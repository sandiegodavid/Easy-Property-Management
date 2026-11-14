from pathlib import Path
from unittest.mock import Mock

from pydantic import SecretStr
import pytest
from sqlalchemy import text

from app.modules.hosted_access.application.identity_setup import MINUTE
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.admin_principals import change_admin_principal
from app.modules.hosted_access.infrastructure.admin_sessions import AdminSessions
from app.modules.hosted_access.infrastructure.provider_status import RevocationCache, UserStatus
from app.modules.hosted_access.tests.test_firebase_provider import NOW
from app.platform.hosted_schema import initialize_store, validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

pytest_plugins = ("app.modules.hosted_access.tests.test_firebase_provider",)
APPLICATION = Path(__file__).resolve().parents[6]


@pytest.fixture
def composition(tmp_path, provider):
    path = tmp_path / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, path, application_directory=APPLICATION)
    engine = create_sqlite_engine(path)
    verifier, sign, _, _ = provider
    token = SecretStr(
        sign(
            {
                "firebase": {
                    "sign_in_provider": "google.com",
                    "sign_in_second_factor": "totp",
                }
            }
        )
    )
    proof = verifier.google(token.get_secret_value(), admin=True)
    tick = [NOW * 1000]
    status = Mock(return_value=UserStatus(proof.subject, False, 0))
    managed = Mock(verifier=verifier)
    managed.setup.realm = verifier.realm
    managed.create_session_cookie.return_value = (SecretStr("synthetic-cookie"), proof)
    managed.status_cache = RevocationCache(status, clock=lambda: tick[0] / 1000)

    def change(action, revision=None):
        with immediate_transaction(engine) as connection:
            change_admin_principal(
                connection,
                realm=verifier.realm,
                subject=proof.subject,
                action=action,
                now=tick[0],
                expected_revision=revision,
            )

    change("bootstrap")
    yield AdminSessions(engine, managed, clock=lambda: tick[0]), token, tick, status, change
    engine.dispose()


def test_persists_hashes_rejects_duplicate_provider_cookie_and_revokes_with_csrf(composition):
    service, token, _, _, _ = composition
    credentials = service.sign_in(token)
    session = service.authenticate(credentials.session)
    assert session.expires_at == credentials.expires_at
    with pytest.raises(ProviderDenied):
        service.sign_in(token)
    with pytest.raises(ProviderDenied):
        service.logout(credentials.session, "x" * 43)
    with service.engine.connect() as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
        assert connection.scalar(text("SELECT count(*) FROM main.admin_sessions")) == 1
    service.logout(credentials.session, credentials.csrf)
    with pytest.raises(ProviderDenied):
        service.authenticate(credentials.session)
    with service.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM main.managed_identity_sessions WHERE revoked_at IS NOT NULL"
                )
            )
            == 1
        )


def test_refresh_fails_closed_and_detects_disabled_account(composition):
    service, token, tick, status, _ = composition
    credentials = service.sign_in(token)
    original = service.authenticate(credentials.session)
    tick[0] += 5 * MINUTE
    status.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        service.authenticate(credentials.session)
    status.side_effect = None
    refreshed = service.authenticate(credentials.session)
    assert refreshed.revocation_valid_until > original.revocation_valid_until
    tick[0] += 5 * MINUTE
    status.return_value = UserStatus("uid", True, 0)
    with pytest.raises(ProviderDenied):
        service.authenticate(credentials.session)


def test_principal_generation_change_during_provider_exchange_denies_issuance(composition):
    service, token, _, _, change = composition
    result = service.provider.create_session_cookie.return_value

    def exchange(*args, **kwargs):
        change("suspend", 1)
        change("restore", 2)
        return result

    service.provider.create_session_cookie.side_effect = exchange
    with pytest.raises(ProviderDenied):
        service.sign_in(token)
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM main.managed_identity_sessions")) == 0
