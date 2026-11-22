"""Own the destination challenge, pairing assertion and atomic session issuance."""

from dataclasses import dataclass, field
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import text

from app.modules.hosted_access.application.central_login import SourceLoginContext
from app.modules.hosted_access.application.identity_evidence import (
    HandoffEvidence,
    SessionReceipt,
    SourceBindingAssertion,
)
from app.modules.hosted_access.application.identity_setup import DAY, MINUTE
from app.modules.hosted_access.application.identity_states import (
    LIVE_SESSION_CAP,
    SourceLoginAttemptState,
)
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.modules.hosted_access.infrastructure.handoff_signing import verify_evidence
from app.modules.hosted_access.infrastructure.source_sessions import (
    SessionLimitReached,
    device_rows,
    renewal_lineage,
    session_row,
)
from app.platform.hosted_contracts.semantic import semantic_hash


@dataclass(frozen=True)
class DestinationStart:
    attempt: SourceLoginAttemptState
    challenge: SecretStr = field(repr=False)
    assertion: SecretStr | None = field(default=None, repr=False)
    origin_id: str = ""


@dataclass(frozen=True)
class DestinationCompletion:
    receipt: SessionReceipt
    return_path: str
    session: SecretStr | None = field(repr=False)
    csrf: SecretStr | None = field(repr=False)
    remembered: bool = False
    remembered_until: int | None = None


def _attempt(connection, identifier):
    row = (
        connection.execute(
            text("SELECT * FROM main.source_login_attempts WHERE attempt_id=:id"),
            {"id": identifier},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProviderDenied()
    return SourceLoginAttemptState.model_validate(
        dict(row) | {"remembered": bool(row["remembered"])}
    )


class DestinationIdentity:
    def __init__(self, engine, *, mutation, binding, signer, central_key, clock):
        self.engine, self.mutation = engine, mutation
        self.binding, self.signer, self.central_key, self.clock = (
            binding,
            signer,
            central_key,
            clock,
        )

    def _current(self, connection, *, enabled=False):
        # The protected binding supplies origin and assignment revision; the
        # same source transaction owns effective access, identity and generation.
        row = (
            connection.execute(text("SELECT * FROM main.access_meta WHERE id=1"))
            .mappings()
            .one_or_none()
        )
        return self.check_current(row, enabled=enabled)

    def check_current(self, row, *, enabled=False):
        binding = self.binding()
        if row is None or (
            row["deployment_id"] != binding.deployment_id
            or row["operator_id"] != binding.scope.operator_id
            or row["workspace_id"] != binding.scope.workspace_id
            or row["binding_id"] != binding.binding_id
            or row["access_epoch"] != binding.access_epoch
            or row["resource_generation"] != binding.resource_generation
            or row["issuer"] != binding.issuer
            or row["subject"] not in {None, binding.subject}
            or row["maintenance_operation_id"] is not None
            or row["not_before"] > self.clock()
            or (
                enabled
                and (row["effective_access"] != "enabled" or row["subject"] != binding.subject)
            )
        ):
            raise ProviderDenied()
        return binding, row

    def begin(
        self,
        return_path,
        *,
        remembered=False,
        continuation_id=None,
        continuation_expires=None,
        expected_binding=None,
        renewal_cookie=None,
        expected_renewal=None,
    ):
        browser = token_urlsafe(32)
        now = self.clock()
        with self.mutation() as connection:
            binding, meta = self._current(connection, enabled=renewal_cookie is not None)
            predecessor = (
                session_row(connection, renewal_cookie, meta, now, lineage=True)
                if renewal_cookie is not None
                else None
            )
            renewal = renewal_lineage(predecessor) if predecessor is not None else None
            if expected_renewal is not None and renewal != expected_renewal:
                raise ProviderDenied()
            if expected_binding is not None and binding != expected_binding:
                raise ProviderDenied()
            connection.execute(
                text(
                    "DELETE FROM main.source_login_attempts "
                    "WHERE state='pending' AND expires_at<=:now"
                ),
                {"now": now},
            )
            privileged = renewal_cookie is not None or continuation_id is not None
            if privileged:
                pending = connection.scalar(
                    text(
                        "SELECT count(*) FROM main.source_login_attempts "
                        "WHERE state IN ('pending','redeeming') "
                        "AND (continuation_id IS NOT NULL OR renewal_session_id IS NOT NULL) "
                        "AND expires_at>:now"
                    ),
                    {"now": now},
                )
                if pending >= LIVE_SESSION_CAP:
                    raise ProviderDenied()
            else:
                pending = connection.scalar(
                    text(
                        "SELECT count(*) FROM main.source_login_attempts "
                        "WHERE state='pending' AND continuation_id IS NULL "
                        "AND renewal_session_id IS NULL AND expires_at>:now"
                    ),
                    {"now": now},
                )
                if pending >= LIVE_SESSION_CAP:
                    connection.execute(
                        text(
                            "DELETE FROM main.source_login_attempts WHERE attempt_id IN ("
                            "SELECT attempt_id FROM main.source_login_attempts "
                            "WHERE state='pending' AND continuation_id IS NULL "
                            "AND renewal_session_id IS NULL "
                            "ORDER BY created_at ASC, attempt_id ASC LIMIT :excess)"
                        ),
                        {"excess": pending - LIVE_SESSION_CAP + 1},
                    )
            attempt_id = str(uuid4())
            expires = min(now + 15 * MINUTE, continuation_expires or now + 15 * MINUTE)
            if expires <= now or (continuation_id is None) != (continuation_expires is None):
                raise ProviderDenied()
            assertion = None
            assertion_expiry = None
            if continuation_id is not None:
                assertion_expiry = min(expires, now + 5 * MINUTE)
                assertion = self.signer.sign(
                    SourceBindingAssertion(
                        key_id=self.signer.key_id,
                        operation_id=attempt_id,
                        request_hash=digest(continuation_id + ":" + attempt_id),
                        nonce_hash=digest(token_urlsafe(32)),
                        binding=binding,
                        continuation_id=continuation_id,
                        source_attempt_id=attempt_id,
                        source_browser_hash=digest(browser),
                        renewal=renewal,
                        issued_at=now,
                        expires_at=assertion_expiry,
                    )
                )
            attempt = SourceLoginAttemptState(
                attempt_id=attempt_id,
                browser_challenge_hash=digest(browser),
                access_epoch=binding.access_epoch,
                resource_generation=binding.resource_generation,
                return_path=return_path,
                remembered=renewal.remembered if renewal is not None else remembered,
                renewal_session_id=predecessor["session_id"] if predecessor is not None else None,
                state="pending",
                handoff_id=None,
                continuation_id=continuation_id,
                binding_assertion_hash=digest(assertion.get_secret_value()) if assertion else None,
                binding_expires_at=assertion_expiry,
                created_at=now,
                expires_at=expires,
                revision=1,
            )
            fields = attempt.model_dump(exclude={"contract_version"})
            columns = ", ".join(fields)
            parameters = ", ".join(f":{name}" for name in fields)
            connection.execute(
                text(f"INSERT INTO main.source_login_attempts ({columns}) VALUES ({parameters})"),
                fields,
            )
        return DestinationStart(
            attempt, SecretStr(browser), assertion, binding.registered_origin_id
        )

    def inspect(self, attempt_id):
        binding, attempt, _ = self.observe(attempt_id)
        return binding, attempt

    def observe(self, attempt_id):
        with self.engine.connect() as connection, connection.begin():
            binding, meta = self._current(connection)
            attempt = _attempt(connection, attempt_id)
            self._require_pending(binding, attempt)
            predecessor = None
            if attempt.renewal_session_id is not None:
                self.check_current(meta, enabled=True)
                row = (
                    connection.execute(
                        text("SELECT * FROM main.access_sessions WHERE session_id=:id"),
                        {"id": attempt.renewal_session_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None or (
                    row["revoked_at"] is not None
                    or row["generation"] != meta["session_generation"]
                    or row["access_epoch"] != meta["access_epoch"]
                    or row["actor_subject"] != meta["subject"]
                    or self.clock() >= row["remembered_until"]
                ):
                    raise ProviderDenied()
                predecessor = renewal_lineage(row)
            return binding, attempt, predecessor

    def login_context(self, attempt_id):
        binding, attempt, renewal = self.observe(attempt_id)
        return SourceLoginContext(
            operator_id=binding.scope.operator_id,
            assignment_revision=binding.assignment_revision,
            access_epoch=binding.access_epoch,
            target_origin=binding.target_origin,
            source_attempt_id=attempt_id,
            source_browser_hash=attempt.browser_challenge_hash,
            return_path=attempt.return_path,
            expires_at=attempt.expires_at,
            renewal=renewal,
        )

    def status(self, attempt_id, browser):
        with self.engine.connect() as connection:
            binding, _ = self._current(connection)
            attempt = _attempt(connection, attempt_id)
            if (
                attempt.access_epoch != binding.access_epoch
                or attempt.resource_generation != binding.resource_generation
                or not compare_digest(attempt.browser_challenge_hash, digest(browser))
            ):
                raise ProviderDenied()
            return attempt.state if self.clock() < attempt.expires_at else "expired"

    def _require_pending(self, binding, attempt):
        if (
            attempt.state != "pending"
            or not attempt.created_at <= self.clock() < attempt.expires_at
            or attempt.access_epoch != binding.access_epoch
            or attempt.resource_generation != binding.resource_generation
        ):
            raise ProviderDenied()

    def check_browser(self, grant, browser, *, renewal_cookie=None):
        if not isinstance(browser, str) or len(browser) != 43:
            raise ProviderDenied()
        with self.engine.connect() as connection:
            binding, meta = self._current(connection, enabled=True)
            attempt = _attempt(connection, grant.source_attempt_id)
            self._require_pending(binding, attempt)
            self._require_handoff(grant, binding, attempt, browser)
            self._predecessor(connection, grant, attempt, meta, renewal_cookie)

    def redeem(
        self,
        token,
        browser,
        central,
        *,
        renewal_cookie=None,
        replace_device=None,
        device_label="Browser",
    ):
        """Reserve centrally, commit locally, acknowledge outside the source writer."""
        grant = verify_evidence(token, HandoffEvidence, self.central_key, now=self.clock())
        original = self.original(grant)
        if original is not None:
            # The private reconciliation channels use the same safe receipt;
            # a browser replay has no session or CSRF bearer to recover.
            if not isinstance(browser, str) or not compare_digest(
                grant.source_browser_hash, digest(browser)
            ):
                raise ProviderDenied()
            central.acknowledge(original)
            raise ProviderDenied()
        self.check_browser(grant, browser, renewal_cookie=renewal_cookie)
        central.reserve(token, grant)
        completion = self._issue(
            grant,
            browser,
            renewal_cookie=renewal_cookie,
            replace_device=replace_device,
            device_label=device_label,
        )
        central.acknowledge(completion.receipt)
        if completion.session is None:
            raise ProviderDenied()
        return completion

    def cap_devices(self, token, browser, *, renewal_cookie=None):
        grant = verify_evidence(token, HandoffEvidence, self.central_key, now=self.clock())
        with self.engine.connect() as connection, connection.begin():
            binding, meta = self._current(connection, enabled=True)
            attempt = _attempt(connection, grant.source_attempt_id)
            self._require_pending(binding, attempt)
            self._require_handoff(grant, binding, attempt, browser)
            self._predecessor(connection, grant, attempt, meta, renewal_cookie)
            if grant.managed.authenticated_at < max(meta["not_before"], self.clock() - 5 * MINUTE):
                raise ProviderDenied()
            return device_rows(connection, meta, self.clock())

    def original(self, grant):
        with self.engine.connect() as connection:
            return self._original(connection, grant)

    @staticmethod
    def _original(connection, grant):
        result = connection.scalar(
            text("SELECT result_json FROM main.access_receipts WHERE operation_id=:id"),
            {"id": grant.operation_id},
        )
        if result is None:
            return None
        receipt = SessionReceipt.model_validate_json(result)
        if (
            receipt.request_hash != semantic_hash(grant)
            or receipt.binding != grant.binding
            or receipt.handoff_id != grant.handoff_id
        ):
            raise ProviderDenied()
        return receipt

    def _require_handoff(self, grant, binding, attempt, browser):
        now = self.clock()
        if (
            grant.binding != binding
            or not grant.issued_at <= now < grant.expires_at
            or not compare_digest(attempt.browser_challenge_hash, grant.source_browser_hash)
            or not compare_digest(attempt.browser_challenge_hash, digest(browser))
            or (
                attempt.continuation_id is not None
                and (attempt.binding_expires_at is None or attempt.binding_expires_at <= now)
            )
            or (
                attempt.continuation_id is not None
                and attempt.remembered != self._remembered(grant)
            )
        ):
            raise ProviderDenied()

    def _predecessor(self, connection, grant, attempt, meta, cookie):
        if grant.renewal is None:
            if attempt.renewal_session_id is not None:
                raise ProviderDenied()
            return None
        row = session_row(connection, cookie, meta, self.clock(), lineage=True)
        if (
            attempt.renewal_session_id != row["session_id"]
            or grant.renewal != renewal_lineage(row)
            or grant.managed.authenticated_at <= row["issued_at"]
            or (
                attempt.continuation_id is None
                and grant.managed.authenticated_at < attempt.created_at
            )
        ):
            raise ProviderDenied()
        return row

    def _issue(
        self, grant, browser, *, renewal_cookie=None, replace_device=None, device_label="Browser"
    ):
        with self.mutation() as connection:
            binding, meta = self._current(connection, enabled=True)
            attempt = _attempt(connection, grant.source_attempt_id)
            original = self._original(connection, grant)
            if original is not None:
                return DestinationCompletion(original, attempt.return_path, None, None)
            self._require_pending(binding, attempt)
            self._require_handoff(grant, binding, attempt, browser)
            predecessor = self._predecessor(connection, grant, attempt, meta, renewal_cookie)
            now = self.clock()
            managed = grant.managed
            if managed.authenticated_at < meta["not_before"]:
                raise ProviderDenied()
            active = connection.scalar(
                text(
                    "SELECT count(*) FROM main.access_sessions WHERE generation=:generation "
                    "AND access_epoch=:epoch AND revoked_at IS NULL AND expires_at>:now"
                ),
                {
                    "generation": meta["session_generation"],
                    "epoch": binding.access_epoch,
                    "now": now,
                },
            )
            needs_slot = predecessor is None or predecessor["expires_at"] <= now
            replaced_managed = None
            if replace_device is not None:
                if (
                    not needs_slot
                    or active != LIVE_SESSION_CAP
                    or grant.managed.authenticated_at < now - 5 * MINUTE
                ):
                    raise ProviderDenied()
                replaced_managed = connection.execute(
                    text("""
                    UPDATE main.access_sessions SET revoked_at=:now
                    WHERE session_id=:id AND generation=:generation AND access_epoch=:epoch
                      AND actor_subject=:subject AND issued_at<=:now AND expires_at>:now AND revoked_at IS NULL
                    RETURNING managed_session_id
                """),
                    {
                        "now": now,
                        "id": replace_device,
                        "generation": meta["session_generation"],
                        "epoch": binding.access_epoch,
                        "subject": binding.subject,
                    },
                ).scalar_one_or_none()
                if replaced_managed is None:
                    raise ProviderDenied()
            elif active >= LIVE_SESSION_CAP and needs_slot:
                raise SessionLimitReached()
            if predecessor is not None:
                connection.execute(
                    text("""
                    UPDATE main.access_sessions SET revoked_at=:now WHERE session_id=:id
                """),
                    {"id": predecessor["session_id"], "now": now},
                )
            session = token_urlsafe(32)
            csrf = self.csrf_token(session)
            receipt = SessionReceipt(
                kind="refresh_session" if predecessor is not None else "issue_session",
                operation_id=grant.operation_id,
                request_hash=semantic_hash(grant),
                binding=binding,
                session_id=str(uuid4()),
                handoff_id=grant.handoff_id,
                source_revision=meta["revision"],
                session_generation=meta["session_generation"],
                recorded_at=now,
                expires_at=min(managed.provider_valid_until, managed.remembered_until),
                replaced_device_managed_id=replaced_managed,
                renewed_from_session_id=predecessor["session_id"]
                if predecessor is not None
                else None,
            )
            self._commit(
                connection,
                receipt,
                attempt,
                managed,
                session,
                csrf,
                remembered=self._remembered(grant),
                device_label=device_label,
            )
        return DestinationCompletion(
            receipt,
            attempt.return_path,
            SecretStr(session),
            SecretStr(csrf),
            self._remembered(grant),
            managed.remembered_until,
        )

    @staticmethod
    def _remembered(grant):
        if grant.renewal is not None:
            return grant.renewal.remembered
        return grant.managed.remembered_until == grant.managed.authenticated_at + 30 * DAY

    @staticmethod
    def csrf_token(session):
        return (
            urlsafe_b64encode(sha256((session + ":operator-csrf").encode()).digest())
            .rstrip(b"=")
            .decode("ascii")
        )

    def observe_receipt(self, reference):
        with self.engine.connect() as connection:
            result = connection.scalar(
                text(
                    "SELECT result_json FROM main.access_receipts WHERE operation_id=:id AND kind IN ('issue_session','refresh_session')"
                ),
                {"id": reference.operation_id},
            )
        receipt = SessionReceipt.model_validate_json(result) if result is not None else None
        if receipt is not None and (
            receipt.binding != reference.binding
            or receipt.request_hash != reference.request_hash
            or receipt.handoff_id != reference.handoff_id
        ):
            raise ProviderDenied()
        return receipt

    @staticmethod
    def _commit(connection, receipt, attempt, managed, session, csrf, *, remembered, device_label):
        connection.execute(
            text("""
            INSERT INTO main.access_sessions (
                session_hash, csrf_hash, actor_subject, handoff_id, generation, access_epoch,
                issued_at, expires_at, managed_valid_until, last_seen_at, session_id,
                managed_session_id, managed_observation_revision, revocation_valid_until,
                remembered_until, remembered, display_label, renewed_from_session_id
            ) VALUES (
                :session, :csrf, :subject, :handoff, :generation, :epoch, :now, :expires,
                :managed_until, :now, :session_id, :managed, :observation, :freshness,
                :remembered, :persist, :label, :predecessor
            )
        """),
            {
                "session": digest(session),
                "csrf": digest(csrf),
                "subject": receipt.binding.subject,
                "handoff": receipt.handoff_id,
                "generation": receipt.session_generation,
                "epoch": receipt.binding.access_epoch,
                "now": receipt.recorded_at,
                "expires": receipt.expires_at,
                "managed_until": managed.provider_valid_until,
                "session_id": receipt.session_id,
                "managed": managed.managed_session_id,
                "observation": managed.revision,
                "freshness": managed.valid_until,
                "remembered": managed.remembered_until,
                "persist": int(remembered),
                "label": device_label,
                "predecessor": receipt.renewed_from_session_id,
            },
        )
        connection.execute(
            text("""
            INSERT INTO main.access_receipts (
                operation_id, request_hash, kind, access_epoch, source_revision, result_json, recorded_at
            ) VALUES (:id, :hash, :kind, :epoch, :revision, :result, :now)
        """),
            {
                "id": receipt.operation_id,
                "hash": receipt.request_hash,
                "kind": receipt.kind,
                "epoch": receipt.binding.access_epoch,
                "revision": receipt.source_revision,
                "result": receipt.model_dump_json(),
                "now": receipt.recorded_at,
            },
        )
        connection.execute(
            text("""
            INSERT INTO main.access_audit (audit_id, operation_id, action, actor_ref, recorded_at, safe_facts_json)
            VALUES (:audit, :id, :kind, 'owning-source', :now, '{}')
        """),
            {
                "audit": str(uuid4()),
                "id": receipt.operation_id,
                "kind": receipt.kind,
                "now": receipt.recorded_at,
            },
        )
        connection.execute(
            text("""
            UPDATE main.source_login_attempts SET state='completed', handoff_id=:handoff,
                revision=revision+1 WHERE attempt_id=:id
        """),
            {"handoff": receipt.handoff_id, "id": attempt.attempt_id},
        )
