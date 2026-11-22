"""Central one-use handoff issuance, reservation and source-receipt reconciliation."""

from dataclasses import dataclass, field
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import text

from app.modules.hosted_access.application.handoff_channel import ContinuationTarget
from app.modules.hosted_access.application.identity_evidence import (
    HandoffEvidence,
    IdentityCommandResult,
    ManagedObservation,
    SourceBindingAssertion,
)
from app.modules.hosted_access.application.identity_setup import DAY, MINUTE
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.modules.hosted_access.infrastructure.handoff_signing import verify_evidence
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.sqlite_engine import immediate_transaction


@dataclass(frozen=True)
class IssuedHandoff:
    target_origin: str
    token: SecretStr = field(repr=False)


def _one(connection, query, identifier):
    row = connection.execute(text(query), {"id": identifier}).mappings().one_or_none()
    if row is None:
        raise ProviderDenied()
    return row


def _observation(row):
    return ManagedObservation(
        managed_session_id=row["managed_session_id"],
        revision=row["revision"],
        issuer=row["issuer"],
        subject=row["subject"],
        method=row["method"],
        purpose=row["purpose"],
        operator_id=row["operator_id"],
        email_verified=True,
        authenticated_at=row["authenticated_at"],
        mfa_verified_at=row["mfa_verified_at"],
        issued_at=row["issued_at"],
        provider_valid_until=row["provider_valid_until"],
        remembered_until=row["remembered_until"],
        checked_at=row["revocation_checked_at"],
        valid_until=row["revocation_valid_until"],
        revoked=row["revoked_at"] is not None,
    )


class PairingSource:
    """Verify the source signature and check the authenticated source's current attempt."""

    def __init__(self, resolve_key, observe_source, *, clock):
        self.resolve_key, self.observe_source, self.clock = resolve_key, observe_source, clock

    def verify_pairing(self, token):
        grant = verify_evidence(token, SourceBindingAssertion, self.resolve_key, now=self.clock())
        binding, attempt = self.observe_source(grant.binding.scope, grant.source_attempt_id)
        if (
            binding != grant.binding
            or attempt.binding_assertion_hash != digest(token.get_secret_value())
            or attempt.renewal_session_id != (grant.renewal.session_id if grant.renewal else None)
        ):
            raise ProviderDenied()
        return grant, attempt


class CentralHandoffs:
    def __init__(self, attempts, signer, source, readiness, *, deployment_id):
        self.attempts, self.signer, self.source, self.readiness = (
            attempts,
            signer,
            source,
            readiness,
        )
        self.engine, self.clock = attempts.engine, attempts.clock
        self.deployment_id = deployment_id

    def google_ready(self, operator_id):
        with self.engine.connect() as connection:
            row = _one(
                connection, "SELECT * FROM main.operators WHERE operator_id=:id", operator_id
            )
            enabled, epoch = row["desired_access"] == "enabled", row["access_epoch"]
        return enabled and self.readiness.ready(operator_id, epoch)

    def continuation_target(self, continuation_id, binding):
        if binding.deployment_id != self.deployment_id:
            raise ProviderDenied()
        with self.engine.connect() as connection:
            row = _one(
                connection,
                "SELECT * FROM main.email_continuations WHERE continuation_id=:id",
                continuation_id,
            )
            managed = _one(
                connection,
                "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id",
                row["managed_session_id"],
            )
            original = _one(
                connection,
                "SELECT * FROM main.login_attempts WHERE attempt_id=:id",
                row["original_attempt_id"],
            )
            if (
                row["state"] != "verified"
                or row["operator_id"] != binding.scope.operator_id
                or row["target_origin"] != binding.target_origin
                or row["access_epoch"] != binding.access_epoch
                or managed["revoked_at"] is not None
                or (managed["issuer"], managed["subject"]) != (binding.issuer, binding.subject)
            ):
                raise ProviderDenied()
            # Pairing may run before activation, but cannot change binding.
            operator = _one(
                connection, "SELECT * FROM main.operators WHERE operator_id=:id", row["operator_id"]
            )
            if (
                operator["workspace_id"] != binding.scope.workspace_id
                or operator["desired_access"] == "retired"
                or operator["revision"] != binding.assignment_revision
                or operator["access_epoch"] != binding.access_epoch
                or operator["issuer"] != binding.issuer
                or operator["subject"] not in {None, binding.subject}
            ):
                raise ProviderDenied()
            expires = min(
                row["expires_at"],
                managed["provider_valid_until"],
                managed["revocation_valid_until"],
                managed["remembered_until"],
            )
            if not row["created_at"] <= self.clock() < expires:
                raise ProviderDenied()
        renewal = None
        if original["purpose"] == "renewal":
            observed_binding, _, renewal = self.source.observe(
                row["operator_id"], original["source_attempt_id"]
            )
            if (
                observed_binding != binding
                or renewal is None
                or renewal.managed_session_id != original["parent_managed_session_id"]
                or renewal.remembered_until != managed["remembered_until"]
            ):
                raise ProviderDenied()
        return ContinuationTarget(
            binding=binding,
            return_path=original["return_path"],
            renewal=renewal,
            remembered=renewal.remembered
            if renewal is not None
            else (managed["remembered_until"] == managed["authenticated_at"] + 30 * DAY),
            expires_at=expires,
        )

    def issue_google(self, attempt_id, browser, cookie):
        with self.engine.connect() as connection:
            attempt = self.attempts.attempt(connection, attempt_id, browser)
            managed = attempt["completed_managed_session_id"]
        if managed is None:
            raise ProviderDenied()
        return self.issue(attempt_id, browser, managed, cookie)

    def issue_paired(self, continuation_id, browser, cookie):
        with self.engine.connect() as connection:
            row = _one(
                connection,
                "SELECT * FROM main.email_continuations WHERE continuation_id=:id",
                continuation_id,
            )
        if row["state"] != "paired":
            raise ProviderDenied()
        return self.issue(row["replacement_attempt_id"], browser, row["managed_session_id"], cookie)

    def issue(self, attempt_id, browser, managed_id, cookie):
        """Called only with the current managed completion or the paired continuation."""
        with self.engine.connect() as connection:
            attempt = self.attempts.attempt(connection, attempt_id, browser)
            operator_id, source_id = attempt["operator_id"], attempt["source_attempt_id"]
        binding, source_attempt, renewal = self.source.observe(operator_id, source_id)
        if not self.readiness.ready(operator_id, binding.access_epoch):
            return None
        with immediate_transaction(self.engine) as connection:
            attempt = self.attempts.attempt(connection, attempt_id, browser)
            managed = _one(
                connection,
                "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id",
                managed_id,
            )
            if not compare_digest(managed["cookie_hash"], digest(cookie.get_secret_value())):
                raise ProviderDenied()
            continuation = self._issuing_attempt(
                connection, attempt, source_attempt, managed, binding, renewal
            )
            self._current(connection, binding)
            now = self.clock()
            observation = _observation(managed)
            expires = min(
                now + 5 * MINUTE,
                source_attempt.expires_at,
                attempt["expires_at"],
                observation.valid_until,
                observation.remembered_until,
            )
            if expires <= now or observation.revoked:
                raise ProviderDenied()
            existing = connection.scalar(
                text(
                    "SELECT 1 FROM main.identity_commands WHERE kind='issue_handoff' AND idempotency_key=:id"
                ),
                {"id": attempt_id},
            )
            if existing:
                raise ProviderDenied()
            grant = HandoffEvidence(
                key_id=self.signer.key_id,
                binding=binding,
                operation_id=str(uuid4()),
                request_hash=digest(attempt_id + ":" + managed_id),
                nonce_hash=digest(token_urlsafe(32)),
                issued_at=now,
                expires_at=expires,
                handoff_id=str(uuid4()),
                attempt_id=attempt_id,
                source_attempt_id=source_attempt.attempt_id,
                source_browser_hash=source_attempt.browser_challenge_hash,
                managed=observation,
                renewal=renewal,
            )
            token = self.signer.sign(grant)
            self._record_issue(connection, grant, token, continuation)
        return IssuedHandoff(binding.target_origin, token)

    @staticmethod
    def _issuing_attempt(connection, attempt, source, managed, binding, renewal):
        if (
            (attempt["purpose"] == "renewal") != (renewal is not None)
            or attempt["operator_id"] != binding.scope.operator_id
            or attempt["source_attempt_id"] != source.attempt_id
            or attempt["source_browser_hash"] != source.browser_challenge_hash
            or attempt["target_origin"] != binding.target_origin
            or attempt["method"] != managed["method"]
            or source.state != "pending"
            or source.access_epoch != binding.access_epoch
            or source.resource_generation != binding.resource_generation
            or (
                source.continuation_id is not None
                and source.remembered
                != (
                    renewal.remembered
                    if renewal is not None
                    else managed["remembered_until"] == managed["authenticated_at"] + 30 * DAY
                )
            )
            or (
                renewal is not None
                and (
                    attempt["parent_managed_session_id"] != renewal.managed_session_id
                    or managed["remembered_until"] != renewal.remembered_until
                    or (
                        managed["authenticated_at"] < source.created_at
                        and source.continuation_id is None
                    )
                )
            )
        ):
            raise ProviderDenied()
        if attempt["method"] == "google":
            if (
                attempt["state"] != "completed"
                or attempt["completed_managed_session_id"] != managed["managed_session_id"]
                or source.continuation_id is not None
            ):
                raise ProviderDenied()
            return None
        continuation = _one(
            connection,
            "SELECT * FROM main.email_continuations WHERE replacement_attempt_id=:id",
            attempt["attempt_id"],
        )
        if (
            attempt["state"] != "verified"
            or (
                renewal is None
                and attempt["parent_managed_session_id"] != managed["managed_session_id"]
            )
            or continuation["state"] != "paired"
            or continuation["managed_session_id"] != managed["managed_session_id"]
            or continuation["source_attempt_id"] != source.attempt_id
            or continuation["source_binding_hash"] != source.binding_assertion_hash
            or continuation["continuation_id"] != source.continuation_id
            or continuation["handoff_id"] is not None
        ):
            raise ProviderDenied()
        return continuation["continuation_id"]

    def _current(self, connection, binding):
        row = _one(
            connection,
            "SELECT * FROM main.operators WHERE operator_id=:id",
            binding.scope.operator_id,
        )
        if (
            binding.deployment_id != self.deployment_id
            or row["workspace_id"] != binding.scope.workspace_id
            or row["desired_access"] != "enabled"
            or row["revision"] != binding.assignment_revision
            or row["access_epoch"] != binding.access_epoch
            or row["issuer"] != binding.issuer
            or row["subject"] != binding.subject
        ):
            raise ProviderDenied()

    @staticmethod
    def _command(connection, grant, *, kind, operation_id, key, state, result=None, now):
        connection.execute(
            text("""
            INSERT INTO main.identity_commands (
                operation_id, kind, idempotency_key, request_hash, operator_id,
                managed_session_id, attempt_id, access_epoch, state, result_json,
                created_at, updated_at, revision
            ) VALUES (:id, :kind, :key, :hash, :operator, :managed, :attempt, :epoch,
                      :state, :result, :now, :now, 1)
        """),
            {
                "id": operation_id,
                "kind": kind,
                "key": key,
                "hash": semantic_hash(grant),
                "operator": grant.binding.scope.operator_id,
                "managed": grant.managed.managed_session_id,
                "attempt": grant.attempt_id,
                "epoch": grant.binding.access_epoch,
                "state": state,
                "result": result.model_dump_json() if result else None,
                "now": now,
            },
        )

    def _record_issue(self, connection, grant, token, continuation):
        issue_id = str(uuid4())
        self._command(
            connection,
            grant,
            kind="issue_handoff",
            operation_id=issue_id,
            key=grant.attempt_id,
            state="succeeded",
            now=grant.issued_at,
            result=IdentityCommandResult(
                kind="issue_handoff", result_id=grant.handoff_id, source_receipt_ref=None
            ),
        )
        connection.execute(
            text("""
            INSERT INTO main.login_handoffs (
                handoff_id, operator_id, browser_state_hash, nonce_hash, code_hash,
                target_origin, issuer, subject, assignment_revision, access_epoch,
                state, expires_at, created_at, attempt_id, managed_session_id, identity_operation_id
            ) VALUES (:id, :operator, :browser, :nonce, :code, :origin, :issuer, :subject,
                      :assignment, :epoch, 'issued', :expires, :now, :attempt, :managed, :issue)
        """),
            {
                "id": grant.handoff_id,
                "operator": grant.binding.scope.operator_id,
                "browser": grant.source_browser_hash,
                "nonce": grant.nonce_hash,
                "code": digest(token.get_secret_value()),
                "origin": grant.binding.target_origin,
                "issuer": grant.binding.issuer,
                "subject": grant.binding.subject,
                "assignment": grant.binding.assignment_revision,
                "epoch": grant.binding.access_epoch,
                "expires": grant.expires_at,
                "now": grant.issued_at,
                "attempt": grant.attempt_id,
                "managed": grant.managed.managed_session_id,
                "issue": issue_id,
            },
        )
        if continuation is not None:
            connection.execute(
                text("""
                UPDATE main.email_continuations SET handoff_id=:handoff, revision=revision+1
                WHERE continuation_id=:id
            """),
                {"id": continuation, "handoff": grant.handoff_id},
            )
        self._audit(
            connection, grant.binding.scope.operator_id, "issue_handoff", issue_id, grant.issued_at
        )

    @staticmethod
    def _audit(connection, operator, kind, operation_id, now):
        connection.execute(
            text("""
            INSERT INTO main.admin_audit
                (audit_id, actor_ref, action, operator_id, recorded_at, safe_facts_json)
            VALUES (:id, 'central-identity', :kind, :operator, :now,
                    json_object('identity_operation_id', :operation))
        """),
            {
                "id": str(uuid4()),
                "kind": kind,
                "operator": operator,
                "now": now,
                "operation": operation_id,
            },
        )

    def reserve(self, token, grant):
        """Called via the authenticated source channel. Retried reservations keep intent."""
        if not self.readiness.ready(grant.binding.scope.operator_id, grant.binding.access_epoch):
            raise ProviderDenied()
        with immediate_transaction(self.engine) as connection:
            self._current(connection, grant.binding)
            row = _one(
                connection,
                "SELECT * FROM main.login_handoffs WHERE handoff_id=:id",
                grant.handoff_id,
            )
            issue = _one(
                connection,
                "SELECT * FROM main.identity_commands WHERE operation_id=:id",
                row["identity_operation_id"],
            )
            managed = _one(
                connection,
                "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id",
                row["managed_session_id"],
            )
            now = self.clock()
            if (
                row["state"] not in {"issued", "redeeming"}
                or not row["created_at"] <= now < row["expires_at"]
                or not compare_digest(row["code_hash"], digest(token.get_secret_value()))
                or issue["request_hash"] != semantic_hash(grant)
                or _observation(managed) != grant.managed
            ):
                raise ProviderDenied()
            if row["state"] == "issued":
                self._command(
                    connection,
                    grant,
                    kind="renew_session" if grant.renewal is not None else "redeem_handoff",
                    operation_id=grant.operation_id,
                    key=grant.handoff_id,
                    state="pending",
                    now=now,
                )
                connection.execute(
                    text("UPDATE main.login_handoffs SET state='redeeming' WHERE handoff_id=:id"),
                    {"id": grant.handoff_id},
                )

    def acknowledge(self, receipt):
        # An observed receipt, fetched through the owning peer, can finish a
        # committed source result after expiry or a lost acknowledgement.
        if (
            receipt.kind not in {"issue_session", "refresh_session"}
            or receipt.binding.deployment_id != self.deployment_id
            or self.source.original(receipt) != receipt
        ):
            raise ProviderDenied()
        kind = "renew_session" if receipt.kind == "refresh_session" else "redeem_handoff"
        with immediate_transaction(self.engine) as connection:
            row = _one(
                connection,
                "SELECT * FROM main.login_handoffs WHERE handoff_id=:id",
                receipt.handoff_id,
            )
            operation = _one(
                connection,
                "SELECT * FROM main.identity_commands WHERE operation_id=:id",
                receipt.operation_id,
            )
            if (
                operation["kind"] != kind
                or operation["idempotency_key"] != receipt.handoff_id
                or operation["request_hash"] != receipt.request_hash
                or operation["operator_id"] != receipt.binding.scope.operator_id
                or operation["access_epoch"] != receipt.binding.access_epoch
                or not operation["created_at"] <= receipt.recorded_at < row["expires_at"]
            ):
                raise ProviderDenied()
            ref = "source-receipt:" + receipt.operation_id
            if row["state"] == "redeemed" and row["source_receipt_ref"] == ref:
                return
            if row["state"] != "redeeming" or operation["state"] != "pending":
                raise ProviderDenied()
            result = IdentityCommandResult(
                kind=kind, result_id=receipt.handoff_id, source_receipt_ref=ref
            )
            now = self.clock()
            connection.execute(
                text("""
                UPDATE main.identity_commands SET state='succeeded', result_json=:result,
                    source_receipt_ref=:ref, updated_at=:now, revision=revision+1 WHERE operation_id=:id
            """),
                {
                    "result": result.model_dump_json(),
                    "ref": ref,
                    "now": now,
                    "id": receipt.operation_id,
                },
            )
            connection.execute(
                text("""
                UPDATE main.login_handoffs SET state='redeemed', redeemed_at=:recorded,
                    source_receipt_ref=:ref WHERE handoff_id=:id
            """),
                {"recorded": receipt.recorded_at, "ref": ref, "id": receipt.handoff_id},
            )
            connection.execute(
                text("""
                UPDATE main.email_continuations SET state='completed', revision=revision+1
                WHERE handoff_id=:id AND state='paired'
            """),
                {"id": receipt.handoff_id},
            )
            connection.execute(
                text("""
                UPDATE main.login_attempts SET state='completed', revision=revision+1
                WHERE attempt_id=:id AND state='verified'
            """),
                {"id": row["attempt_id"]},
            )
            if receipt.replaced_device_managed_id is not None:
                connection.execute(
                    text("""
                    UPDATE main.managed_identity_sessions SET revoked_at=:now, revision=revision+1
                    WHERE managed_session_id=:id AND purpose='operator' AND operator_id=:operator
                      AND issuer=:issuer AND subject=:subject AND revoked_at IS NULL AND issued_at<=:now
                """),
                    {
                        "id": receipt.replaced_device_managed_id,
                        "operator": operation["operator_id"],
                        "issuer": receipt.binding.issuer,
                        "subject": receipt.binding.subject,
                        "now": now,
                    },
                )
            self._audit(connection, operation["operator_id"], kind, receipt.operation_id, now)
