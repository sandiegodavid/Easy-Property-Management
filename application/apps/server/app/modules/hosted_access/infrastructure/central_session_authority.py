"""Issue scoped status and recent-proof evidence from the central owner."""

from dataclasses import dataclass
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import text

from app.modules.hosted_access.application.identity_evidence import (
    IdentityCommandResult,
    ManagedObservation,
    RecentAuthGrant,
    SessionObservationGrant,
)
from app.modules.hosted_access.application.identity_setup import MINUTE
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.modules.hosted_access.infrastructure.central_handoffs import _observation, _one
from app.modules.hosted_access.infrastructure.source_sessions import observation_hash
from app.platform.sqlite_engine import immediate_transaction
from app.platform.hosted_contracts.operations import original_result


@dataclass(frozen=True)
class ProviderStatusTarget:
    realm: str
    subject: str


def _managed(connection, identifier, binding):
    row = _one(
        connection,
        "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id",
        identifier,
    )
    if (
        row["purpose"] != "operator"
        or row["operator_id"] != binding.scope.operator_id
        or (row["issuer"], row["subject"]) != (binding.issuer, binding.subject)
    ):
        raise ProviderDenied()
    return row


class CentralSessionAuthority:
    def __init__(self, handoffs, provider):
        self.handoffs, self.provider = handoffs, provider
        self.engine, self.clock, self.signer = handoffs.engine, handoffs.clock, handoffs.signer

    def observe(self, binding, session_id, managed_id):
        with self.engine.connect() as connection:
            self.handoffs._current(connection, binding)
            row = _managed(connection, managed_id, binding)
            if self.clock() >= min(row["provider_valid_until"], row["remembered_until"]):
                raise ProviderDenied()
        status = self.provider.status_cache.account_status(
            ProviderStatusTarget(binding.issuer, binding.subject)
        )
        if status.status.subject != binding.subject:
            raise ProviderDenied()
        with immediate_transaction(self.engine) as connection:
            self.handoffs._current(connection, binding)
            row = _managed(connection, managed_id, binding)
            now = self.clock()
            until = min(status.valid_until, row["provider_valid_until"])
            checked_at = max(row["issued_at"], status.checked_at)
            if status.checked_at > now or not row["issued_at"] <= checked_at <= now < min(
                until, row["remembered_until"]
            ):
                raise ProviderUnavailable()
            revoke = status.status.disabled or row["authenticated_at"] < status.status.valid_since
            revoked_at = (
                row["revoked_at"] if row["revoked_at"] is not None else now if revoke else None
            )
            if checked_at >= row["revocation_checked_at"] and (
                until > row["revocation_valid_until"] or revoked_at != row["revoked_at"]
            ):
                connection.execute(
                    text("""
                    UPDATE main.managed_identity_sessions SET revocation_checked_at=:checked,
                        revocation_valid_until=:until, revoked_at=:revoked, revision=revision+1
                    WHERE managed_session_id=:id
                """),
                    {
                        "checked": checked_at,
                        "until": max(until, row["revocation_valid_until"]),
                        "revoked": revoked_at,
                        "id": managed_id,
                    },
                )
                row = _managed(connection, managed_id, binding)
            managed = _observation(row)
        return self.signer.sign(
            SessionObservationGrant(
                key_id=self.signer.key_id,
                binding=binding,
                operation_id=str(uuid4()),
                request_hash=observation_hash(session_id, managed_id),
                nonce_hash=digest(token_urlsafe(32)),
                issued_at=now,
                expires_at=min(now + 5 * MINUTE, managed.valid_until, managed.remembered_until),
                managed=managed,
            )
        )

    def reconcile_revocation(self, binding, command):
        if (
            command.intent.kind != "revoke"
            or command.intent.deployment_id != binding.deployment_id
            or command.intent.scope != binding.scope
            or command.intent.access_epoch != binding.access_epoch
        ):
            raise ProviderDenied()
        outcome = original_result(command, self.handoffs.source.original_control(command))
        if outcome is None or outcome.result is None or outcome.result.revocation is None:
            raise ProviderUnavailable()
        result = outcome.result.revocation
        if outcome.result.access_epoch != binding.access_epoch or (
            command.intent.payload.all_devices != (result.not_before is not None)
        ):
            raise ProviderDenied()
        with immediate_transaction(self.engine) as connection:
            assignment = _one(
                connection,
                "SELECT * FROM main.operators WHERE operator_id=:id",
                binding.scope.operator_id,
            )
            if (
                binding.deployment_id != self.handoffs.deployment_id
                or assignment["workspace_id"] != binding.scope.workspace_id
                or assignment["access_epoch"] < binding.access_epoch
            ):
                raise ProviderDenied()
            values = {
                "operator": binding.scope.operator_id,
                "issuer": binding.issuer,
                "subject": binding.subject,
                "now": self.clock(),
                "managed": result.managed_session_id,
                "fence": result.not_before,
                "operation": outcome.operation.operation_id,
                "hash": outcome.operation.request_hash,
            }
            recorded = (
                connection.execute(
                    text("""
                SELECT action,operator_id,json_extract(safe_facts_json,'$.request_hash') AS request_hash
                FROM main.admin_audit WHERE audit_id=:operation
            """),
                    values,
                )
                .mappings()
                .one_or_none()
            )
            kind = "revoke_all" if result.not_before is not None else "revoke_session"
            if recorded is not None:
                if (recorded["action"], recorded["operator_id"], recorded["request_hash"]) != (
                    kind,
                    binding.scope.operator_id,
                    outcome.operation.request_hash,
                ):
                    raise ProviderDenied()
                return
            connection.execute(
                text("""
                UPDATE main.managed_identity_sessions SET revoked_at=:now,revision=revision+1
                WHERE operator_id=:operator AND issuer=:issuer AND subject=:subject
                AND purpose='operator' AND revoked_at IS NULL AND issued_at<=:now
                AND ((:managed IS NOT NULL AND managed_session_id=:managed)
                  OR (:fence IS NOT NULL AND authenticated_at<:fence))
            """),
                values,
            )
            connection.execute(
                text("""
                INSERT INTO main.admin_audit (audit_id,actor_ref,action,operator_id,recorded_at,safe_facts_json)
                VALUES (:operation,'central-identity',:kind,:operator,:now,json_object('request_hash',:hash))
            """),
                values | {"kind": kind},
            )

    def start_recent(self, binding, challenge_id):
        challenge = self.handoffs.source.observe_recent(binding, challenge_id)
        if challenge.binding != binding or challenge.challenge_id != challenge_id:
            raise ProviderDenied()
        browser, attempt = token_urlsafe(32), str(uuid4())
        now = self.clock()
        with immediate_transaction(self.engine) as connection:
            self.handoffs._current(connection, binding)
            _managed(connection, challenge.managed_session_id, binding)
            count = connection.scalar(
                text("""
                SELECT count(*) FROM main.login_attempts WHERE operator_id=:operator
                AND purpose='recent_auth' AND state IN ('pending','verified') AND expires_at>:now
            """),
                {"operator": binding.scope.operator_id, "now": now},
            )
            if count >= 32 or not now < challenge.expires_at:
                raise ProviderDenied()
            connection.execute(
                text("""
                INSERT INTO main.login_attempts (
                    attempt_id,purpose,operator_id,parent_managed_session_id,source_attempt_id,
                    source_browser_hash,central_browser_hash,method,target_origin,return_path,
                    confirmed_request_hash,state,created_at,expires_at,revision
                ) VALUES (:id,'recent_auth',:operator,:parent,:challenge,:source_hash,:browser,
                          'google',:origin,'/',:hash,'pending',:now,:expires,1)
            """),
                {
                    "id": attempt,
                    "operator": binding.scope.operator_id,
                    "parent": challenge.managed_session_id,
                    "challenge": challenge_id,
                    "source_hash": digest(challenge_id),
                    "browser": digest(browser),
                    "origin": binding.target_origin,
                    "hash": challenge.request_hash,
                    "now": now,
                    "expires": challenge.expires_at,
                },
            )
        return attempt, browser

    def complete_recent(self, binding, attempt_id, browser, token, *, require_mfa=False):
        if not isinstance(browser, str) or len(browser) != 43:
            raise ProviderDenied()
        with immediate_transaction(self.engine) as connection:
            row = self._recent_attempt(connection, binding, attempt_id, browser, "pending")
            connection.execute(
                text("""
                UPDATE main.login_attempts SET state='verified',revision=revision+1 WHERE attempt_id=:id
            """),
                {"id": attempt_id},
            )
        challenge = self.handoffs.source.observe_recent(binding, row["source_attempt_id"])
        if (
            challenge.binding != binding
            or challenge.challenge_id != row["source_attempt_id"]
            or challenge.request_hash != row["confirmed_request_hash"]
            or challenge.managed_session_id != row["parent_managed_session_id"]
        ):
            raise ProviderDenied()
        _, proof = self.provider.complete_google(token, remembered=False, admin=require_mfa)
        status = self.provider.status_cache.observe(proof)
        with immediate_transaction(self.engine) as connection:
            row = self._recent_attempt(connection, binding, attempt_id, browser, "verified")
            prior = _managed(connection, challenge.managed_session_id, binding)
            now = self.clock()
            expires = min(row["expires_at"], status.valid_until, prior["remembered_until"])
            if (
                (proof.realm, proof.subject) != (binding.issuer, binding.subject)
                or proof.method != ("google_totp" if require_mfa else "google")
                or (require_mfa and proof.mfa_verified_at is None)
                or prior["revoked_at"] is not None
                or not max(row["created_at"], prior["authenticated_at"] + 1)
                <= proof.authenticated_at
                <= proof.issued_at
                <= now
                < expires
            ):
                raise ProviderDenied()
            managed = ManagedObservation(
                managed_session_id=str(uuid4()),
                revision=1,
                issuer=binding.issuer,
                subject=binding.subject,
                method=proof.method,
                purpose="operator",
                operator_id=binding.scope.operator_id,
                email_verified=True,
                authenticated_at=proof.authenticated_at,
                mfa_verified_at=proof.mfa_verified_at,
                issued_at=proof.issued_at,
                provider_valid_until=proof.expires_at,
                remembered_until=expires,
                checked_at=max(status.checked_at, proof.issued_at),
                valid_until=status.valid_until,
                revoked=False,
            )
            if connection.scalar(
                text("""
                SELECT 1 FROM main.identity_commands
                WHERE kind='recent_auth' AND idempotency_key=:key
            """),
                {"key": challenge.challenge_id},
            ):
                raise ProviderDenied()
            result = IdentityCommandResult(
                kind="recent_auth",
                result_id=challenge.challenge_id,
                source_receipt_ref=None,
            )
            operation_id = str(uuid4())
            connection.execute(
                text("""
                INSERT INTO main.identity_commands (
                    operation_id,kind,idempotency_key,request_hash,operator_id,managed_session_id,
                    attempt_id,access_epoch,state,result_json,created_at,updated_at,revision
                ) VALUES (:id,'recent_auth',:key,:hash,:operator,:managed,:attempt,:epoch,
                          'succeeded',:result,:now,:now,1)
            """),
                {
                    "id": operation_id,
                    "key": challenge.challenge_id,
                    "hash": challenge.request_hash,
                    "operator": binding.scope.operator_id,
                    "managed": challenge.managed_session_id,
                    "attempt": attempt_id,
                    "epoch": binding.access_epoch,
                    "result": result.model_dump_json(),
                    "now": now,
                },
            )
            connection.execute(
                text("""
                UPDATE main.login_attempts SET state='completed',revision=revision+1 WHERE attempt_id=:id
            """),
                {"id": attempt_id},
            )
            self.handoffs._audit(
                connection,
                binding.scope.operator_id,
                "recent_auth",
                operation_id,
                now,
            )
        return self.signer.sign(
            RecentAuthGrant(
                key_id=self.signer.key_id,
                binding=binding,
                operation_id=challenge.challenge_id,
                request_hash=challenge.request_hash,
                nonce_hash=digest(challenge.challenge_id),
                issued_at=now,
                expires_at=expires,
                session_id=challenge.session_id,
                managed=managed,
            )
        )

    def _recent_attempt(self, connection, binding, attempt_id, browser, state):
        self.handoffs._current(connection, binding)
        row = _one(connection, "SELECT * FROM main.login_attempts WHERE attempt_id=:id", attempt_id)
        if (
            row["purpose"] != "recent_auth"
            or row["state"] != state
            or row["operator_id"] != binding.scope.operator_id
            or row["target_origin"] != binding.target_origin
            or not row["created_at"] <= self.clock() < row["expires_at"]
            or not compare_digest(row["central_browser_hash"], digest(browser))
        ):
            raise ProviderDenied()
        return row
