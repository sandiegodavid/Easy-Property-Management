"""Atomically pair a verified email continuation to its completing browser."""

import json
from hmac import compare_digest
from uuid import uuid4

from sqlalchemy import text

from app.modules.hosted_access.application.identity_setup import DAY, HOUR
from app.modules.hosted_access.application.identity_states import (
    EmailContinuationState,
    LoginAttemptState,
    check_continuation_pairing,
)
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.platform.sqlite_engine import immediate_transaction


def _row(connection, statement, value):
    result = connection.execute(text(statement), {"id": value}).mappings().one_or_none()
    if result is None:
        raise ProviderDenied()
    return result


class CentralPairing:
    def __init__(self, attempts, source, *, deployment_id):
        self.attempts, self.source, self.deployment_id = attempts, source, deployment_id

    def pair(self, continuation_id, assertion, *, origin, browser, cookie):
        # The public identifier is only a selector. Check browser ownership before
        # spending work on signature verification or a call to the source owner.
        with self.attempts.engine.connect() as connection:
            self._session(connection, continuation_id, origin, browser, cookie)
        grant, source = self.source.verify_pairing(assertion)
        assertion_hash = digest(assertion.get_secret_value())
        with immediate_transaction(self.attempts.engine) as connection:
            row, managed, now = self._session(connection, continuation_id, origin, browser, cookie)
            binding = grant.binding
            operator = _row(
                connection, "SELECT * FROM main.operators WHERE operator_id=:id", row["operator_id"]
            )
            if (
                grant.continuation_id != continuation_id
                or binding.deployment_id != self.deployment_id
                or binding.scope.operator_id != row["operator_id"]
                or binding.scope.workspace_id != operator["workspace_id"]
                or binding.target_origin != origin
                or binding.assignment_revision != operator["revision"]
                or binding.access_epoch != row["access_epoch"]
                or operator["access_epoch"] != row["access_epoch"]
                or operator["desired_access"] == "retired"
                or binding.issuer != managed["issuer"]
                or binding.subject != managed["subject"]
                or operator["issuer"] != managed["issuer"]
                or operator["subject"] not in {None, managed["subject"]}
                or grant.source_attempt_id != source.attempt_id
                or grant.source_browser_hash != source.browser_challenge_hash
                or binding.resource_generation != source.resource_generation
                or source.binding_assertion_hash != assertion_hash
                or source.binding_expires_at != grant.expires_at
                or not row["created_at"]
                <= source.created_at
                <= grant.issued_at
                <= now
                < grant.expires_at
                or source.state != "pending"
                or source.remembered
                != (
                    grant.renewal.remembered
                    if grant.renewal is not None
                    else managed["remembered_until"] == managed["authenticated_at"] + 30 * DAY
                )
                or (
                    grant.renewal is None
                    and not source.remembered
                    and managed["remembered_until"] > managed["authenticated_at"] + 8 * HOUR
                )
            ):
                raise ProviderDenied()
            if row["state"] == "paired":
                if row["source_binding_hash"] != assertion_hash:
                    raise ProviderDenied()
                result = _row(
                    connection,
                    "SELECT result_json FROM main.identity_commands "
                    "WHERE kind='pair_email_continuation' AND idempotency_key=:id",
                    continuation_id,
                )
                return json.loads(result["result_json"])

            original = LoginAttemptState.model_validate(
                dict(
                    _row(
                        connection,
                        "SELECT * FROM main.login_attempts WHERE attempt_id=:id",
                        row["original_attempt_id"],
                    )
                )
            )
            if (
                original.state != "superseded"
                or (original.purpose == "renewal") != (grant.renewal is not None)
                or (
                    grant.renewal is not None
                    and (
                        grant.renewal.managed_session_id != original.parent_managed_session_id
                        or grant.renewal.remembered_until != managed["remembered_until"]
                    )
                )
            ):
                raise ProviderDenied()
            replacement = LoginAttemptState(
                attempt_id=str(uuid4()),
                purpose=original.purpose,
                operator_id=row["operator_id"],
                parent_managed_session_id=(
                    grant.renewal.managed_session_id
                    if grant.renewal
                    else managed["managed_session_id"]
                ),
                source_attempt_id=source.attempt_id,
                source_browser_hash=source.browser_challenge_hash,
                central_browser_hash=row["central_browser_hash"],
                method="email_link",
                email_key=original.email_key,
                target_origin=origin,
                return_path=source.return_path,
                confirmed_request_hash=None,
                last_delivery_at=None,
                last_delivery_code=None,
                state="verified",
                created_at=now,
                expires_at=min(row["expires_at"], source.expires_at, grant.expires_at),
                revision=1,
            )
            paired = EmailContinuationState.model_validate(
                dict(row)
                | {
                    "state": "paired",
                    "replacement_attempt_id": replacement.attempt_id,
                    "source_attempt_id": source.attempt_id,
                    "source_binding_hash": assertion_hash,
                    "revision": row["revision"] + 1,
                }
            )
            try:
                check_continuation_pairing(paired, replacement, source, original)
            except ValueError:
                raise ProviderDenied() from None
            self._write(connection, paired, replacement, assertion_hash, now)
            return self._result(continuation_id)

    def _session(self, connection, continuation_id, origin, browser, cookie):
        row = _row(
            connection,
            "SELECT * FROM main.email_continuations WHERE continuation_id=:id",
            continuation_id,
        )
        if (
            row["target_origin"] != origin
            or row["state"] not in {"verified", "paired"}
            or not compare_digest(row["central_browser_hash"], digest(browser))
        ):
            raise ProviderDenied()
        managed = _row(
            connection,
            "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id",
            row["managed_session_id"],
        )
        now = self.attempts.clock()
        if (
            managed["revoked_at"] is not None
            or managed["method"] != "email_link"
            or managed["purpose"] != "operator"
            or managed["operator_id"] != row["operator_id"]
            or not row["created_at"]
            <= now
            < min(
                row["expires_at"],
                managed["provider_valid_until"],
                managed["revocation_valid_until"],
                managed["remembered_until"],
            )
            or not compare_digest(managed["cookie_hash"], digest(cookie))
        ):
            raise ProviderDenied()
        return row, managed, now

    @staticmethod
    def _result(continuation_id):
        return {
            "version": 1,
            "kind": "pair_email_continuation",
            "result_id": continuation_id,
            "source_receipt_ref": None,
        }

    def _write(self, connection, paired, replacement, assertion_hash, now):
        fields = replacement.model_dump(exclude={"contract_version"})
        columns = ", ".join(fields)
        values = ", ".join(f":{name}" for name in fields)
        connection.execute(
            text(f"INSERT INTO main.login_attempts ({columns}) VALUES ({values})"), fields
        )
        changed = connection.execute(
            text("""
            UPDATE main.email_continuations SET state='paired', revision=revision+1,
                replacement_attempt_id=:replacement, source_attempt_id=:source, source_binding_hash=:hash
            WHERE continuation_id=:id AND state='verified' AND revision=:revision
        """),
            {
                "replacement": replacement.attempt_id,
                "source": replacement.source_attempt_id,
                "hash": assertion_hash,
                "id": paired.continuation_id,
                "revision": paired.revision - 1,
            },
        )
        if changed.rowcount != 1:
            raise ProviderDenied()
        operation_id = str(uuid4())
        connection.execute(
            text("""
            INSERT INTO main.identity_commands (
                operation_id, kind, idempotency_key, request_hash, operator_id, managed_session_id,
                attempt_id, access_epoch, state, result_json, created_at, updated_at, revision
            ) VALUES (:id,'pair_email_continuation',:key,:hash,:operator,:managed,:attempt,:epoch,
                      'succeeded',:result,:now,:now,1)
        """),
            {
                "id": operation_id,
                "key": paired.continuation_id,
                "hash": assertion_hash,
                "operator": paired.operator_id,
                "managed": paired.managed_session_id,
                "attempt": replacement.attempt_id,
                "epoch": paired.access_epoch,
                "result": json.dumps(self._result(paired.continuation_id)),
                "now": now,
            },
        )

        connection.execute(
            text("""
                INSERT INTO main.admin_audit
                    (audit_id, actor_ref, action, operator_id, recorded_at, safe_facts_json)
                VALUES (:id, 'central-identity', 'pair_email_continuation', :operator, :now, :facts)
            """),
            {
                "id": str(uuid4()),
                "operator": paired.operator_id,
                "now": now,
                "facts": json.dumps({"identity_operation_id": operation_id}),
            },
        )
