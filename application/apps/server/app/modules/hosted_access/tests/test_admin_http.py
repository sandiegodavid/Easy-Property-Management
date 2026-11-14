"""HTTPS Admin entry and cross-browser exchange tests with owning SQLite sessions."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.modules.hosted_access.api.admin_identity import build_admin_identity_app
from app.modules.hosted_access.tests.test_identity_contracts import setup

pytest_plugins = ("app.modules.hosted_access.tests.test_admin_sessions",)


def client(service):
    service.provider.setup.origins = setup().origins
    return TestClient(build_admin_identity_app(service), base_url=setup().origins.admin)


def begin(browser, tick):
    now = tick[0]
    tick[0] -= 20000
    response = browser.get("/auth/start")
    tick[0] = now
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    return response.json()["attemptId"]


def test_exchange_session_logout_and_single_use(composition):
    service, token, tick, _, _ = composition
    browser = client(service)
    attempt = begin(browser, tick)
    payload = {"attemptId": attempt, "token": token.get_secret_value()}
    response = browser.post(
        "/auth/complete", json=payload, headers={"Origin": setup().origins.admin}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert browser.get("/api/admin/session").status_code == 200
    assert (
        browser.post(
            "/auth/complete", json=payload, headers={"Origin": setup().origins.admin}
        ).status_code
        == 401
    )
    assert (
        browser.post("/auth/logout", headers={"Origin": setup().origins.admin}).status_code == 401
    )
    assert (
        browser.post(
            "/auth/logout",
            headers={"Origin": setup().origins.admin, "X-CSRF-Token": response.json()["csrfToken"]},
        ).status_code
        == 200
    )
    assert browser.get("/api/admin/session").status_code == 401
    with service.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT state FROM main.login_attempts WHERE attempt_id=:id"), {"id": attempt}
            )
            == "completed"
        )


def test_other_browser_origin_host_and_duplicate_cookie_deny(composition):
    service, token, tick, _, _ = composition
    browser = client(service)
    other = client(service)
    attempt = begin(browser, tick)
    payload = {"attemptId": attempt, "token": token.get_secret_value()}
    assert (
        other.post(
            "/auth/complete", json=payload, headers={"Origin": setup().origins.admin}
        ).status_code
        == 401
    )
    assert (
        browser.post(
            "/auth/complete", json=payload, headers={"Origin": "https://other.invalid"}
        ).status_code
        == 401
    )
    assert browser.get("/auth/start", headers={"Host": "other.invalid"}).status_code == 401
    assert (
        browser.post(
            "/auth/complete",
            json=payload,
            headers={
                "Origin": setup().origins.admin,
                "Cookie": "__Host-epm-central-challenge=a; __Host-epm-central-challenge=b",
            },
        ).status_code
        == 401
    )
    assert (
        browser.post(
            "/auth/complete", json=payload, headers={"Origin": setup().origins.admin}
        ).status_code
        == 200
    )


def test_oversized_body_and_provider_timeout_cannot_replay_attempt(composition):
    from app.modules.hosted_access.application.managed_provider import ProviderUnavailable

    service, token, tick, _, _ = composition
    browser = client(service)
    attempt = begin(browser, tick)
    headers = {"Origin": setup().origins.admin, "Content-Type": "application/json"}
    assert browser.post("/auth/complete", content="x" * 20001, headers=headers).status_code == 401
    service.provider.lookup_status.side_effect = ProviderUnavailable()
    payload = {"attemptId": attempt, "token": token.get_secret_value()}
    assert browser.post("/auth/complete", json=payload, headers=headers).status_code == 503
    service.provider.lookup_status.side_effect = None
    assert browser.post("/auth/complete", json=payload, headers=headers).status_code == 401


def test_concurrent_exchange_reserves_one_attempt(composition):
    from concurrent.futures import ThreadPoolExecutor

    service, token, tick, _, _ = composition
    service.provider.setup.origins = setup().origins
    now = tick[0]
    tick[0] -= 20000
    attempt, challenge = service.begin()
    tick[0] = now

    def complete():
        from app.modules.hosted_access.application.managed_provider import ProviderDenied

        try:
            return service.sign_in(token, attempt_id=attempt, browser=challenge)
        except ProviderDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: complete(), range(2)))
    assert sum(item is not None for item in results) == 1
    assert service.provider.create_session_cookie.call_count == 1


def test_enrollment_checks_principal_before_any_session(composition):
    service, _, tick, _, change = composition
    browser = client(service)
    attempt = begin(browser, tick)
    primary = service.provider.verifier.google
    from unittest.mock import Mock

    proof = service.provider.create_session_cookie.return_value[1]
    service.provider.verifier.google = Mock(
        return_value=proof.model_copy(update={"method": "google", "mfa_verified_at": None})
    )
    payload = {"attemptId": attempt, "token": "primary-proof", "phase": "enroll"}
    try:
        assert (
            browser.post(
                "/auth/complete", json=payload, headers={"Origin": setup().origins.admin}
            ).status_code
            == 200
        )
        change("suspend", 1)
        assert (
            browser.post(
                "/auth/complete", json=payload, headers={"Origin": setup().origins.admin}
            ).status_code
            == 401
        )
        with service.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM main.admin_sessions")) == 0
    finally:
        service.provider.verifier.google = primary
