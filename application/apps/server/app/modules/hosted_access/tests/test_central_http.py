"""Central exact-origin routes and early email capability scrubbing."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.modules.hosted_access.api.central_identity import build_central_identity_app

pytest_plugins = ("app.modules.hosted_access.tests.central_fixtures",)


def browser(service, tmp_path):
    tmp_path.joinpath("index.html").write_text(
        '<!doctype html><head><script type="module" src="/assets/main.js"></script></head>'
    )
    app = build_central_identity_app(
        service,
        ui_directory=tmp_path,
        web_config={"firebase": {"projectId": service.attempts.setup.realm.project_id}},
        network_source=lambda request: "192.0.2.1",
    )
    return TestClient(app, base_url=service.attempts.setup.origins.central)


def test_email_continuation_scrubs_before_resources_and_uses_new_browser(
    central, central_start, tmp_path
):
    service, tick, _ = central
    attempt, _ = central_start(service, tick, "email_link")
    client = browser(service, tmp_path)
    page = client.get("/auth/email/continue", params={"attempt": attempt, "oobCode": "secret-code"})
    assert page.status_code == 200
    assert page.text.index("history.replaceState") < page.text.index('type="module"')
    assert "secret-code" not in page.text
    assert "nonce-" in page.headers["Content-Security-Policy"]
    cookie = page.headers["set-cookie"]
    assert all(flag in cookie for flag in ("Secure", "HttpOnly", "SameSite=lax"))
    result = client.post(
        "/auth/email/continue",
        json={
            "attemptId": attempt,
            "email": "A.B+tag@example.invalid",
            "code": "secret-code",
        },
        headers={"Origin": service.attempts.setup.origins.central},
    )
    assert result.status_code == 200
    assert result.json()["continueUrl"].startswith(
        "https://synthetic-operator.example.invalid/auth/start?continuation="
    )
    assert "__Host-epm-central=" in result.headers["set-cookie"]
    assert "cookie" not in result.json()
    with service.engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM main.login_attempts")) == "superseded"


def test_origin_body_cookie_and_status_disclosure(central, central_start, tmp_path):
    service, tick, _ = central
    attempt, challenge = central_start(service, tick)
    client = browser(service, tmp_path)
    assert (
        client.post(
            "/auth/complete",
            json={
                "attemptId": attempt,
                "token": "proof",
            },
            headers={"Origin": "https://attacker.invalid"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/auth/start?attempt=" + attempt, headers={"Accept": "application/json"}
        ).status_code
        == 401
    )
    client.cookies.set("__Host-epm-central-challenge", challenge)
    response = client.get("/auth/start?attempt=" + attempt, headers={"Accept": "application/json"})
    assert response.json() == {"state": "pending"}
    assert (
        client.post(
            "/auth/complete",
            content='{"token":"a","token":"b"}',
            headers={
                "Origin": service.attempts.setup.origins.central,
                "Content-Type": "application/json",
            },
        ).status_code
        == 401
    )
    assert service.provider.complete_google.call_count == 0


def test_mail_route_passes_public_attempt_correlation(central, central_start, tmp_path):
    service, tick, _ = central
    client = browser(service, tmp_path)
    response = client.post(
        "/auth/email-link",
        json={
            "flowId": "00000000-0000-4000-8000-000000000099",
            "email": "A.B+tag@example.invalid",
        },
        headers={"Origin": service.attempts.setup.origins.central},
    )
    assert response.status_code == 200
    service.provider.send_email_link.assert_called_once()
    assert (
        service.provider.send_email_link.call_args.kwargs["attempt_id"]
        == response.json()["attemptId"]
    )
    assert "operation" not in response.json()
