"""Exercise the browser return through the central HTTP boundary and owning database."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.modules.hosted_access.api.central_identity import build_central_identity_app
from app.modules.hosted_access.application.identity_evidence import SourceBindingAssertion
from app.modules.hosted_access.application.identity_states import SourceLoginAttemptState
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.infrastructure.central_attempts import digest
from app.modules.hosted_access.infrastructure.central_pairing import CentralPairing
from app.platform.hosted_schema import validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import immediate_transaction

pytest_plugins = ("app.modules.hosted_access.tests.central_fixtures",)
APPLICATION = Path(__file__).resolve().parents[6]


@pytest.fixture
def round_trip(central, central_start):
    service, tick, _ = central
    original, original_browser = central_start(service, tick, "email_link")
    browser = "x" * 43
    completion = service.complete_email(
        original, browser, "A.B+tag@example.invalid", SecretStr("action-code")
    )
    continuation = completion.result["continuationId"]
    context = service.attempts.source.resolve_start.return_value
    with service.engine.connect() as connection:
        workspace = connection.scalar(text("SELECT workspace_id FROM main.operators"))
    tick[0] += 1000
    signed = SecretStr("synthetic signed source binding")
    source = SourceLoginAttemptState(
        attempt_id=str(uuid4()),
        browser_challenge_hash="d" * 64,
        access_epoch=1,
        resource_generation=1,
        return_path="/home",
        remembered=False,
        state="pending",
        handoff_id=None,
        continuation_id=continuation,
        binding_assertion_hash=digest(signed.get_secret_value()),
        binding_expires_at=tick[0] + 60000,
        created_at=tick[0],
        expires_at=tick[0] + 120000,
        revision=1,
    )
    grant = SourceBindingAssertion(
        key_id="synthetic-source-key",
        binding={
            "deployment_id": service.deployment_id,
            "scope": {"operator_id": context.operator_id, "workspace_id": workspace},
            "binding_id": str(uuid4()),
            "resource_generation": 1,
            "access_epoch": 1,
            "assignment_revision": 1,
            "registered_origin_id": str(uuid4()),
            "target_origin": context.target_origin,
            "issuer": service.attempts.setup.realm.alias,
            "subject": "uid",
        },
        operation_id=str(uuid4()),
        request_hash="a" * 64,
        nonce_hash="b" * 64,
        issued_at=tick[0],
        expires_at=source.binding_expires_at,
        continuation_id=continuation,
        source_attempt_id=source.attempt_id,
        source_browser_hash=source.browser_challenge_hash,
    )
    owner = Mock()
    owner.verify_pairing.return_value = grant, source
    pairing = CentralPairing(service.attempts, owner, deployment_id=service.deployment_id)
    return (
        service,
        pairing,
        continuation,
        signed,
        {
            "origin": context.target_origin,
            "browser": browser,
            "cookie": completion.cookie.get_secret_value(),
        },
        original_browser,
        tick,
    )


def test_source_form_round_trip_returns_safe_page_and_persists_original_receipt(
    round_trip, tmp_path
):
    service, pairing, continuation, signed, binding, original_browser, _ = round_trip
    client = TestClient(
        build_central_identity_app(
            service,
            ui_directory=tmp_path,
            web_config={},
            network_source=lambda _: None,
            pairing=pairing,
        ),
        base_url=service.attempts.setup.origins.central,
    )
    body = {"continuationId": continuation, "assertion": signed.get_secret_value()}
    cookies = "__Host-epm-central=" + binding["cookie"] + "; __Host-epm-central-challenge="
    for origin, browser in (
        ("https://other.example.invalid", binding["browser"]),
        (binding["origin"], original_browser),
    ):
        response = client.post(
            "/auth/email/continue",
            data=body,
            headers={"Origin": origin, "Cookie": cookies + browser},
        )
        assert response.status_code == 401
    pairing.source.verify_pairing.assert_not_called()
    headers = {"Origin": binding["origin"], "Cookie": cookies + binding["browser"]}
    assert client.post("/auth/email/continue", json=body, headers=headers).status_code == 401
    for _ in range(2):
        response = client.post("/auth/email/continue", data=body, headers=headers)
        assert response.status_code == 200
        assert "Identity verified" in response.text
        assert signed.get_secret_value() not in response.text
        assert "set-cookie" not in response.headers
    with service.engine.connect() as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
        assert connection.scalar(text("SELECT count(*) FROM main.identity_commands")) == 1
        assert connection.scalar(text("SELECT state FROM main.email_continuations")) == "paired"


@pytest.mark.parametrize("changed", ["cookie", "assertion", "remembered", "epoch", "expired"])
def test_pairing_fails_closed_on_wrong_proof_or_stale_binding(round_trip, changed):
    service, pairing, continuation, signed, binding, _, tick = round_trip
    grant, source = pairing.source.verify_pairing.return_value
    if changed == "cookie":
        binding["cookie"] = "y" * 43
    elif changed == "assertion":
        grant = grant.model_copy(update={"continuation_id": str(uuid4())})
    elif changed == "remembered":
        source = source.model_copy(update={"remembered": True})
    elif changed == "epoch":
        with immediate_transaction(service.engine) as connection:
            connection.execute(text("UPDATE main.operators SET access_epoch=2"))
    elif changed == "expired":
        tick[0] = grant.expires_at
    pairing.source.verify_pairing.return_value = grant, source
    with pytest.raises(ProviderDenied):
        pairing.pair(continuation, signed, **binding)
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM main.email_continuations")) == "verified"


def test_concurrent_pairing_reconciles_one_receipt_and_rejects_new_assertion(round_trip):
    service, pairing, continuation, signed, binding, _, _ = round_trip
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(
            lambda _: pairing.pair(continuation, signed, **binding), range(2)
        )
    assert first == second
    other = SecretStr("different signed source binding")
    grant, source = pairing.source.verify_pairing.return_value
    pairing.source.verify_pairing.return_value = (
        grant,
        source.model_copy(
            update={
                "binding_assertion_hash": digest(other.get_secret_value()),
            }
        ),
    )
    with pytest.raises(ProviderDenied):
        pairing.pair(continuation, other, **binding)
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM main.identity_commands")) == 1
        assert connection.scalar(text("SELECT count(*) FROM main.login_attempts")) == 2


def test_receipt_write_failure_rolls_back_pairing(round_trip):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    service, pairing, continuation, signed, binding, _, _ = round_trip

    def fail_receipt(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO main.identity_commands" in statement:
            raise OperationalError("receipt unavailable", None, RuntimeError())

    event.listen(service.engine, "before_cursor_execute", fail_receipt)
    try:
        with pytest.raises(OperationalError):
            pairing.pair(continuation, signed, **binding)
    finally:
        event.remove(service.engine, "before_cursor_execute", fail_receipt)
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM main.login_attempts")) == 1
        assert connection.scalar(text("SELECT state FROM main.email_continuations")) == "verified"
    assert pairing.pair(continuation, signed, **binding)["result_id"] == continuation
