"""H03.7 tests use real owning stores, Ed25519 evidence and independent browser jars."""

from concurrent.futures import ThreadPoolExecutor
import re
from pathlib import Path
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest
from sqlalchemy import event, text

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.central_identity import build_central_identity_app
from app.modules.hosted_access.api.destination_identity import destination_router
from app.modules.hosted_access.application.identity_evidence import HandoffEvidence, IdentityBinding
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.central_handoffs import CentralHandoffs, PairingSource
from app.modules.hosted_access.infrastructure.central_pairing import CentralPairing
from app.modules.hosted_access.infrastructure.destination_identity import DestinationIdentity
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner, verify_evidence
from app.modules.hosted_access.infrastructure.schema_store import bind_disabled_access
from app.modules.hosted_access.tests.test_identity_persistence import binding as disabled_binding
from app.modules.hosted_access.tests.test_firebase_provider import NOW
from app.platform.hosted_schema import initialize_store, validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
from app.platform.tests.test_hosted_schema import FIRST, SECOND

pytest_plugins = ("app.modules.hosted_access.tests.central_fixtures",)
APPLICATION = Path(__file__).resolve().parents[6]
COOKIES = IdentityCookiePolicy()


@pytest.fixture
def handoffs(central, tmp_path):
    service, tick, _ = central
    realm = service.attempts.setup.realm.alias
    origin = service.attempts.source.resolve_start.return_value.target_origin
    binding = IdentityBinding(
        deployment_id=FIRST,
        scope={"operator_id": FIRST, "workspace_id": SECOND},
        binding_id=FIRST,
        resource_generation=1,
        access_epoch=1,
        assignment_revision=1,
        registered_origin_id=FIRST,
        target_origin=origin,
        issuer=realm,
        subject="uid",
    )
    with immediate_transaction(service.engine) as connection:
        connection.execute(text("UPDATE operators SET subject='uid', setup_state='active'"))
    path = tmp_path / "source.sqlite"
    initialize_store(HostedStore.HOSTED_ACCESS, path, application_directory=APPLICATION)
    source_engine = create_sqlite_engine(path)
    try:
        with immediate_transaction(source_engine) as connection:
            bind_disabled_access(
                connection,
                disabled_binding(
                    issuer=realm, workspace_id=SECOND, email_key=realm + ":user@example.invalid"
                ),
                application_directory=APPLICATION,
            )
            connection.execute(
                text("UPDATE access_meta SET subject='uid', effective_access='enabled'")
            )
        central_secret = Ed25519PrivateKey.generate()
        source_secret = Ed25519PrivateKey.generate()

        def central_key(exact_binding, signer, key_id):
            assert (exact_binding, signer, key_id) == (binding, "central_identity", "central-key")
            return central_secret.public_key()

        def source_key(exact_binding, signer, key_id):
            assert (exact_binding, signer, key_id) == (binding, "owning_source", "source-key")
            return source_secret.public_key()

        destination = DestinationIdentity(
            source_engine,
            mutation=lambda: immediate_transaction(source_engine),
            binding=lambda: binding,
            signer=IdentitySigner("source-key", source_secret),
            central_key=central_key,
            clock=lambda: tick[0],
        )
        source = Mock()
        source.observe.side_effect = lambda operator, attempt: destination.observe(attempt)
        source.original.side_effect = destination.observe_receipt
        service.attempts.source.resolve_start.side_effect = destination.login_context
        service.attempts.source.inspect_start.side_effect = lambda operator, attempt: (
            destination.login_context(attempt)
        )
        central_owner = CentralHandoffs(
            service.attempts,
            IdentitySigner("central-key", central_secret),
            source,
            Mock(ready=Mock(return_value=True)),
            deployment_id=service.deployment_id,
        )
        pairing = CentralPairing(
            service.attempts,
            PairingSource(
                source_key,
                lambda scope, attempt: destination.inspect(attempt),
                clock=lambda: tick[0],
            ),
            deployment_id=service.deployment_id,
        )
        yield service, tick, binding, destination, central_owner, pairing
    finally:
        source_engine.dispose()


def google(handoffs, *, remembered=False):
    service, tick, _, destination, central_owner, _ = handoffs
    tick[0] = (NOW - 30) * 1000
    source = destination.begin("/properties")
    attempt, browser = service.attempts.start(source.attempt.attempt_id, method="google")
    tick[0] = NOW * 1000
    verified = service.complete_google(
        attempt, browser, SecretStr("test-token"), remembered=remembered
    )
    issued = central_owner.issue_google(attempt, browser, verified.cookie)
    return issued, source.challenge.get_secret_value(), attempt, browser, verified.cookie


def test_google_bound_session_atomic_receipt_and_no_bearer_replay(handoffs):
    service, _, binding, destination, central, _ = handoffs
    issued, browser, attempt, central_browser, central_cookie = google(handoffs, remembered=True)
    assert issued.target_origin == binding.target_origin
    with pytest.raises(ProviderDenied):
        central.issue_google(attempt, central_browser, central_cookie)
    with pytest.raises(ProviderDenied):
        destination.redeem(issued.token, "z" * 43, central)
    presented = issued.token.get_secret_value()
    stem, signature = presented.split(".")
    with pytest.raises(ProviderDenied):
        destination.redeem(
            SecretStr(stem + "." + ("Z" if signature[0] == "A" else "A") + signature[1:]),
            browser,
            central,
        )

    result = destination.redeem(issued.token, browser, central)
    assert result.return_path == "/properties" and result.remembered
    assert result.csrf.get_secret_value() == destination.csrf_token(
        result.session.get_secret_value()
    )
    with pytest.raises(ProviderDenied):
        destination.redeem(issued.token, browser, central)
    with destination.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM access_sessions")) == 1
        assert (
            connection.scalar(
                text("SELECT count(*) FROM access_audit WHERE action='issue_session'")
            )
            == 1
        )
        receipt = connection.scalar(text("SELECT result_json FROM access_receipts"))
        assert result.session.get_secret_value() not in receipt
        assert result.csrf.get_secret_value() not in receipt
        assert validate_schema(
            connection, HostedStore.HOSTED_ACCESS, application_directory=APPLICATION
        )
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM login_handoffs")) == "redeemed"
        assert connection.scalar(text("SELECT count(*) FROM identity_commands")) == 2
        assert presented not in connection.scalar(text("SELECT code_hash FROM login_handoffs"))
        assert validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)


def test_lost_acknowledgement_keeps_one_session_and_reconciles_original(handoffs):
    _, tick, _, destination, central, _ = handoffs
    issued, browser, *_ = google(handoffs)
    uncertain = Mock(wraps=central)
    uncertain.acknowledge.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        destination.redeem(issued.token, browser, uncertain)
    receipt = uncertain.acknowledge.call_args.args[0]
    with pytest.raises(ProviderDenied):
        destination.redeem(issued.token, browser, central)
    tick[0] += 10 * 60 * 1000
    central.acknowledge(receipt)
    with destination.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM access_sessions")) == 1


def test_failed_source_transaction_can_retry_original_reservation(handoffs):
    service, _, _, destination, central, _ = handoffs
    issued, browser, *_ = google(handoffs)
    with immediate_transaction(destination.engine) as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON main.access_receipts "
            "BEGIN SELECT RAISE(ABORT,'injected receipt failure'); END"
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        destination.redeem(issued.token, browser, central)
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM login_handoffs")) == "redeeming"
    with immediate_transaction(destination.engine) as connection:
        assert connection.scalar(text("SELECT count(*) FROM access_sessions")) == 0
        connection.exec_driver_sql("DROP TRIGGER fail_receipt")
    assert destination.redeem(issued.token, browser, central).session is not None


def field(response, name):
    assert response.status_code == 200, response.text
    value = re.search(r'name="' + name + r'" value="([^"]+)"', response.text)
    assert value
    return value[1]


def test_email_browser_return_only_completing_browser_and_new_destination_can_redeem(
    handoffs, tmp_path
):
    service, tick, binding, destination, central, pairing = handoffs
    login_origin = service.attempts.setup.origins.central
    tick[0] = (NOW - 30) * 1000
    original = destination.begin("/properties")
    attempt, original_central = service.attempts.start(
        original.attempt.attempt_id, method="email_link", email="A.B+tag@example.invalid"
    )
    tick[0] = NOW * 1000

    def complete(browser):
        try:
            return service.complete_email(
                attempt, browser, "A.B+tag@example.invalid", SecretStr("email-code")
            )
        except ProviderDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(complete, ["a" * 43, "b" * 43]))
    ((winner, verified),) = [
        (code * 43, result) for code, result in zip("ab", results, strict=True) if result
    ]
    continuation = verified.result["continuationId"]
    tick[0] += 1000

    api = FastAPI()
    scoped_central = Mock(wraps=central)
    scoped_central.continuation_target.side_effect = lambda identifier: central.continuation_target(
        identifier, binding
    )
    api.include_router(
        destination_router(
            destination,
            scoped_central,
            source_origin=binding.target_origin,
            central_origin=login_origin,
        )
    )
    login = build_central_identity_app(
        service,
        ui_directory=tmp_path,
        web_config={},
        network_source=lambda request: None,
        pairing=pairing,
        handoffs=central,
    )

    with (
        TestClient(
            api, base_url=binding.target_origin, follow_redirects=False
        ) as completing_device,
        TestClient(api, base_url=binding.target_origin, follow_redirects=False) as original_device,
        TestClient(login, base_url=login_origin) as completing_login,
        TestClient(login, base_url=login_origin) as unrelated_login,
    ):
        start = completing_device.get("/auth/start", params={"continuation": continuation})
        data = {"continuationId": continuation, "assertion": field(start, "assertion")}
        assert data["assertion"] not in str(start.url)
        completing_login.cookies.set(COOKIES.central_challenge, winner)
        completing_login.cookies.set(COOKIES.central, verified.cookie.get_secret_value())
        unrelated_login.cookies.set(COOKIES.central_challenge, original_central)
        unrelated_login.cookies.set(COOKIES.central, verified.cookie.get_secret_value())
        assert (
            unrelated_login.post(
                "/auth/email/continue", data=data, headers={"Origin": binding.target_origin}
            ).status_code
            == 401
        )
        transferred = completing_login.post(
            "/auth/email/continue", data=data, headers={"Origin": binding.target_origin}
        )
        token = field(transferred, "handoff")
        assert (
            "form-action " + binding.target_origin in transferred.headers["Content-Security-Policy"]
        )
        original_device.cookies.set(COOKIES.source_challenge, original.challenge.get_secret_value())
        assert (
            original_device.post(
                "/auth/complete", data={"handoff": token}, headers={"Origin": login_origin}
            ).status_code
            == 401
        )
        assert (
            completing_device.post(
                "/auth/complete", data={"handoff": token}, headers={"Origin": binding.target_origin}
            ).status_code
            == 401
        )
        succeeded = completing_device.post(
            "/auth/complete", data={"handoff": token}, headers={"Origin": login_origin}
        )
        assert succeeded.status_code == 303
        assert succeeded.headers["location"] == "/properties"
        assert f"{COOKIES.operator}=" in succeeded.headers["set-cookie"]
        assert "HttpOnly" in succeeded.headers["set-cookie"]

    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM email_continuations")) == "completed"
        assert connection.scalar(text("SELECT count(*) FROM login_handoffs")) == 1
    with destination.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM access_sessions")) == 1


def test_operator_runtime_uses_same_owner_via_bounded_unix_relay(handoffs):
    from contextlib import asynccontextmanager
    import os
    import socket
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace

    from app.modules.host_agent.infrastructure.identity_relay import (
        IdentityRelay,
        IdentityRelayCall,
        invoke_identity,
    )
    from app.modules.hosted_access.application.source_contracts import Disable
    from app.modules.hosted_access.infrastructure.central_session_authority import (
        CentralSessionAuthority,
    )
    from app.modules.hosted_access.infrastructure.handoff_channel import (
        BoundCentralRelay,
        CentralHandoffClient,
        CentralHandoffDispatch,
        SourceBrowserDirectory,
        own_identity_listener,
    )
    from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
        OperatorIdentityInputs,
        compose_operator_identity,
    )

    service, tick, binding, owner, central, _ = handoffs
    issued, browser, *_ = google(handoffs)
    grant = verify_evidence(issued.token, HandoffEvidence, owner.central_key, now=owner.clock())
    login_origin = service.attempts.setup.origins.central
    runtime = SimpleNamespace(ready=True, can_write=True, workspace_id=binding.scope.workspace_id)

    with TemporaryDirectory(dir="/tmp", prefix="h037-") as directory:
        base = Path(directory).resolve()
        source_path, to_source, central_path, to_central = (
            base / name for name in ("s", "rs", "c", "rc")
        )
        with (
            socket.socket(socket.AF_UNIX) as source,
            socket.socket(socket.AF_UNIX) as relay_to_source,
            socket.socket(socket.AF_UNIX) as central_listener,
            socket.socket(socket.AF_UNIX) as relay_to_central,
        ):
            for sock, path in zip(
                (source, relay_to_source, central_listener, relay_to_central),
                (source_path, to_source, central_path, to_central),
                strict=True,
            ):
                sock.bind(str(path))
                sock.listen(8)
            uid = os.getuid()
            registry = Mock()
            registry.by_origin.return_value = binding
            registry.by_operator.return_value = binding
            source_lookup = SourceBrowserDirectory(registry, to_source, relay_uid=uid)
            central.source.original.side_effect = source_lookup.original
            source_client = CentralHandoffClient(to_central, uid, lambda: binding)
            source_resolver = Mock()
            source_resolver.resolve_identity_source.return_value = SimpleNamespace(
                path=source_path, uid=uid
            )
            source_resolver.resolve_identity_control.return_value = SimpleNamespace(
                path=source_path, uid=uid
            )
            source_relay = IdentityRelay(source_resolver)
            authority = CentralSessionAuthority(central, service.provider)

            @asynccontextmanager
            async def lifespan(_app):
                async with (
                    own_identity_listener(relay_to_source, source_relay, peer_uid=uid),
                    own_identity_listener(
                        central_listener,
                        CentralHandoffDispatch(
                            central, lambda: binding, session_authority=authority
                        ),
                        peer_uid=uid,
                    ),
                    own_identity_listener(
                        relay_to_central,
                        BoundCentralRelay(central_path, uid, lambda: binding),
                        peer_uid=uid,
                    ),
                    run_owner(),
                ):
                    yield

            app = FastAPI(lifespan=lifespan)
            run_owner = compose_operator_identity(
                app,
                runtime,
                OperatorIdentityInputs(
                    engine=owner.engine,
                    binding=lambda: binding,
                    signer=owner.signer,
                    central_key=owner.central_key,
                    central=source_client,
                    clock=owner.clock,
                    listener=source,
                    relay_uid=uid,
                    source_origin=binding.target_origin,
                    central_origin=login_origin,
                    usage_reader=lambda: SimpleNamespace(
                        used_bytes=123, usable_bytes=50_000_000, revision=1
                    ),
                ),
            )
            with TestClient(app, base_url=binding.target_origin, follow_redirects=False) as client:
                scope = binding.scope
                observed = source_lookup.inspect_source(
                    scope.operator_id, scope.workspace_id, binding.access_epoch
                )
                assert (observed.usage_bytes, observed.usable_bytes) == (123, 50_000_000)
                assert observed.binding == binding
                assert observed.effective_enabled is True
                with pytest.raises(ProviderDenied):
                    source_lookup.inspect_source(
                        scope.operator_id, scope.workspace_id, binding.access_epoch + 1
                    )
                assert client.get("/api/hosted/session").status_code == 401
                assert client.get("/api/properties").status_code == 503
                assert (
                    source_lookup.resolve_start(
                        grant.source_attempt_id,
                        origin_id=binding.registered_origin_id,
                    ).source_browser_hash
                    == grant.source_browser_hash
                )
                runtime.can_write = False
                with pytest.raises(ProviderUnavailable):
                    source_lookup.resolve_start(
                        grant.source_attempt_id, origin_id=binding.registered_origin_id
                    )
                runtime.can_write = True
                client.cookies.set(COOKIES.source_challenge, browser)
                result = client.post(
                    "/auth/complete",
                    data={"handoff": issued.token.get_secret_value()},
                    headers={"Origin": login_origin},
                )
                assert result.status_code == 303
                assert result.headers["location"] == "/properties"
                source_resolver.resolve_identity_source.assert_called_with(
                    binding.deployment_id,
                    binding.scope,
                    binding.access_epoch,
                )

                cookie = result.cookies[COOKIES.operator]
                sessions = app.state.hosted_source_sessions
                tick[0] = sessions.authorize(cookie).revocation_valid_until
                with pytest.raises(ProviderUnavailable):
                    sessions.authorize(cookie)
                assert sessions.refresh(cookie, source_client.refresh_status)
                assert sessions.authorize(cookie).revocation_valid_until > tick[0]
                command = command_for(owner, Disable(reason="operator-request"))
                revoked = invoke_identity(
                    to_source,
                    IdentityRelayCall(method="execute", command=command),
                    expected_uid=uid,
                )
                assert not revoked.result.effective_enabled
                assert (
                    invoke_identity(
                        to_source,
                        IdentityRelayCall(method="original", command=command),
                        expected_uid=uid,
                    )
                    == revoked
                )
                with pytest.raises(ProviderDenied):
                    sessions.authorize(cookie)


def test_google_post_requires_original_proof_cookie_and_current_source(handoffs, tmp_path):
    service, tick, binding, owner, central, _ = handoffs
    login_origin = service.attempts.setup.origins.central
    login = build_central_identity_app(
        service,
        ui_directory=tmp_path,
        web_config={},
        network_source=lambda request: None,
        handoffs=central,
    )
    with (
        TestClient(login, base_url=login_origin) as first,
        TestClient(login, base_url=login_origin) as second,
    ):
        for browser in (first, second):
            tick[0] = (NOW - 30) * 1000
            source = owner.begin("/properties")
            url = "/auth/start?flow=" + source.attempt.attempt_id
            opened = browser.get(url, headers={"Accept": "application/json"})
            assert opened.status_code == 200
            attempt = opened.json()["attemptId"]
            tick[0] = NOW * 1000
            response = browser.post(
                "/auth/complete",
                json={"attemptId": attempt, "token": "synthetic"},
                headers={"Origin": login_origin},
            )
            assert response.json() == {"state": "verified", "handoffAttempt": attempt}
        original = second.cookies.get(COOKIES.central)
        second.cookies.set(
            COOKIES.central,
            first.cookies.get(COOKIES.central),
            domain="login.epmdemo.xyz",
            path="/",
        )
        assert (
            second.post(
                "/auth/complete", data={"attemptId": attempt}, headers={"Origin": login_origin}
            ).status_code
            == 401
        )
        second.cookies.set(COOKIES.central, original, domain="login.epmdemo.xyz", path="/")
        forwarded = second.post(
            "/auth/complete", data={"attemptId": attempt}, headers={"Origin": login_origin}
        )
        handoff = field(forwarded, "handoff")
        assert handoff not in str(forwarded.url)
        assert f'action="{binding.target_origin}/auth/complete"' in forwarded.text
        assert (
            second.post(
                "/auth/complete", data={"attemptId": attempt}, headers={"Origin": login_origin}
            ).status_code
            == 401
        )


def test_source_disable_after_central_reservation_prevents_session(handoffs):
    service, _, _, owner, central, _ = handoffs
    issued, browser, *_ = google(handoffs)
    interrupted = Mock(wraps=central)

    def reserve_then_disable(token, grant):
        central.reserve(token, grant)
        with immediate_transaction(owner.engine) as connection:
            connection.execute(
                text(
                    "UPDATE access_meta SET effective_access='disabled', session_generation=session_generation+1"
                )
            )

    interrupted.reserve.side_effect = reserve_then_disable
    with pytest.raises(ProviderDenied):
        owner.redeem(issued.token, browser, interrupted)
    interrupted.acknowledge.assert_not_called()
    with owner.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM access_sessions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM access_receipts")) == 0
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM login_handoffs")) == "redeeming"


def new_proof(service, now, *, email=False):
    from app.modules.hosted_access.application.identity_setup import HOUR

    completion = service.provider.complete_email_link if email else service.provider.complete_google
    cookie, proof = completion.return_value
    completion.return_value = (
        cookie,
        proof.model_copy(
            update={"authenticated_at": now, "issued_at": now, "expires_at": now + HOUR}
        ),
    )


def renew_google(handoffs, cookie):
    service, tick, _, destination, central, _ = handoffs
    start = destination.begin("/properties", renewal_cookie=cookie)
    attempt, browser = service.attempts.start(start.attempt.attempt_id, method="google")
    tick[0] += 1000
    new_proof(service, tick[0])
    result = service.complete_google(attempt, browser, SecretStr("fresh"), remembered=True)
    return central.issue_google(attempt, browser, result.cookie), start.challenge.get_secret_value()


def sign_in(handoffs):
    _, _, _, destination, central, _ = handoffs
    issued, browser, *_ = google(handoffs, remembered=True)
    return destination.redeem(issued.token, browser, central)


def fill_slots(destination, *, count):
    from uuid import uuid4
    from app.modules.hosted_access.application.identity_setup import HOUR
    from app.modules.hosted_access.infrastructure.central_attempts import digest

    now = destination.clock()
    with immediate_transaction(destination.engine) as connection:
        row = dict(
            connection.execute(text("SELECT * FROM main.access_sessions LIMIT 1")).mappings().one()
        )
        ids = [str(uuid4()) for _ in range(count)]
        for identifier in ids:
            fields = row | {
                "session_id": identifier,
                "handoff_id": str(uuid4()),
                "session_hash": digest(identifier),
                "issued_at": now,
                "last_seen_at": now,
                "expires_at": now + HOUR,
                "managed_valid_until": now + HOUR,
                "revocation_valid_until": now + 500,
                "revoked_at": None,
            }
            columns = ",".join(fields)
            values = ",".join(":" + key for key in fields)
            connection.execute(
                text(f"INSERT INTO main.access_sessions ({columns}) VALUES ({values})"), fields
            )
        return ids


@pytest.mark.parametrize("expired", [False, True])
def test_renewal_at_cap_replaces_live_slot_but_expiry_only_needs_free_slot(handoffs, expired):
    from app.modules.hosted_access.infrastructure.source_sessions import (
        SessionExpired,
        SessionLimitReached,
        SourceSessions,
    )

    _, tick, _, destination, central, _ = handoffs
    first = sign_in(handoffs)
    cookie, csrf = first.session.get_secret_value(), first.csrf.get_secret_value()
    sessions = SourceSessions(destination)
    prior = sessions.authorize(cookie, csrf=csrf, write=True)
    if expired:
        tick[0] = prior.expires_at + 1000
        with pytest.raises(SessionExpired):
            sessions.authorize(cookie)
    ids = fill_slots(destination, count=32 if expired else 31)
    issued, browser = renew_google(handoffs, cookie)
    with pytest.raises(ProviderDenied):
        destination.redeem(issued.token, browser, central)
    if expired:
        with pytest.raises(SessionLimitReached):
            destination.redeem(issued.token, browser, central, renewal_cookie=cookie)
        with immediate_transaction(destination.engine) as connection:
            connection.execute(
                text("UPDATE main.access_sessions SET revoked_at=:now WHERE session_id=:id"),
                {"now": tick[0], "id": ids[0]},
            )
    result = destination.redeem(issued.token, browser, central, renewal_cookie=cookie)
    assert result.remembered and result.remembered_until == prior.remembered_until
    assert result.receipt.kind == "refresh_session"
    assert result.receipt.renewed_from_session_id == prior.session_id
    with pytest.raises(ProviderDenied):
        sessions.authorize(cookie)
    replacement = sessions.authorize(result.session.get_secret_value())
    assert replacement.remembered_until == prior.remembered_until
    assert replacement.session_hash != prior.session_hash
    with pytest.raises(ProviderDenied):
        destination.redeem(issued.token, browser, central, renewal_cookie=cookie)
    with destination.engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
            SELECT count(*) FROM main.access_sessions WHERE revoked_at IS NULL AND expires_at>:now
        """),
                {"now": tick[0]},
            )
            == 32
        )
        assert validate_schema(
            connection, HostedStore.HOSTED_ACCESS, application_directory=APPLICATION
        )


def test_two_fresh_handoffs_can_replace_one_lineage_only_once(handoffs):
    _, _, _, owner, central, _ = handoffs
    cookie = sign_in(handoffs).session.get_secret_value()
    prepared = [renew_google(handoffs, cookie) for _ in range(2)]

    def run(pair):
        issued, browser = pair
        try:
            return owner.redeem(issued.token, browser, central, renewal_cookie=cookie)
        except ProviderDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(result is not None for result in workers.map(run, prepared)) == 1
    with owner.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM main.access_sessions WHERE renewed_from_session_id IS NOT NULL"
                )
            )
            == 1
        )


def test_provider_status_expiry_outage_and_monotonic_revocation(handoffs):
    from app.modules.hosted_access.infrastructure.central_session_authority import (
        CentralSessionAuthority,
    )
    from app.modules.hosted_access.infrastructure.provider_status import UserStatus
    from app.modules.hosted_access.infrastructure.source_sessions import SourceSessions

    service, tick, binding, owner, central, _ = handoffs
    first = sign_in(handoffs)
    cookie = first.session.get_secret_value()
    authority, sessions = CentralSessionAuthority(central, service.provider), SourceSessions(owner)
    initial = sessions.authorize(cookie)
    lookup = Mock(wraps=service.provider.status_cache.fetch)
    service.provider.status_cache.fetch = lookup
    assert not sessions.refresh(cookie, authority.observe)
    lookup.assert_not_called()
    tick[0] = initial.revocation_valid_until
    with pytest.raises(ProviderUnavailable):
        sessions.authorize(cookie)
    lookup.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        sessions.refresh(cookie, authority.observe)
    with pytest.raises(ProviderUnavailable):
        sessions.authorize(cookie)
    lookup.side_effect = None
    assert sessions.refresh(cookie, authority.observe)
    updated = sessions.authorize(cookie)
    assert updated.managed_observation_revision > initial.managed_observation_revision
    assert updated.managed_valid_until == initial.managed_valid_until
    assert updated.expires_at == initial.expires_at
    signed = authority.observe(binding, updated.session_id, updated.managed_session_id)
    assert lookup.call_count == 2
    tick[0] = updated.revocation_valid_until
    lookup.side_effect = lambda identity: UserStatus(identity.subject, True, 0)
    sessions.refresh(cookie, authority.observe)
    with pytest.raises(ProviderDenied):
        sessions.authorize(cookie)
    with pytest.raises(ProviderDenied):
        sessions.apply_observation(cookie, signed)


def test_recent_auth_binds_browser_session_request_and_consumer_transaction(handoffs):
    from app.modules.hosted_access.infrastructure.central_session_authority import (
        CentralSessionAuthority,
    )
    from app.modules.hosted_access.infrastructure.source_sessions import SourceSessions

    service, tick, binding, owner, central, _ = handoffs
    credentials = sign_in(handoffs)
    cookie, csrf = credentials.session.get_secret_value(), credentials.csrf.get_secret_value()
    sessions = SourceSessions(owner)
    authority = CentralSessionAuthority(central, service.provider)
    central.source.observe_recent.side_effect = lambda _binding, identifier: (
        sessions.observe_recent(identifier)
    )
    request = "a" * 64
    challenge, _ = sessions.begin_recent(cookie, csrf, request)
    central_attempt, browser = authority.start_recent(binding, challenge)
    with pytest.raises(ProviderDenied):
        authority.complete_recent(binding, central_attempt, "z" * 43, SecretStr("token"))
    tick[0] += 1000
    new_proof(service, tick[0])
    grant = authority.complete_recent(binding, central_attempt, browser, SecretStr("token"))
    with pytest.raises(ProviderDenied), immediate_transaction(owner.engine) as connection:
        sessions.consume_recent(connection, cookie, csrf, "b" * 64, grant)

    with (
        pytest.raises(RuntimeError, match="consumer failed"),
        immediate_transaction(owner.engine) as connection,
    ):
        sessions.consume_recent(connection, cookie, csrf, request, grant)
        raise RuntimeError("consumer failed")
    with immediate_transaction(owner.engine) as connection:
        sessions.consume_recent(connection, cookie, csrf, request, grant)
    with pytest.raises(ProviderDenied), immediate_transaction(owner.engine) as connection:
        sessions.consume_recent(connection, cookie, csrf, request, grant)


def command_for(owner, payload, *, key=None):
    from uuid import uuid4
    from app.modules.hosted_access.application.source_contracts import SourceCommand
    from app.platform.hosted_contracts.semantic import semantic_hash

    with owner.engine.connect() as connection:
        revision = connection.scalar(text("SELECT revision FROM main.access_meta"))
    binding = owner.binding()
    envelope = SourceCommand.model_fields["intent"].annotation.model_validate(
        {
            "deployment_id": binding.deployment_id,
            "scope": binding.scope,
            "kind": payload.action,
            "expected_revision": revision,
            "access_epoch": binding.access_epoch,
            "payload": payload,
        }
    )
    return SourceCommand(
        operation_id=str(uuid4()),
        idempotency_key=key or str(uuid4()),
        intent=envelope,
        request_hash=semantic_hash(envelope),
    )


def admin_actor(owner):
    from app.platform.hosted_contracts.authority import ServiceAuthority

    binding = owner.binding()
    return ServiceAuthority(
        deployment_id=binding.deployment_id,
        scope=binding.scope,
        service="admin",
        authenticated_channel_ref="test-peer",
    )


def test_lifecycle_authenticates_exact_proof_and_original_after_epoch_change(handoffs):
    from uuid import uuid4
    from app.modules.hosted_access.application.source_contracts import (
        Claim,
        Disable,
        Enable,
        Rebind,
    )
    from app.modules.hosted_access.infrastructure.source_lifecycle import (
        LifecycleProof,
        SourceLifecycle,
    )
    from app.platform.hosted_contracts.operations import SemanticConflict
    from app.platform.hosted_contracts.semantic import semantic_hash

    _, tick, first, owner, _, _ = handoffs
    actor = admin_actor(owner)
    tick[0] = NOW * 1000
    protected = [first]
    owner.binding = lambda: protected[0]
    proof = Mock()
    proof.verify.side_effect = lambda command, binding: LifecycleProof(
        binding,
        command.request_hash,
        tick[0] + 1000,
        binding.issuer + ":user@example.invalid",
    )
    lifecycle = SourceLifecycle(
        owner.engine,
        mutation=owner.mutation,
        binding=owner.binding,
        clock=owner.clock,
        proof_owner=proof,
    )
    with immediate_transaction(owner.engine) as connection:
        connection.execute(
            text("UPDATE main.access_meta SET effective_access='disabled',subject=NULL")
        )
    enable = command_for(owner, Enable(readiness_proof_ref="readiness"))
    with pytest.raises(ProviderDenied):
        lifecycle.execute(actor, enable)
    claim = command_for(
        owner,
        Claim(
            invitation_id=FIRST, verified_identity_ref="identity", readiness_proof_ref="readiness"
        ),
    )
    assert not lifecycle.execute(actor, claim).result.effective_enabled
    enabling = command_for(owner, Enable(readiness_proof_ref="readiness"))
    before = lifecycle.execute(actor, enabling)
    assert before.result.effective_enabled
    protected[0] = first.model_copy(update={"access_epoch": 2, "assignment_revision": 2})
    disable = command_for(owner, Disable(reason="operator-request"))
    denied = lifecycle.execute(actor, disable)
    assert denied.result.access_epoch == 2 and not denied.result.effective_enabled
    assert (
        lifecycle.execute(actor, enabling.model_copy(update={"operation_id": str(uuid4())}))
        == before
    )
    changed = enabling.intent.model_copy(update={"expected_revision": 3})
    with pytest.raises(SemanticConflict):
        lifecycle.execute(
            actor,
            enabling.model_copy(update={"intent": changed, "request_hash": semantic_hash(changed)}),
        )
    protected[0] = first.model_copy(
        update={"access_epoch": 3, "assignment_revision": 3, "subject": "new-uid"}
    )
    rebind = command_for(
        owner,
        Rebind(
            assignment_id=FIRST,
            assignment_revision=3,
            verified_identity_hash="a" * 64,
            expected_session_generation=2,
        ),
    )
    assert not lifecycle.execute(actor, rebind).result.effective_enabled
    with owner.engine.connect() as connection:
        assert connection.execute(
            text("SELECT subject,access_epoch,session_generation FROM main.access_meta")
        ).one() == ("new-uid", 3, 3)
        assert connection.scalar(text("SELECT count(*) FROM main.access_audit")) == 4


@pytest.mark.parametrize("all_devices", [False, True])
def test_logout_commits_local_before_reconciling_central_role_and_keeps_original(
    handoffs, all_devices
):
    from app.modules.hosted_access.application.source_contracts import Revoke
    from app.modules.hosted_access.infrastructure.central_session_authority import (
        CentralSessionAuthority,
    )
    from app.modules.hosted_access.infrastructure.source_lifecycle import SourceLifecycle
    from app.modules.hosted_access.infrastructure.source_sessions import SourceSessions

    service, tick, binding, owner, central, _ = handoffs
    credentials = sign_in(handoffs)
    cookie, csrf = credentials.session.get_secret_value(), credentials.csrf.get_secret_value()
    sessions = SourceSessions(owner)
    authority = CentralSessionAuthority(central, service.provider)
    lifecycle = SourceLifecycle(
        owner.engine, mutation=owner.mutation, binding=owner.binding, clock=owner.clock
    )
    old = sessions.authorize(cookie)
    from uuid import uuid4

    admin_managed = str(uuid4())
    with immediate_transaction(service.engine) as connection:
        separate = dict(
            connection.execute(
                text("SELECT * FROM main.managed_identity_sessions WHERE managed_session_id=:id"),
                {"id": old.managed_session_id},
            )
            .mappings()
            .one()
        )
        separate.update(
            managed_session_id=admin_managed,
            cookie_hash="a" * 64,
            purpose="admin",
            operator_id=None,
            method="google_totp",
            mfa_verified_at=separate["authenticated_at"],
        )
        fields = ",".join(separate)
        values = ",".join(":" + field for field in separate)
        connection.execute(
            text(f"INSERT INTO main.managed_identity_sessions ({fields}) VALUES ({values})"),
            separate,
        )
    pending, pending_browser = renew_google(handoffs, cookie)
    revoke = command_for(
        owner,
        Revoke(
            session_reference=None if all_devices else old.session_id,
            all_devices=all_devices,
        ),
    )
    channel = Mock()
    channel.reconcile_revocation.side_effect = ProviderUnavailable()
    with pytest.raises(ProviderDenied):
        sessions.logout(lifecycle, channel, cookie, "z" * 43, revoke)
    result = sessions.logout(lifecycle, channel, cookie, csrf, revoke)
    assert not result.central_reconciled
    with pytest.raises(ProviderDenied):
        sessions.authorize(cookie)
    with pytest.raises(ProviderDenied):
        owner.redeem(pending.token, pending_browser, central, renewal_cookie=cookie)

    central.source.original_control.side_effect = lambda command: lifecycle.original(
        admin_actor(owner), command.reference()
    )
    channel.reconcile_revocation.side_effect = lambda command: authority.reconcile_revocation(
        binding, command
    )
    reconciled = sessions.logout(lifecycle, channel, cookie, csrf, revoke)
    assert reconciled.central_reconciled and reconciled.source == result.source
    authority.reconcile_revocation(binding, revoke)
    with owner.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM main.access_receipts WHERE kind='revoke_sessions'")
            )
            == 1
        )
    with service.engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT revoked_at FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                ),
                {"id": admin_managed},
            ).scalar_one()
            is None
        )
        assert (
            connection.scalar(
                text(
                    "SELECT revoked_at FROM main.managed_identity_sessions WHERE managed_session_id=:id"
                ),
                {"id": old.managed_session_id},
            )
            == tick[0]
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM main.admin_audit WHERE action IN ('revoke_session','revoke_all')"
                )
            )
            == 1
        )
        assert connection.scalar(
            text("SELECT count(*) FROM main.managed_identity_sessions WHERE revoked_at IS NOT NULL")
        ) == (2 if all_devices else 1)


def test_email_renewal_requires_predecessor_cookie_on_completing_device(handoffs):
    service, tick, binding, owner, central, pairing = handoffs
    first = sign_in(handoffs)
    cookie = first.session.get_secret_value()
    start = owner.begin("/properties", renewal_cookie=cookie)
    attempt, browser = service.attempts.start(
        start.attempt.attempt_id,
        method="email_link",
        email="A.B+tag@example.invalid",
    )
    tick[0] += 1000
    new_proof(service, tick[0], email=True)
    verified = service.complete_email(
        attempt,
        browser,
        "A.B+tag@example.invalid",
        SecretStr("fresh-code"),
        remembered=False,
    )
    continuation = verified.result["continuationId"]
    target = central.continuation_target(continuation, binding)
    with pytest.raises(ProviderDenied):
        owner.begin(
            target.return_path,
            continuation_id=continuation,
            continuation_expires=target.expires_at,
            expected_renewal=target.renewal,
        )
    fresh = owner.begin(
        target.return_path,
        continuation_id=continuation,
        continuation_expires=target.expires_at,
        expected_renewal=target.renewal,
        renewal_cookie=cookie,
    )
    pairing.pair(
        continuation,
        fresh.assertion,
        origin=binding.target_origin,
        browser=browser,
        cookie=verified.cookie.get_secret_value(),
    )
    issued = central.issue_paired(continuation, browser, verified.cookie)
    updated = owner.redeem(
        issued.token, fresh.challenge.get_secret_value(), central, renewal_cookie=cookie
    )
    assert updated.receipt.renewed_from_session_id == first.receipt.session_id
    assert updated.remembered_until == first.remembered_until


def test_concurrent_new_issuance_has_only_one_remaining_slot(handoffs):
    from app.modules.hosted_access.infrastructure.source_sessions import SessionLimitReached

    service, tick, _, owner, central, _ = handoffs
    sign_in(handoffs)
    fill_slots(owner, count=30)
    attempts = []
    for _ in range(2):
        opened = owner.begin("/properties")
        attempt, browser = service.attempts.start(opened.attempt.attempt_id, method="google")
        tick[0] += 1000
        new_proof(service, tick[0])
        result = service.complete_google(attempt, browser, SecretStr("fresh"), remembered=True)
        attempts.append((central.issue_google(attempt, browser, result.cookie), opened.challenge))

    def redeem(values):
        handoff, challenge = values
        try:
            return owner.redeem(handoff.token, challenge.get_secret_value(), central)
        except SessionLimitReached:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(result is not None for result in workers.map(redeem, attempts)) == 1
    with owner.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM main.access_sessions")) == 32


def test_session_admission_one_select_and_no_provider_fetch(handoffs):
    from app.modules.hosted_access.infrastructure.source_sessions import SourceSessions

    service, _, _, owner, _, _ = handoffs
    credentials = sign_in(handoffs)
    seen = []

    def listener(_conn, _cursor, statement, *_rest):
        if statement.lstrip().startswith("SELECT"):
            seen.append(statement)

    event.listen(owner.engine, "before_cursor_execute", listener)
    try:
        assert (
            SourceSessions(owner).authorize(credentials.session.get_secret_value()).session_id
            == credentials.receipt.session_id
        )
    finally:
        event.remove(owner.engine, "before_cursor_execute", listener)
    assert len(seen) == 1
    service.provider.complete_google.assert_called_once()


def test_security_lists_only_public_device_fields_and_checks_original_logout(handoffs):
    from secrets import token_urlsafe
    from uuid import uuid4
    from app.modules.hosted_access.api.operator_security import operator_security_router
    from app.modules.hosted_access.infrastructure.central_session_authority import (
        CentralSessionAuthority,
    )
    from app.modules.hosted_access.infrastructure.operator_security import OperatorSecurity
    from app.modules.hosted_access.infrastructure.source_lifecycle import SourceLifecycle
    from app.modules.hosted_access.infrastructure.source_sessions import SourceSessions

    service, tick, binding, owner, central, _ = handoffs
    credentials = sign_in(handoffs)
    first = credentials.session.get_secret_value()
    tick[0] += 1000
    start = owner.begin("/sign-in")
    attempt, challenge = service.attempts.start(start.attempt.attempt_id, method="google")
    new_proof(service, tick[0])
    verified = service.complete_google(attempt, challenge, SecretStr("token"))
    handoff = central.issue_google(attempt, challenge, verified.cookie)
    second = owner.redeem(
        handoff.token, start.challenge.get_secret_value(), central, device_label="Firefox"
    )
    sessions = SourceSessions(owner)
    lifecycle = SourceLifecycle(
        owner.engine, mutation=owner.mutation, binding=owner.binding, clock=owner.clock
    )
    authority = CentralSessionAuthority(central, service.provider)
    central.source.original_control.side_effect = lambda command: lifecycle.original(
        admin_actor(owner), command.reference()
    )
    channel = Mock()
    channel.reconcile_revocation.side_effect = ProviderUnavailable()
    security = OperatorSecurity(owner, sessions, lifecycle, channel)
    app = FastAPI()
    app.include_router(operator_security_router(security, origin=binding.target_origin))
    headers = {"Origin": binding.target_origin, "X-EPM-CSRF": credentials.csrf.get_secret_value()}
    logout = "/api/hosted/session/logout"
    with TestClient(app, base_url=binding.target_origin) as client:
        client.cookies.set(COOKIES.operator, first)
        session = client.get("/api/hosted/session").json()
        assert set(session) == {
            "identity",
            "sessionId",
            "expiresAt",
            "renewAfter",
            "csrfToken",
            "supportContact",
            "capabilities",
        }
        tick[0] = session["renewAfter"]
        paused = client.get("/api/hosted/session")
        assert paused.status_code == 503
        assert paused.json() == {
            "state": "unavailable",
            "refreshCsrf": credentials.csrf.get_secret_value(),
        }
        channel.refresh_status.side_effect = authority.observe
        assert (
            client.post(
                "/api/hosted/session/refresh", headers=headers | {"X-EPM-CSRF": "x" * 43}
            ).status_code
            == 401
        )
        assert client.post("/api/hosted/session/refresh", headers=headers).status_code == 200
        listed = client.get("/api/hosted/sessions").json()["items"]
        assert len(listed) == 2
        assert all(set(item) == {"sessionId", "label", "lastSeenAt", "current"} for item in listed)
        assert [item["label"] for item in listed if not item["current"]] == ["Firefox"]
        device_form = {
            "operation": str(uuid4()),
            "proof": token_urlsafe(32),
            "selection": "other",
            "device": second.receipt.session_id,
        }
        assert (
            client.post(
                logout,
                data=device_form,
                headers=headers | {"Origin": "https://unrelated.example.invalid"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                logout, data=device_form, headers=headers | {"X-EPM-CSRF": "x" * 43}
            ).status_code
            == 401
        )
        response = client.post(logout, data=device_form, headers=headers)
        assert response.json() == {"state": "pending"}
        assert "set-cookie" not in response.headers
        assert client.get("/api/hosted/session").status_code == 200
        with pytest.raises(ProviderDenied):
            sessions.authorize(second.session.get_secret_value())
        channel.reconcile_revocation.side_effect = lambda command: authority.reconcile_revocation(
            binding, command
        )
        assert client.post(
            logout + "/check", data=device_form | {"proof": token_urlsafe(32)}, headers=headers
        ).json() == {"state": "unknown"}
        assert client.post(logout + "/check", data=device_form, headers=headers).json() == {
            "state": "confirmed"
        }
        current_form = {
            "operation": str(uuid4()),
            "proof": token_urlsafe(32),
            "selection": "current",
            "device": "",
        }
        exited = client.post(logout, data=current_form, headers=headers)
        assert exited.json() == {"state": "confirmed"}
        assert "Max-Age=0" in exited.headers["set-cookie"]
        assert client.get("/api/hosted/session").status_code == 401
        assert client.post(
            logout + "/check", data=current_form, headers={"Origin": binding.target_origin}
        ).json() == {"state": "confirmed"}
        with TestClient(app, base_url=binding.target_origin) as interrupted:
            interrupted.cookies.set(
                COOKIES.operator, first, domain="synthetic-operator.example.invalid"
            )
            replay = interrupted.post(
                logout + "/check", data=current_form, headers={"Origin": binding.target_origin}
            )
            assert replay.json() == {"state": "confirmed"}
            assert "Max-Age=0" in replay.headers["set-cookie"]


def test_capped_browser_selects_one_device_with_original_fresh_handoff(handoffs):
    service, tick, binding, owner, central, _ = handoffs
    first = sign_in(handoffs)
    fill_slots(owner, count=31)
    start = owner.begin("/sign-in")
    attempt, browser = service.attempts.start(start.attempt.attempt_id, method="google")
    tick[0] += 1000
    new_proof(service, tick[0])
    verified = service.complete_google(attempt, browser, SecretStr("fresh-token"))
    issued = central.issue_google(attempt, browser, verified.cookie)
    central_origin = service.attempts.setup.origins.central
    app = FastAPI()
    app.include_router(
        destination_router(
            owner, central, source_origin=binding.target_origin, central_origin=central_origin
        )
    )
    with TestClient(app, base_url=binding.target_origin, follow_redirects=False) as client:
        token = issued.token.get_secret_value()
        challenge = start.challenge.get_secret_value()
        form = {"handoff": token}
        headers = {"Origin": central_origin, "Accept": "text/html"}
        assert client.post("/auth/complete", headers=headers, data=form).status_code == 401
        client.cookies.set(COOKIES.source_challenge, challenge)
        capped = client.post("/auth/complete", headers=headers, data=form)
        assert capped.status_code == 409
        assert capped.text.count("<option") == 33
        assert "hand" + "off=" not in str(capped.url)
        choice = form | {"device": first.receipt.session_id}
        assert client.post("/auth/complete", headers=headers, data=choice).status_code == 401
        same_origin = {"Origin": binding.target_origin, "Accept": "text/html"}
        result = client.post("/auth/complete", headers=same_origin, data=choice)
        assert result.status_code == 303
        assert result.headers["location"] == "/sign-in"
        assert client.post("/auth/complete", headers=same_origin, data=choice).status_code == 401
    with owner.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM main.access_sessions WHERE revoked_at IS NULL")
            )
            == 32
        )
        assert (
            connection.scalar(
                text("SELECT revoked_at FROM main.access_sessions WHERE session_id=:id"),
                {"id": first.receipt.session_id},
            )
            == tick[0]
        )


def test_managed_entry_serves_packaged_security_on_registered_https_only(handoffs, tmp_path):
    import json
    import os
    import socket
    from tempfile import TemporaryDirectory

    from app.bootstrap.api import create_app
    from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
        OperatorIdentityInputs,
    )
    from app.modules.workspace.application.service import WorkspaceService

    service, _, binding, owner, central, _ = handoffs
    configuration = tmp_path / "local.json"
    configuration.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    manifest = WorkspaceService.from_local_config(configuration).initialize()
    binding = binding.model_copy(
        update={
            "scope": binding.scope.model_copy(update={"workspace_id": str(manifest.workspace_id)})
        }
    )
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text(
        '<html><head></head><body><div id="root"></div></body></html>'
    )
    (build / "assets").mkdir()
    (build / "assets" / "app.js").write_text("void 0;")
    with TemporaryDirectory(dir="/tmp") as directory, socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(Path(directory) / "source.sock"))
        app = create_app(
            configuration,
            web_build_path=build,
            operator_identity_inputs=OperatorIdentityInputs(
                engine=owner.engine,
                binding=lambda: binding,
                signer=owner.signer,
                central_key=owner.central_key,
                central=central,
                clock=owner.clock,
                listener=listener,
                relay_uid=os.getuid(),
                source_origin=binding.target_origin,
                central_origin=service.attempts.setup.origins.central,
                support_contact="help@example.invalid",
            ),
        )
        with TestClient(app, base_url=binding.target_origin) as client:
            entry = client.get("/sign-in", headers={"Accept": "text/html"})
            assert entry.status_code == 200
            assert 'content="hosted_managed"' in entry.text
            assert 'content="help@example.invalid"' in entry.text
            assert "no-store" in entry.headers["Cache-Control"]
            assert client.get("/assets/app.js").status_code == 200
            assert client.get("https://wrong.example.invalid/sign-in").status_code == 403
            assert (
                client.get(
                    binding.target_origin.replace("https:", "http:") + "/sign-in"
                ).status_code
                == 403
            )
            assert client.get("/api/operator/bootstrap").status_code == 503
            assert client.get("/api/hosted/session").status_code == 401


@pytest.fixture
def managed_business(handoffs, tmp_path, monkeypatch):
    import json
    import os
    import socket
    from tempfile import TemporaryDirectory

    from app.bootstrap.api import create_app
    from app.modules.hosted_access.api.managed_business import ManagedBusinessInputs
    from app.modules.hosted_access.application.configuration import WORKSPACE_BYTES
    from app.modules.hosted_access.application.storage_budget import (
        HostedStorageBudget,
        StorageFacts,
    )
    from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
        OperatorIdentityInputs,
    )
    from app.modules.workspace.application.service import WorkspaceService

    service, tick, binding, owner, central, _ = handoffs
    # Prove local revocation even when the central acknowledgment is unavailable.
    monkeypatch.setattr(
        central, "reconcile_revocation", Mock(side_effect=ProviderUnavailable), raising=False
    )
    first, second = sign_in(handoffs), sign_in(handoffs)
    configuration = tmp_path / "local.json"
    configuration.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "business")}))
    workspace = WorkspaceService.from_local_config(configuration)
    manifest = workspace.initialize()
    workspace_id = str(manifest.workspace_id)
    with immediate_transaction(owner.engine) as connection:
        connection.execute(text("UPDATE access_meta SET workspace_id=:id"), {"id": workspace_id})
    binding = binding.model_copy(
        update={"scope": binding.scope.model_copy(update={"workspace_id": workspace_id})}
    )

    def headers(credentials):
        return {
            "Cookie": f"{COOKIES.operator}={credentials.session.get_secret_value()}",
            "Origin": binding.target_origin,
            "X-EPM-CSRF": credentials.csrf.get_secret_value(),
        }

    with TemporaryDirectory(dir="/tmp") as directory, socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(Path(directory) / "source.sock"))
        readiness = Mock(return_value=True)
        budget = HostedStorageBudget(
            lambda: StorageFacts(WORKSPACE_BYTES, WORKSPACE_BYTES, 10**10, 9 * 10**9, 10000)
        )
        app = create_app(
            configuration,
            operator_identity_inputs=OperatorIdentityInputs(
                engine=owner.engine,
                binding=lambda: binding,
                signer=owner.signer,
                central_key=owner.central_key,
                central=central,
                clock=owner.clock,
                listener=listener,
                relay_uid=os.getuid(),
                source_origin=binding.target_origin,
                central_origin=service.attempts.setup.origins.central,
                business=ManagedBusinessInputs(readiness, budget, files=True),
            ),
        )
        with TestClient(app, base_url=binding.target_origin) as client:
            yield client, app, workspace, owner, tick, headers(first), headers(second), readiness


def test_managed_business_orders_draft_claims_and_late_commits(managed_business):
    from uuid import uuid4

    client, app, _, owner, tick, first_headers, second_headers, readiness = managed_business
    form = str(uuid4())
    other_form = str(uuid4())
    lease_path = f"/api/hosted/drafts/{form}/lease"
    recovery = f"/api/operator/recovery/{form}"
    token, other_token = "a" * 43, "b" * 43
    claim = {"token": token, "expectedRevision": 0}
    payload = {
        "schemaVersion": 1,
        "formKey": "task.create",
        "payload": {"title": "Keep these edits"},
        "expectedRevision": 0,
        "idempotencyKey": str(uuid4()),
    }

    assert client.get("/api/operator/bootstrap").status_code == 401
    assert client.get("/api/operator/bootstrap", headers=first_headers).status_code == 200
    identity = client.get("/api/hosted/session", headers=first_headers)
    assert "records.write" in identity.json()["capabilities"]
    assert (
        client.post(
            lease_path,
            headers=first_headers | {"Origin": "https://other.invalid"},
            json=claim,
        ).status_code
        == 403
    )
    assert client.post(lease_path, headers=first_headers, json=claim).status_code == 200
    assert client.put(recovery, headers=first_headers, json=payload).status_code == 409
    saved = client.put(
        recovery,
        headers=first_headers | {"X-EPM-Draft-Lease": token},
        json=payload,
    )
    assert saved.status_code == 200, saved.text
    claim = {"token": other_token, "expectedRevision": 1}
    assert client.post(lease_path, headers=second_headers, json=claim).status_code == 409
    assert (
        client.post(
            f"/api/hosted/drafts/{other_form}/lease",
            headers=second_headers,
            json={"token": "c" * 43, "expectedRevision": 0},
        ).status_code
        == 200
    )
    assert (
        client.post(lease_path, headers=second_headers, json=claim | {"takeover": True}).status_code
        == 200
    )
    payload |= {"expectedRevision": 1, "idempotencyKey": str(uuid4())}
    assert (
        client.put(
            recovery, headers=first_headers | {"X-EPM-Draft-Lease": token}, json=payload
        ).status_code
        == 409
    )
    with immediate_transaction(owner.engine) as connection:
        connection.execute(text("UPDATE access_meta SET restore_generation=restore_generation+1"))
    assert (
        client.put(
            recovery,
            headers=second_headers | {"X-EPM-Draft-Lease": other_token},
            json=payload,
        ).status_code
        == 409
    )
    assert client.post(lease_path, headers=second_headers, json=claim).status_code == 200
    assert client.get(recovery, headers=second_headers).json()["payload"] == {
        "title": "Keep these edits"
    }
    task = {
        "title": "Keep these edits",
        "status": "open",
        "priority": "normal",
        "isAllDay": False,
        "expectedRevision": 0,
        "idempotencyKey": str(uuid4()),
    }
    exact = second_headers | {
        "X-EPM-Prepared-Form": form,
        "X-EPM-Draft-Lease": other_token,
    }
    attempt = client.post(
        recovery + "/attempt",
        headers=exact,
        json={
            "attemptKey": task["idempotencyKey"],
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
        },
    )
    assert attempt.status_code == 200, attempt.text
    wrong_claim = second_headers | {
        "X-EPM-Prepared-Form": other_form,
        "X-EPM-Draft-Lease": "c" * 43,
    }
    # This second form's old claim was invalidated by restore. Reclaim
    # it to show that even current ownership of another form fails.
    assert (
        client.post(
            f"/api/hosted/drafts/{other_form}/lease",
            headers=second_headers,
            json={"token": "c" * 43, "expectedRevision": 0},
        ).status_code
        == 200
    )
    for invalid in (second_headers, wrong_claim):
        response = client.post("/api/tasks", headers=invalid, json=task)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "hosted_draft_lease_conflict"
    original = "/api/tasks/creation-operations/" + task["idempotencyKey"]
    assert client.get(original, headers=second_headers).status_code == 404
    assert client.get(recovery, headers=second_headers).json()["status"] == "outcome_unknown"
    # Expiry during the writer must still roll back the task and its receipt.
    engine = app.state.task_service.unit_of_work.engine
    admitted_at = tick[0]

    def expire_after_receipt(_connection, _cursor, statement, *_args):
        if statement.lstrip().startswith("INSERT INTO task_creation_operations"):
            tick[0] = admitted_at + 60 * 60 * 1000

    event.listen(engine, "after_cursor_execute", expire_after_receipt)
    try:
        expired = client.post("/api/tasks", headers=exact, json=task)
    finally:
        event.remove(engine, "after_cursor_execute", expire_after_receipt)
        tick[0] = admitted_at
    assert expired.status_code == 401, expired.text
    assert client.get(original, headers=second_headers).status_code == 404

    committed = client.post("/api/tasks", headers=exact, json=task)
    assert committed.status_code == 201, committed.text
    assert client.get(original, headers=first_headers).status_code == 200
    tick[0] += 60 * 60 * 1000
    assert client.get(recovery, headers=second_headers).status_code == 401
    readiness.return_value = False
    assert client.get("/api/operator/bootstrap", headers=first_headers).status_code == 503


def test_managed_multipart_revocation_preserves_the_original_attempt(managed_business, monkeypatch):
    from hashlib import sha256
    from secrets import token_urlsafe
    from threading import Event
    from uuid import uuid4

    client, app, workspace, _, _, uploading, other_device, _ = managed_business
    prop = client.post(
        "/api/properties",
        headers=uploading,
        json={
            "displayName": "Upload property",
            "addressLine1": "2345 Time Square Street",
            "city": "New York",
            "region": "NY",
            "postalCode": "10005",
            "countryCode": "US",
            "propertyType": "townhome",
            "ownerships": [{"ownerKind": "local_operator"}],
            "expectedPropertyRevision": 0,
            "idempotencyKey": str(uuid4()),
        },
    )
    assert prop.status_code == 201, prop.text
    issue = client.post(
        "/api/maintenance-issues",
        headers=uploading,
        json={
            "propertyId": prop.json()["id"],
            "summary": "Inspect outlet",
            "description": "Attach the inspection notes.",
            "category": "electrical",
            "reporter": {"role": "manager", "subjectKind": "local_operator"},
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        },
    )
    assert issue.status_code == 201, issue.text

    issue_id = issue.json()["id"]
    content = b"Original multipart evidence"
    digest = sha256(content).hexdigest()
    form, key = str(uuid4()), str(uuid4())
    recovery = f"/api/operator/recovery/{form}"
    lease = f"/api/hosted/drafts/{form}/lease"
    token = token_urlsafe(32)
    editing = uploading | {"X-EPM-Draft-Lease": token, "X-EPM-Prepared-Form": form}
    assert (
        client.post(
            lease, headers=uploading, json={"token": token, "expectedRevision": 0}
        ).status_code
        == 200
    )
    save = client.put(
        recovery,
        headers=editing,
        json={
            "formKey": "file.upload",
            "schemaVersion": 1,
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
            "payload": {
                "expectedRevision": 0,
                "originalName": "evidence.txt",
                "mediaType": "text/plain",
                "contentSha256": digest,
                "entityType": "maintenance_issue",
                "entityId": issue_id,
                "purpose": "supporting_document",
            },
        },
    )
    assert save.status_code == 200, save.text
    attempt = client.post(
        recovery + "/attempt",
        headers=editing,
        json={"attemptKey": key, "expectedRevision": 1, "idempotencyKey": str(uuid4())},
    )
    assert attempt.status_code == 200, attempt.text

    store = app.state.file_service.content_store
    publish = store.store
    staged, release = Event(), Event()

    def pause_after_publication(source):
        pending = publish(source)
        staged.set()
        if not release.wait(10):
            pending.rollback()
            raise AssertionError("Test did not release the staged upload.")
        return pending

    def upload(headers):
        return client.post(
            "/api/files",
            headers=headers,
            data={
                "entity_type": "maintenance_issue",
                "entity_id": issue_id,
                "purpose": "supporting_document",
                "idempotency_key": key,
            },
            files={"file": ("evidence.txt", content, "text/plain")},
        )

    target = workspace.paths.files / "managed" / digest
    original = f"/api/files/commands/by-key/{key}"
    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as pool:
        patch.setattr(store, "store", pause_after_publication)
        incoming = pool.submit(upload, editing)
        try:
            assert staged.wait(10), incoming.result(timeout=1).text
            assert target.read_bytes() == content
            current = client.get("/api/hosted/session", headers=uploading).json()["sessionId"]
            logout = client.post(
                "/api/hosted/session/logout",
                headers=other_device,
                data={
                    "operation": str(uuid4()),
                    "proof": token_urlsafe(32),
                    "selection": "other",
                    "device": current,
                },
            )
            assert logout.status_code == 200, logout.text
            assert logout.json() == {"state": "pending"}
            assert client.get("/api/hosted/session", headers=uploading).status_code == 401
        finally:
            release.set()
        rejected = incoming.result(timeout=10)

    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["detail"]["code"] == "hosted_session_expired"
    assert not target.exists()
    assert client.get(original, headers=other_device).status_code == 404
    saved = client.get(recovery, headers=other_device).json()
    assert (saved["status"], saved["attemptKey"], saved["payload"]) == (
        "outcome_unknown",
        key,
        save.json()["payload"],
    )

    replacement = token_urlsafe(32)
    claim = client.post(
        lease, headers=other_device, json={"token": replacement, "expectedRevision": 2}
    )
    assert claim.status_code == 200, claim.text
    reclaimed = other_device | {"X-EPM-Draft-Lease": replacement, "X-EPM-Prepared-Form": form}
    completed = upload(reclaimed)
    assert completed.status_code == 201, completed.text
    assert target.read_bytes() == content
    assert client.get(original, headers=other_device).json() == completed.json()
    reconciled = client.post(
        recovery + "/reconcile",
        headers=reclaimed,
        json={"expectedRevision": 2, "idempotencyKey": str(uuid4())},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "reconciled"
