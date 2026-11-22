"""Focused H03.12 exit-gap checks for no_secret_url_log and local_mode_independent."""

import json
import logging
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from app.bootstrap.api import create_app
from app.modules.hosted_access.api.central_identity import build_central_identity_app
from app.modules.hosted_access.application.identity_setup import IdentitySetup
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.firebase_rest import JsonResponse
from app.modules.hosted_access.infrastructure.provider_configuration import (
    load_provider_configuration,
)
from app.modules.workspace.application.service import WorkspaceService
from app.platform.testing_client import LocalApiClient

pytest_plugins = ("app.modules.hosted_access.tests.central_fixtures",)


def test_no_secret_url_log_with_synthetic_markers(central, central_start, caplog, tmp_path):
    service, tick, _ = central
    marker_token = "SYNTHETIC_SECRET_ID_TOKEN_MARKER_9911"
    marker_code = "SYNTHETIC_SECRET_OOB_CODE_MARKER_8822"
    marker_refresh = "SYNTHETIC_SECRET_REFRESH_TOKEN_MARKER_7733"
    marker_cookie = "SYNTHETIC_SECRET_SESSION_COOKIE_MARKER_6644"

    (tmp_path / "index.html").write_text("<!doctype html><title>Central</title>")
    app = build_central_identity_app(
        service,
        web_config={"firebase": {"apiKey": "public"}},
        ui_directory=tmp_path,
        network_source=lambda _request: "203.0.113.0/24",
    )
    origin = service.attempts.setup.origins.central
    client = TestClient(app, base_url=origin, follow_redirects=False)

    caplog.set_level(logging.DEBUG)
    attempt, browser = central_start(service, tick, method="google")
    client.cookies.set("__Host-epm-auth-browser", browser)

    # Failed completion with synthetic token marker must not leak marker in response or logs.
    bad = client.post(
        "/auth/complete",
        json={"attemptId": attempt, "token": marker_token, "remembered": False},
        headers={"Origin": origin},
    )
    assert bad.status_code == 401
    assert bad.headers.get("cache-control") == "no-store"
    assert bad.headers.get("referrer-policy") == "no-referrer"
    assert marker_token not in bad.text
    assert marker_token not in caplog.text

    # Email completion with synthetic oobCode/refreshToken/sessionCookie must not leak markers.
    attempt_mail, browser_mail = central_start(service, tick, method="email_link")
    client.cookies.set("__Host-epm-auth-browser", browser_mail)
    service.provider.complete_email_link = Mock(side_effect=ProviderDenied())
    bad_mail = client.post(
        "/auth/email/continue",
        json={
            "attemptId": attempt_mail,
            "email": "operator@example.invalid",
            "code": marker_code,
            "remembered": False,
        },
        headers={"Origin": origin},
    )
    assert bad_mail.status_code == 401
    assert bad_mail.headers.get("cache-control") == "no-store"
    assert bad_mail.headers.get("referrer-policy") == "no-referrer"
    for marker in (marker_code, marker_refresh, marker_cookie):
        assert marker not in bad_mail.text
        assert marker not in caplog.text


def test_email_completion_adapter_discards_refresh_token_marker(provider, caplog):
    from app.modules.hosted_access.tests.test_firebase_provider import rest

    _, sign, _, _ = provider
    client, http = rest(provider)
    refresh_marker = "SYNTHETIC_REFRESH_MARKER_5544"
    id_token = sign({"email": "user@example.invalid", "firebase": {"sign_in_provider": "password"}})
    session_cookie = sign(
        {
            "iss": f"https://session.firebase.google.com/{client.setup.realm.project_id}",
            "email": "user@example.invalid",
            "firebase": {"sign_in_provider": "password"},
        }
    )
    http.request.side_effect = [
        JsonResponse(
            {"idToken": id_token, "localId": "uid", "refreshToken": refresh_marker},
            0,
        ),
        JsonResponse({"users": [{"localId": "uid", "disabled": False, "validSince": "0"}]}, 0),
        JsonResponse({"sessionCookie": session_cookie}, 0),
    ]
    caplog.set_level(logging.DEBUG)
    cookie, proof = client.complete_email_link(
        "user@example.invalid",
        SecretStr("SYNTHETIC_OOB_CODE"),
        remembered=False,
    )
    assert cookie.get_secret_value() == session_cookie
    assert proof.subject == "uid"
    assert refresh_marker not in repr(proof)
    assert refresh_marker not in caplog.text


def test_local_mode_independent_without_cloud_or_hosted_roles(tmp_path):
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    manifest = WorkspaceService.from_local_config(config).initialize()
    with LocalApiClient(create_app(config)) as client:
        assert client.get("/api/operator/bootstrap").status_code == 200
        assert client.get("/api/operator/bootstrap").json()["workspaceId"] == str(
            manifest.workspace_id
        )
        # Hosted endpoints fail closed with 404 in local mode without cloud resources.
        assert client.post("/api/hosted/session").status_code == 404
        lease = client.post(
            f"/api/hosted/drafts/{uuid4()}/lease",
            json={"token": "a" * 43, "expectedRevision": 1},
        )
        assert lease.status_code == 404
        assert lease.json()["detail"]["code"] == "hosted_mode_required"

    # Production-local/operator role cannot load cloud provider credentials.
    selection = IdentitySetup.model_validate_json(
        (
            Path(__file__).resolve().parents[6] / "deploy/hosted-mvp/identity/selection.json"
        ).read_bytes()
    )
    with pytest.raises(ProviderUnavailable):
        load_provider_configuration(tmp_path / "missing.json", selection, component="operator")
