"""Admin session effects in the owning store. Provider calls stay outside write locks."""

from dataclasses import dataclass, field
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.admin_admission import (
    AdminAdmission,
    AdminPrincipal,
    require_admin_session,
)
from app.modules.hosted_access.application.identity_setup import MINUTE
from app.modules.hosted_access.application.identity_states import (
    AdminSessionState,
    ManagedIdentitySessionState,
)
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    VerifiedProviderIdentity,
)
from app.modules.hosted_access.infrastructure.admin_principals import SQLiteAdminPrincipalReader
from app.modules.hosted_access.infrastructure.firebase_rest import FirebaseRest
from app.platform.sqlite_engine import immediate_transaction


def _digest(secret: str) -> str:
    return sha256(secret.encode()).hexdigest()


@dataclass(frozen=True)
class AdminCredentials:
    session: str = field(repr=False)
    csrf: str = field(repr=False)
    expires_at: int


class AdminSessions:
    def __init__(self, engine: Engine, provider: FirebaseRest, *, clock):
        self.engine = engine
        self.provider = provider
        self.clock = clock
        self.admission = AdminAdmission(provider.setup.realm, SQLiteAdminPrincipalReader(engine))

    def sign_in(self, token: SecretStr, *, attempt_id=None, browser=None) -> AdminCredentials:
        primary = self.provider.verifier.google(token.get_secret_value(), admin=True)
        principal, _ = self.admission.session_deadline(primary, now=self.clock())
        if attempt_id is not None:
            self._reserve_attempt(attempt_id, browser, primary.authenticated_at)
        self.provider.lookup_status(primary)
        provider_cookie, proof = self.provider.create_session_cookie(
            token, primary, remembered=False
        )
        observation = self.provider.status_cache.observe(proof)
        session = token_urlsafe(32)
        csrf = self.csrf_token(session)
        try:
            with immediate_transaction(self.engine) as connection:
                now = self.clock()
                current = self._principal(connection, principal.principal_id)
                if current != principal or not current.enabled:
                    raise ProviderDenied()
                deadline = min(proof.expires_at, primary.authenticated_at + 480 * MINUTE)
                if not now < min(
                    deadline, observation.valid_until, primary.authenticated_at + 15 * MINUTE
                ):
                    raise ProviderDenied()
                managed = ManagedIdentitySessionState(
                    managed_session_id=str(uuid4()),
                    cookie_hash=_digest(provider_cookie.get_secret_value()),
                    purpose="admin",
                    operator_id=None,
                    issuer=proof.realm,
                    subject=proof.subject,
                    email_key=proof.email_key,
                    method="google_totp",
                    authenticated_at=proof.authenticated_at,
                    mfa_verified_at=proof.mfa_verified_at,
                    provider_valid_until=proof.expires_at,
                    remembered_until=deadline,
                    revocation_checked_at=max(proof.issued_at, observation.checked_at),
                    revocation_valid_until=observation.valid_until,
                    issued_at=proof.issued_at,
                    revoked_at=None,
                    revision=1,
                )
                admin = AdminSessionState(
                    session_hash=_digest(session),
                    principal_id=principal.principal_id,
                    csrf_hash=_digest(csrf),
                    generation=principal.session_generation,
                    authenticated_at=managed.authenticated_at,
                    mfa_verified_at=managed.mfa_verified_at,
                    expires_at=deadline,
                    last_seen_at=now,
                    revoked_at=None,
                    managed_session_id=managed.managed_session_id,
                    managed_valid_until=managed.provider_valid_until,
                    revocation_valid_until=managed.revocation_valid_until,
                )
                if attempt_id is not None:
                    changed = connection.execute(
                        text(
                            "UPDATE main.login_attempts SET state='completed', revision=revision+1 "
                            "WHERE attempt_id=:id AND state='verified' AND expires_at>:now"
                        ),
                        {"id": attempt_id, "now": now},
                    )
                    if changed.rowcount != 1:
                        raise ProviderDenied()
                connection.execute(
                    text("""
                    INSERT INTO main.managed_identity_sessions VALUES (
                        :managed_session_id, :cookie_hash, :purpose, :operator_id, :issuer,
                        :subject, :email_key, :method, :authenticated_at, :mfa_verified_at,
                        :provider_valid_until, :remembered_until, :revocation_checked_at,
                        :revocation_valid_until, :issued_at, :revoked_at, :revision
                    )
                    """),
                    managed.model_dump(),
                )
                connection.execute(
                    text("""
                    INSERT INTO main.admin_sessions VALUES (
                        :session_hash, :principal_id, :csrf_hash, :generation, :authenticated_at,
                        :mfa_verified_at, :expires_at, :last_seen_at, :revoked_at,
                        :managed_session_id, :managed_valid_until, :revocation_valid_until
                    )
                    """),
                    admin.model_dump(),
                )
        except IntegrityError:
            raise ProviderDenied() from None
        return AdminCredentials(session, csrf, deadline)

    def begin(self):
        attempt_id, browser = str(uuid4()), token_urlsafe(32)
        now = self.clock()
        with immediate_transaction(self.engine) as connection:
            count = connection.scalar(
                text(
                    "SELECT count(*) FROM main.login_attempts WHERE purpose='admin_login' "
                    "AND state IN ('pending','verified') AND expires_at>:now"
                ),
                {"now": now},
            )
            if count >= 128:
                raise ProviderDenied()
            connection.execute(
                text("""
                INSERT INTO main.login_attempts (
                    attempt_id, purpose, central_browser_hash, method, target_origin,
                    return_path, state, created_at, expires_at, revision
                ) VALUES (:id, 'admin_login', :browser, 'google_totp', :origin,
                          '/', 'pending', :now, :expires, 1)
                """),
                {
                    "id": attempt_id,
                    "browser": _digest(browser),
                    "origin": self.provider.setup.origins.admin,
                    "now": now,
                    "expires": now + 15 * MINUTE,
                },
            )
        return attempt_id, browser

    @staticmethod
    def csrf_token(secret):
        return (
            urlsafe_b64encode(sha256((secret + ":admin-csrf").encode()).digest())
            .decode()
            .rstrip("=")
        )

    def enrollment_allowed(self, token, attempt_id, browser):
        proof = self.provider.verifier.google(token.get_secret_value())
        self.admission.require_principal(proof, now=self.clock())
        self._reserve_attempt(attempt_id, browser, proof.authenticated_at, consume=False)

    def _reserve_attempt(self, attempt_id, browser, authenticated_at, *, consume=True):
        if not isinstance(browser, str) or len(browser) != 43:
            raise ProviderDenied()
        with immediate_transaction(self.engine) as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM main.login_attempts WHERE attempt_id=:id"),
                    {"id": attempt_id},
                )
                .mappings()
                .one_or_none()
            )
            now = self.clock()
            if (
                row is None
                or row["purpose"] != "admin_login"
                or row["state"] != "pending"
                or row["target_origin"] != self.provider.setup.origins.admin
                or not row["created_at"] <= now < row["expires_at"]
                or authenticated_at + 999 < row["created_at"]
                or not compare_digest(row["central_browser_hash"], _digest(browser))
            ):
                raise ProviderDenied()
            if consume:
                connection.execute(
                    text(
                        "UPDATE main.login_attempts SET state='verified', revision=revision+1 "
                        "WHERE attempt_id=:id"
                    ),
                    {"id": attempt_id},
                )

    @staticmethod
    def _principal(connection, principal_id):
        row = connection.execute(
            text(
                "SELECT enabled, session_generation FROM main.admin_principals WHERE principal_id=:id"
            ),
            {"id": principal_id},
        ).one_or_none()
        if row is None:
            raise ProviderDenied()
        return AdminPrincipal(principal_id, row.enabled == 1, row.session_generation)

    @staticmethod
    def _load(connection, secret):
        if not isinstance(secret, str) or len(secret) != 43:
            raise ProviderDenied()
        value = (
            connection.execute(
                text("SELECT * FROM main.admin_sessions WHERE session_hash=:hash"),
                {"hash": _digest(secret)},
            )
            .mappings()
            .one_or_none()
        )
        if value is None:
            raise ProviderDenied()
        return AdminSessionState.model_validate(dict(value))

    def authenticate(self, secret: str, *, sensitive: bool = False) -> AdminSessionState:
        with self.engine.connect() as connection:
            session = self._load(connection, secret)
            principal = self._principal(connection, session.principal_id)
            now = self.clock()
            if now < session.revocation_valid_until:
                require_admin_session(session, principal, now=now, sensitive=sensitive)
                return session
            if (
                not principal.enabled
                or principal.session_generation != session.generation
                or session.revoked_at is not None
                or now >= session.expires_at
                or (sensitive and now >= session.mfa_verified_at + 15 * MINUTE)
            ):
                raise ProviderDenied()
            value = (
                connection.execute(
                    text(
                        "SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                    ),
                    {"id": session.managed_session_id},
                )
                .mappings()
                .one()
            )
        managed = ManagedIdentitySessionState.model_validate(dict(value))
        if managed.revoked_at is not None or managed.issuer != self.admission.realm.alias:
            raise ProviderDenied()
        proof = VerifiedProviderIdentity(
            realm=managed.issuer,
            subject=managed.subject,
            email=managed.email_key.removeprefix(managed.issuer + ":"),
            email_key=managed.email_key,
            method=managed.method,
            authenticated_at=managed.authenticated_at,
            issued_at=managed.issued_at,
            expires_at=managed.provider_valid_until,
            mfa_verified_at=managed.mfa_verified_at,
        )
        observation = self.provider.status_cache.observe(proof)
        with immediate_transaction(self.engine) as connection:
            current = self._load(connection, secret)
            principal = self._principal(connection, current.principal_id)
            until = min(observation.valid_until, current.managed_valid_until)
            refreshed = current.model_copy(update={"revocation_valid_until": until})
            require_admin_session(refreshed, principal, now=self.clock(), sensitive=sensitive)
            changed = connection.execute(
                text("""
                    UPDATE main.managed_identity_sessions
                    SET revocation_checked_at=:checked, revocation_valid_until=:until, revision=revision+1
                    WHERE managed_session_id=:id AND revoked_at IS NULL
                      AND revocation_checked_at<=:checked
                    """),
                {
                    "checked": observation.checked_at,
                    "until": until,
                    "id": managed.managed_session_id,
                },
            )
            if changed.rowcount != 1:
                raise ProviderDenied()
            connection.execute(
                text(
                    "UPDATE main.admin_sessions SET revocation_valid_until=:until WHERE session_hash=:hash"
                ),
                {"until": until, "hash": current.session_hash},
            )
            return refreshed

    def logout(self, secret: str, csrf: str) -> None:
        with immediate_transaction(self.engine) as connection:
            session = self._load(connection, secret)
            if (
                not isinstance(csrf, str)
                or len(csrf) != 43
                or not compare_digest(session.csrf_hash, _digest(csrf))
            ):
                raise ProviderDenied()
            now = self.clock()
            if now < session.last_seen_at:
                raise ProviderDenied()
            connection.execute(
                text(
                    "UPDATE main.admin_sessions SET revoked_at=:now WHERE session_hash=:hash AND revoked_at IS NULL"
                ),
                {"now": now, "hash": session.session_hash},
            )
            connection.execute(
                text(
                    "UPDATE main.managed_identity_sessions SET revoked_at=:now, revision=revision+1 "
                    "WHERE managed_session_id=:id AND revoked_at IS NULL"
                ),
                {"now": now, "id": session.managed_session_id},
            )
