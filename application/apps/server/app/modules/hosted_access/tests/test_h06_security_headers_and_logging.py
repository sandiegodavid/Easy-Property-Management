"""H06.4 focused tests: HTTP security header hardening & negative structured log redaction."""

from __future__ import annotations

import json
import logging

from app.modules.host_agent.application.auth_routes import (
    AuthRouteManifest,
    WorkspaceRouteManifest,
)
from app.modules.host_agent.infrastructure.auth_projection import (
    VerifiedAuthEndpoint,
    _route,
    _workspace_eligible_routes,
)
from app.modules.hosted_access.api.managed_business import business_error
from app.modules.hosted_access.api.operator_settings import HEADERS as SETTINGS_HEADERS
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.platform.hosted_logging import (
    REDACTED,
    StructuredJsonFormatter,
    emit_structured_event,
    format_structured_log,
)
from app.platform.hosted_security_headers import (
    API_CSP_VALUE,
    HSTS_HEADER_VALUE,
    PERMISSIONS_POLICY_VALUE,
)


def test_caddy_routes_emit_hsts_permissions_policy_and_nosniff():
    held_manifest = AuthRouteManifest(
        component_id="00000000-0000-4000-8000-000000000641",
        artifact_sha256="a" * 64,
        private_endpoint_id="00000000-0000-4000-8000-000000000642",
    )
    held_ep = VerifiedAuthEndpoint(
        manifest=held_manifest,
        address="10.246.0.10",
        port=8000,
        tls_name="pilot-a.epmdemo.xyz",
    )
    held_route = _route("https://pilot-a.epmdemo.xyz", "GET", "/auth/start", held_ep)
    resp_headers = held_route["handle"][0]["headers"]["response"]["set"]
    assert resp_headers["Strict-Transport-Security"] == [HSTS_HEADER_VALUE]
    assert resp_headers["Permissions-Policy"] == [PERMISSIONS_POLICY_VALUE]
    assert resp_headers["X-Content-Type-Options"] == ["nosniff"]

    ws_manifest = WorkspaceRouteManifest(
        component_id="00000000-0000-4000-8000-000000000641",
        artifact_sha256="a" * 64,
        private_endpoint_id="00000000-0000-4000-8000-000000000642",
        recovery_proof_ref="recovery:pt-1",
    )
    ws_ep = VerifiedAuthEndpoint(
        manifest=ws_manifest,
        address="10.246.0.10",
        port=8000,
        tls_name="pilot-a.epmdemo.xyz",
    )
    _deny, proxy_route = _workspace_eligible_routes("https://pilot-a.epmdemo.xyz", ws_ep)
    ws_resp = proxy_route["handle"][0]["headers"]["response"]["set"]
    assert ws_resp["Strict-Transport-Security"] == [HSTS_HEADER_VALUE]
    assert ws_resp["Permissions-Policy"] == [PERMISSIONS_POLICY_VALUE]
    assert ws_resp["X-Content-Type-Options"] == ["nosniff"]


def test_managed_business_and_operator_settings_emit_full_api_security_headers():
    err_response = business_error(ProviderDenied())
    for headers in (err_response.headers, SETTINGS_HEADERS):
        assert headers["Cache-Control"] == "no-store"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Strict-Transport-Security"] == HSTS_HEADER_VALUE
        assert headers["Permissions-Policy"] == PERMISSIONS_POLICY_VALUE
        assert headers["Content-Security-Policy"] == API_CSP_VALUE


def test_structured_logging_redacts_secrets_cookies_tokens_deks_and_business_payloads(caplog):
    fake_jwt = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1aWQtMSJ9.c2lnbmF0dXJlMTIzNDU2"
    fake_cookie = "__Host-epm-op=super-secret-cookie-value"
    fake_bearer = "Bearer secret-firebase-access-token-999"
    fake_r2_secret = "r2-super-secret-access-key-xyz"
    fake_dek = b"\x01\x02\x03raw-dek-bytes"

    line = format_structured_log(
        "epm-operator",
        "request_failed",
        severity="WARNING",
        authorization=fake_bearer,
        cookie=fake_cookie,
        wrapped_dek="wrapped-dek-b64",
        raw_dek=fake_dek,
        secret_access_key=fake_r2_secret,
        business_data={"tenant_name": "Alice Confidential"},
        detail=f"Upstream rejected {fake_bearer} with jwt {fake_jwt} and {fake_cookie}",
        safe_code="restore_denied",
    )
    for forbidden in (
        "super-secret-cookie-value",
        "secret-firebase-access-token-999",
        fake_jwt,
        fake_r2_secret,
        "wrapped-dek-b64",
        "raw-dek-bytes",
        "Alice Confidential",
    ):
        assert forbidden not in line

    parsed = json.loads(line)
    assert parsed["component"] == "epm-operator"
    assert parsed["event"] == "request_failed"
    assert parsed["severity"] == "WARNING"
    assert parsed["safe_code"] == "restore_denied"
    assert parsed["authorization"] == REDACTED
    assert parsed["cookie"] == REDACTED
    assert parsed["wrapped_dek"] == REDACTED
    assert parsed["raw_dek"] == REDACTED
    assert parsed["secret_access_key"] == REDACTED
    assert parsed["business_data"] == REDACTED

    formatter = StructuredJsonFormatter("epm-admin")
    record = logging.LogRecord(
        name="epm.hosted_admin",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=f"Denied token {fake_jwt} with {fake_cookie}",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert fake_jwt not in formatted
    assert "super-secret-cookie-value" not in formatted
    assert json.loads(formatted)["component"] == "epm-admin"

    test_logger = logging.getLogger("epm.test.h064")
    with caplog.at_level(logging.ERROR, logger="epm.test.h064"):
        emitted = emit_structured_event(
            test_logger,
            "epm-host-guardian",
            "containment_triggered",
            severity="ERROR",
            token="must-not-leak",
        )
    assert "must-not-leak" not in emitted
    assert "must-not-leak" not in caplog.text
