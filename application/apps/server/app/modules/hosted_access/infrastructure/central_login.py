"""Central provider orchestration with durable code reservation and safe result inspection."""

from uuid import uuid4
from secrets import token_urlsafe
from dataclasses import dataclass, field
from pydantic import SecretStr

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.central_login import UnavailableClaimReadiness
from app.modules.hosted_access.application.identity_setup import DAY
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
    email_key,
)
from app.modules.hosted_access.infrastructure.central_attempts import CentralAttempts, digest
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.sqlite_engine import immediate_transaction


@dataclass(frozen=True)
class CentralCompletion:
    result: dict
    cookie: SecretStr = field(repr=False)


class CentralLogin:
    def __init__(
        self,
        attempts: CentralAttempts,
        provider,
        *,
        deployment_id,
        readiness=None,
        invitations=None,
    ):
        self.attempts, self.provider = attempts, provider
        self.engine, self.clock = attempts.engine, attempts.clock
        self.deployment_id = deployment_id
        self.readiness = readiness or UnavailableClaimReadiness()
        self.invitations = invitations

    def send_email(self, attempt_id, browser, *, network):
        with self.engine.connect() as connection:
            attempt = dict(self.attempts.attempt(connection, attempt_id, browser))
        context = self.attempts.current_context(attempt)
        with immediate_transaction(self.engine) as connection:
            self.attempts.assignment(connection, context)
            row = self.attempts.attempt(connection, attempt_id, browser)
            if row["state"] != "pending" or row["method"] != "email_link":
                raise ProviderDenied()
            now = self.clock()
            if row["last_delivery_at"] is not None and now - row["last_delivery_at"] < 60000:
                raise ProviderDenied()
            ordinal = row["delivery_attempts"] + 1
            connection.execute(
                text(
                    "UPDATE main.login_attempts SET delivery_attempts=:n, last_delivery_at=:now, "
                    "last_delivery_code='unknown', revision=revision+1 WHERE attempt_id=:id"
                ),
                {"n": ordinal, "now": now, "id": attempt_id},
            )
        email = attempt["email_key"].removeprefix(self.attempts.setup.realm.alias + ":")
        operation = OperationReference.model_validate(
            {
                "deployment_id": self.deployment_id,
                "scope": {"kind": "deployment"},
                "kind": "send_email",
                "operation_id": str(uuid4()),
                "idempotency_key": attempt_id + ":" + str(ordinal),
                "request_hash": digest(
                    attempt_id + ":" + attempt["email_key"] + ":" + str(ordinal)
                ),
            }
        )
        result = "unknown"
        try:
            self.provider.send_email_link(
                email, network=network, operation=operation, attempt_id=attempt_id
            )
            result = "sent"
        except ProviderDenied:
            result = "rejected"
            raise
        finally:
            with immediate_transaction(self.engine) as connection:
                connection.execute(
                    text(
                        "UPDATE main.login_attempts SET last_delivery_code=:code, revision=revision+1 "
                        "WHERE attempt_id=:id AND delivery_attempts=:n"
                    ),
                    {"code": result, "id": attempt_id, "n": ordinal},
                )
        return {"state": "sent"}

    def complete_google(self, attempt_id, browser, token, *, remembered=False):
        with self.engine.connect() as connection:
            attempt = dict(self.attempts.attempt(connection, attempt_id, browser))
        context = self.attempts.current_context(attempt)
        self.attempts.reserve_google(attempt_id, browser)
        cookie, proof = self.provider.complete_google(token, remembered=remembered)
        return self._persist(attempt, context, cookie, proof, remembered=remembered)

    def complete_email(self, attempt_id, browser, email, code, *, remembered=False):
        with self.engine.connect() as connection:
            attempt = dict(self.attempts.attempt(connection, attempt_id))
        if email_key(self.attempts.setup.realm.alias, email) != attempt["email_key"]:
            raise ProviderDenied()
        context = self.attempts.current_context(attempt)
        continuation, reserved = self.attempts.reserve_email(attempt_id, browser, code)
        if not reserved:
            return {
                "state": continuation["state"],
                "continuationId": continuation["continuation_id"],
            }
        try:
            cookie, proof = self.provider.complete_email_link(email, code, remembered=remembered)
            return self._persist(
                attempt,
                context,
                cookie,
                proof,
                remembered=remembered,
                continuation_id=continuation["continuation_id"],
            )
        except ProviderUnavailable, ProviderDenied, IntegrityError:
            self.attempts.mark_email_unknown(continuation["continuation_id"])
            raise

    def _persist(self, attempt, context, cookie, proof, *, remembered, continuation_id=None):
        self.attempts.source.current(context)
        if (
            proof.realm != self.attempts.setup.realm.alias
            or proof.method != attempt["method"]
            or (attempt["email_key"] is not None and proof.email_key != attempt["email_key"])
            or proof.authenticated_at + 999 < attempt["created_at"]
        ):
            raise ProviderDenied()
        observation = self.provider.status_cache.observe(proof)
        now = self.clock()
        session_id = str(uuid4())
        central_cookie = token_urlsafe(32)
        until = proof.authenticated_at + (30 * DAY if remembered else 8 * 3600000)
        lineage = context.renewal
        if lineage is not None:
            if (
                attempt["purpose"] != "renewal"
                or lineage.managed_session_id != attempt["parent_managed_session_id"]
                or proof.authenticated_at < attempt["created_at"]
            ):
                raise ProviderDenied()
            until = lineage.remembered_until
        with immediate_transaction(self.engine) as connection:
            assignment = self.attempts.assignment(connection, context)
            expected_subject = assignment["subject"]
            if expected_subject is not None and expected_subject != proof.subject:
                raise ProviderDenied()
            row = self.attempts.attempt(connection, attempt["attempt_id"])
            if row["state"] != ("pending" if continuation_id else "verified"):
                raise ProviderDenied()
            if not now < min(until, observation.valid_until):
                raise ProviderDenied()
            if lineage is not None:
                prior = (
                    connection.execute(
                        text(
                            "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                        ),
                        {"id": lineage.managed_session_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior is None or (
                    prior["revoked_at"] is not None
                    or prior["operator_id"] != context.operator_id
                    or prior["purpose"] != "operator"
                    or prior["issuer"] != proof.realm
                    or prior["subject"] != proof.subject
                    or prior["remembered_until"] != until
                    or proof.authenticated_at <= prior["authenticated_at"]
                ):
                    raise ProviderDenied()
            if continuation_id:
                continuation = (
                    connection.execute(
                        text("SELECT * FROM main.email_continuations WHERE continuation_id=:id"),
                        {"id": continuation_id},
                    )
                    .mappings()
                    .one()
                )
                if continuation["state"] != "verifying" or now >= continuation["expires_at"]:
                    raise ProviderDenied()
            connection.execute(
                text("""
                INSERT INTO main.managed_identity_sessions (
                    managed_session_id, cookie_hash, purpose, operator_id, issuer, subject,
                    email_key, method, authenticated_at, mfa_verified_at, provider_valid_until,
                    remembered_until, revocation_checked_at, revocation_valid_until,
                    issued_at, revoked_at, revision
                ) VALUES (:id, :cookie, 'operator', :operator, :issuer, :subject, :email,
                          :method, :auth, NULL, :provider_until, :remembered_until,
                          :checked, :valid_until, :issued, NULL, 1)
            """),
                {
                    "id": session_id,
                    "cookie": digest(central_cookie),
                    "operator": context.operator_id,
                    "issuer": proof.realm,
                    "subject": proof.subject,
                    "email": proof.email_key,
                    "method": proof.method,
                    "auth": proof.authenticated_at,
                    "provider_until": proof.expires_at,
                    "remembered_until": until,
                    "checked": max(proof.issued_at, observation.checked_at),
                    "valid_until": observation.valid_until,
                    "issued": proof.issued_at,
                },
            )
            if continuation_id:
                connection.execute(
                    text(
                        "UPDATE main.email_continuations SET managed_session_id=:session, "
                        "state='verified', expires_at=min(expires_at,:until), revision=revision+1 "
                        "WHERE continuation_id=:id"
                    ),
                    {"session": session_id, "until": proof.expires_at, "id": continuation_id},
                )
            connection.execute(
                text(
                    "UPDATE main.login_attempts SET state=:state, "
                    "completed_managed_session_id=:completed, revision=revision+1 WHERE attempt_id=:id"
                ),
                {
                    "state": "superseded" if continuation_id else "completed",
                    "completed": None if continuation_id else session_id,
                    "id": attempt["attempt_id"],
                },
            )
        claim_result = None
        if self.invitations is not None and context.invitation_id is not None:
            claim_result = self.invitations.claim_from_source(
                self.attempts,
                context,
                attempt["attempt_id"],
                session_id,
                central_cookie=SecretStr(central_cookie),
            )
        return CentralCompletion(
            {
                "state": "workspace_not_ready",
                "managedSessionId": session_id,
                **({"claim": claim_result} if claim_result is not None else {}),
                **(
                    {
                        "continuationId": continuation_id,
                        "continueUrl": context.target_origin
                        + "/auth/start?continuation="
                        + continuation_id,
                    }
                    if continuation_id
                    else {}
                ),
            },
            SecretStr(central_cookie),
        )
