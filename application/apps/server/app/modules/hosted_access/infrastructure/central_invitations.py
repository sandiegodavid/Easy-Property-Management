"""Explicit Admin invitation issuance and central claim receipts."""

from hmac import compare_digest
import json
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.central_login import (
    UnavailableClaimReadiness,
    UnavailableSourceClaim,
    ClaimSourceReceipt,
)
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.platform.sqlite_engine import immediate_transaction


class CentralInvitations:
    def __init__(self, engine, admin_sessions, *, clock, readiness=None, source_claim=None):
        self.engine, self.admin_sessions, self.clock = engine, admin_sessions, clock
        self.readiness = readiness or UnavailableClaimReadiness()
        self.source_claim = source_claim or UnavailableSourceClaim()

    def issue(self, admin_cookie, operator_id, *, expected_revision, access_epoch, expires_at):
        admin = self.admin_sessions.authenticate(admin_cookie, sensitive=True)
        token, identifier = token_urlsafe(32), str(uuid4())
        with immediate_transaction(self.engine) as connection:
            admin = self.admin_sessions._load(connection, admin_cookie)
            principal = self.admin_sessions._principal(connection, admin.principal_id)
            from app.modules.hosted_access.application.admin_admission import require_admin_session

            require_admin_session(admin, principal, now=self.clock(), sensitive=True)
            row = (
                connection.execute(
                    text("SELECT * FROM main.operators WHERE operator_id=:id"), {"id": operator_id}
                )
                .mappings()
                .one_or_none()
            )
            now = self.clock()
            if (
                row is None
                or row["revision"] != expected_revision
                or row["access_epoch"] != access_epoch
                or row["subject"] is not None
                or row["desired_access"] == "retired"
                or not now < expires_at
            ):
                raise ProviderDenied()
            connection.execute(
                text(
                    "UPDATE main.operators SET revision=revision+1, updated_at=:now WHERE operator_id=:id"
                ),
                {"now": now, "id": operator_id},
            )
            connection.execute(
                text(
                    "UPDATE main.invitations SET state='revoked', revision=revision+1 "
                    "WHERE operator_id=:id AND state IN ('pending_delivery','sent')"
                ),
                {"id": operator_id},
            )
            connection.execute(
                text("""
                INSERT INTO main.invitations (
                    invitation_id, operator_id, token_hash, email_key, assignment_revision,
                    access_epoch, state, expires_at, created_at, revision
                ) VALUES (:id,:operator,:token,:email,:revision,:epoch,'pending_delivery',:expires,:now,1)
            """),
                {
                    "id": identifier,
                    "operator": operator_id,
                    "token": digest(token),
                    "email": row["email_key"],
                    "revision": expected_revision + 1,
                    "epoch": access_epoch,
                    "expires": expires_at,
                    "now": now,
                },
            )
            self.audit(
                connection,
                "invitation_issue",
                admin.principal_id,
                {"invitation_id": identifier},
                operator_id,
            )
        return identifier, SecretStr(token)

    def claim_from_source(self, attempts, context, attempt_id, managed_id, *, central_cookie):
        # The injected source owner authenticates its retained invitation capability
        # and browser binding. Browser JSON cannot supply this context.
        verified = attempts.source.inspect_start(context.operator_id, context.source_attempt_id)
        if verified != context or context.invitation_id is None:
            raise ProviderDenied()
        attempts.source.current(context)
        return self._claim(
            attempt_id,
            managed_id,
            context.invitation_id,
            context.invitation_hash,
            central_cookie=central_cookie,
        )

    def claim(self, attempt_id, managed_id, invitation_id, token, *, central_cookie):
        return self._claim(
            attempt_id,
            managed_id,
            invitation_id,
            digest(token.get_secret_value()),
            central_cookie=central_cookie,
        )

    def _claim(self, attempt_id, managed_id, invitation_id, token_hash, *, central_cookie):
        with self.engine.connect() as connection:
            attempt = (
                connection.execute(
                    text("SELECT * FROM main.login_attempts WHERE attempt_id=:id"),
                    {"id": attempt_id},
                )
                .mappings()
                .one_or_none()
            )
            if attempt is None:
                raise ProviderDenied()
            operator = connection.execute(
                text("SELECT access_epoch FROM main.operators WHERE operator_id=:id"),
                {"id": attempt["operator_id"]},
            ).one()
            prior_key = attempt_id + ":" + managed_id + ":" + invitation_id
            prior_hash = digest(prior_key + ":" + token_hash)
            owned = (
                connection.execute(
                    text(
                        "SELECT cookie_hash, revoked_at, provider_valid_until, revocation_valid_until "
                        "FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                    ),
                    {"id": managed_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                owned is None
                or owned["revoked_at"] is not None
                or self.clock()
                >= min(owned["provider_valid_until"], owned["revocation_valid_until"])
                or not compare_digest(
                    owned["cookie_hash"], digest(central_cookie.get_secret_value())
                )
            ):
                raise ProviderDenied()
            original = (
                connection.execute(
                    text(
                        "SELECT * FROM main.identity_commands "
                        "WHERE kind='claim' AND idempotency_key=:key"
                    ),
                    {"key": prior_key},
                )
                .mappings()
                .one_or_none()
            )
            if original:
                if original["request_hash"] != prior_hash:
                    raise ProviderDenied()
                if original["state"] == "succeeded":
                    return json.loads(original["result_json"])
                retained = dict(original)
                connection.rollback()
                return self._reconcile(retained)
        ready = self.readiness.ready(attempt["operator_id"], operator.access_epoch)
        try:
            with immediate_transaction(self.engine) as connection:
                owned = connection.execute(
                    text(
                        "SELECT cookie_hash FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                    ),
                    {"id": managed_id},
                ).scalar_one_or_none()
                if owned is None or not compare_digest(
                    owned, digest(central_cookie.get_secret_value())
                ):
                    raise ProviderDenied()
                # A matching original receipt is inspected before current readiness or invite state.
                key = attempt_id + ":" + managed_id + ":" + invitation_id
                request_hash = digest(key + ":" + token_hash)
                prior = (
                    connection.execute(
                        text(
                            "SELECT * FROM main.identity_commands WHERE kind='claim' AND idempotency_key=:key"
                        ),
                        {"key": key},
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior:
                    if prior["request_hash"] != request_hash:
                        raise ProviderDenied()
                    return (
                        json.loads(prior["result_json"])
                        if prior["state"] == "succeeded"
                        else {"state": "claim_needs_checking"}
                    )
                managed = (
                    connection.execute(
                        text(
                            "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                        ),
                        {"id": managed_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                invite = (
                    connection.execute(
                        text("SELECT * FROM main.invitations WHERE invitation_id=:id"),
                        {"id": invitation_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                current = (
                    connection.execute(
                        text("SELECT * FROM main.operators WHERE operator_id=:id"),
                        {"id": attempt["operator_id"]},
                    )
                    .mappings()
                    .one()
                )
                now = self.clock()
                if (
                    managed is None
                    or invite is None
                    or managed["operator_id"] != current["operator_id"]
                    or managed["purpose"] != "operator"
                    or managed["revoked_at"] is not None
                    or not managed["issued_at"]
                    <= now
                    < min(managed["provider_valid_until"], managed["revocation_valid_until"])
                    or attempt["state"] not in {"completed", "superseded"}
                    or now >= attempt["expires_at"]
                    or current["desired_access"] != "enabled"
                    or invite["operator_id"] != current["operator_id"]
                    or invite["state"] not in {"pending_delivery", "sent"}
                    or now >= invite["expires_at"]
                    or invite["access_epoch"] != current["access_epoch"]
                    or current["access_epoch"] != operator.access_epoch
                    or invite["assignment_revision"] != current["revision"]
                    or invite["email_key"] != managed["email_key"]
                    or current["issuer"] != managed["issuer"]
                    or current["subject"] not in {None, managed["subject"]}
                    or not compare_digest(invite["token_hash"], token_hash)
                ):
                    raise ProviderDenied()
                if not ready or current["setup_state"] != "ready_for_claim":
                    return {"state": "workspace_not_ready"}
                connection.execute(
                    text(
                        "UPDATE main.invitations SET state='claimed', claimed_at=:now, claimed_issuer=:issuer, "
                        "claimed_subject=:subject, revision=revision+1 WHERE invitation_id=:id"
                    ),
                    {
                        "now": now,
                        "issuer": managed["issuer"],
                        "subject": managed["subject"],
                        "id": invitation_id,
                    },
                )
                connection.execute(
                    text(
                        "UPDATE main.operators SET subject=:subject, revision=revision+1, updated_at=:now "
                        "WHERE operator_id=:id"
                    ),
                    {"subject": managed["subject"], "now": now, "id": current["operator_id"]},
                )
                operation_id = str(uuid4())
                connection.execute(
                    text("""
                    INSERT INTO main.identity_commands (
                        operation_id, kind, idempotency_key, request_hash, operator_id,
                        managed_session_id, attempt_id, access_epoch, state, result_json,
                        created_at, updated_at, revision
                    ) VALUES (:id,'claim',:key,:hash,:operator,:managed,:attempt,:epoch,
                              'pending',NULL,:now,:now,1)
                """),
                    {
                        "id": operation_id,
                        "key": key,
                        "hash": request_hash,
                        "operator": current["operator_id"],
                        "managed": managed_id,
                        "attempt": attempt_id,
                        "epoch": current["access_epoch"],
                        "now": now,
                    },
                )
                self.audit(
                    connection,
                    "invitation_claim",
                    "central-identity",
                    {"identity_operation_id": operation_id},
                    current["operator_id"],
                )
        except IntegrityError:
            raise ProviderDenied() from None
        command = {
            "operation_id": operation_id,
            "operator_id": current["operator_id"],
            "access_epoch": current["access_epoch"],
            "result_id": invitation_id,
        }
        try:
            receipt = self.source_claim.claim(
                operation_id=operation_id,
                operator_id=current["operator_id"],
                issuer=managed["issuer"],
                subject=managed["subject"],
                access_epoch=current["access_epoch"],
            )
        except ProviderUnavailable:
            self._unknown(operation_id)
            return {"state": "claim_needs_checking"}
        except ProviderDenied:
            self._unknown(operation_id)
            raise
        return self._acknowledge(command, receipt)

    def _unknown(self, operation_id):
        with immediate_transaction(self.engine) as connection:
            connection.execute(
                text(
                    "UPDATE main.identity_commands SET state='unknown', updated_at=:now, revision=revision+1 "
                    "WHERE operation_id=:id AND state='pending'"
                ),
                {"now": self.clock(), "id": operation_id},
            )

    def _reconcile(self, command):
        try:
            receipt = self.source_claim.original(command["operation_id"])
        except ProviderUnavailable:
            return {"state": "claim_needs_checking"}
        if receipt is None:
            return {"state": "claim_needs_checking"}
        invitation = command["idempotency_key"].rsplit(":", 1)[1]
        return self._acknowledge(command | {"result_id": invitation}, receipt)

    def _acknowledge(self, command, receipt):
        if (
            not isinstance(receipt, ClaimSourceReceipt)
            or receipt.operation_id != command["operation_id"]
            or receipt.operator_id != command["operator_id"]
            or receipt.access_epoch != command["access_epoch"]
        ):
            raise ProviderDenied()
        result = {
            "version": 1,
            "kind": "claim",
            "result_id": command["result_id"],
            "source_receipt_ref": receipt.receipt_ref,
        }
        with immediate_transaction(self.engine) as connection:
            original = (
                connection.execute(
                    text(
                        "SELECT state, result_json FROM main.identity_commands WHERE operation_id=:id"
                    ),
                    {"id": command["operation_id"]},
                )
                .mappings()
                .one()
            )
            if original["state"] == "succeeded":
                return json.loads(original["result_json"])
            connection.execute(
                text(
                    "UPDATE main.identity_commands SET state='succeeded', result_json=:result, "
                    "source_receipt_ref=:receipt, updated_at=:now, revision=revision+1 "
                    "WHERE operation_id=:id AND state IN ('pending','unknown')"
                ),
                {
                    "result": json.dumps(result),
                    "receipt": receipt.receipt_ref,
                    "now": self.clock(),
                    "id": command["operation_id"],
                },
            )
        return result

    def audit(self, connection, action, actor, facts, operator_id):
        connection.execute(
            text("""
            INSERT INTO main.admin_audit
                (audit_id, actor_ref, action, operator_id, recorded_at, safe_facts_json)
            VALUES (:id,:actor,:action,:operator,:now,:facts)
        """),
            {
                "id": str(uuid4()),
                "actor": actor,
                "action": action,
                "operator": operator_id,
                "now": self.clock(),
                "facts": json.dumps(facts),
            },
        )
