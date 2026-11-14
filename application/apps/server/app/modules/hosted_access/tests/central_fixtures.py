"""Durable central flow invariants with real SQLite and synthetic provider/source owners."""

from pathlib import Path
from unittest.mock import Mock

from pydantic import SecretStr
import pytest
from sqlalchemy import text

from app.modules.hosted_access.application.central_login import SourceLoginContext
from app.modules.hosted_access.infrastructure.central_attempts import CentralAttempts
from app.modules.hosted_access.infrastructure.central_login import CentralLogin
from app.modules.hosted_access.infrastructure.provider_status import RevocationCache, UserStatus
from app.modules.hosted_access.tests.test_identity_contracts import setup
from app.modules.hosted_access.tests.test_firebase_provider import NOW
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
from app.platform.tests.test_hosted_schema import seed_admin, FIRST

pytest_plugins = ("app.modules.hosted_access.tests.test_firebase_provider",)
APPLICATION = Path(__file__).resolve().parents[6]


@pytest.fixture
def central(tmp_path, provider):
    path = tmp_path / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, path, application_directory=APPLICATION)
    engine = create_sqlite_engine(path)
    selected = setup()
    tick = [(NOW - 30) * 1000]
    with immediate_transaction(engine) as connection:
        seed_admin(connection)
        connection.execute(
            text(
                "UPDATE main.operators SET issuer=:issuer, email_key=:email, subject=NULL, "
                "setup_state='ready_for_claim' WHERE operator_id=:id"
            ),
            {
                "issuer": selected.realm.alias,
                "email": selected.realm.alias + ":A.B+tag@example.invalid",
                "id": FIRST,
            },
        )
    context = SourceLoginContext(
        operator_id=FIRST,
        assignment_revision=1,
        access_epoch=1,
        target_origin="https://synthetic-operator.example.invalid",
        source_attempt_id="00000000-0000-4000-8000-000000000099",
        source_browser_hash="b" * 64,
        return_path="/home",
        expires_at=(NOW + 800) * 1000,
    )
    source = Mock()
    source.resolve_start.return_value = source.inspect_start.return_value = context
    attempts = CentralAttempts(engine, selected, source, clock=lambda: tick[0])
    verifier, sign, _, _ = provider
    google = verifier.google(sign())
    email = verifier.email_completion(
        sign({"firebase": {"sign_in_provider": "password"}}),
        expected_email="A.B+tag@example.invalid",
        expected_subject="uid",
    )
    client = Mock()
    client.complete_google.return_value = SecretStr("provider-cookie"), google
    client.complete_email_link.return_value = SecretStr("provider-cookie"), email
    client.status_cache = RevocationCache(
        lambda identity: UserStatus(identity.subject, False, 0),
        clock=lambda: tick[0] / 1000,
    )
    service = CentralLogin(attempts, client, deployment_id=FIRST)
    yield service, tick, path
    engine.dispose()


def start(service, tick, method="google"):
    tick[0] = (NOW - 30) * 1000
    result = service.attempts.start(
        SecretStr("signed-source-assertion"),
        method=method,
        email="A.B+tag@example.invalid" if method == "email_link" else None,
    )
    tick[0] = NOW * 1000
    return result


@pytest.fixture
def central_start():
    return start
