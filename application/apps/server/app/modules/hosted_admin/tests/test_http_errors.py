"""Private HTTP errors share the API contract without disclosing private input."""

from fastapi.testclient import TestClient
import pytest

from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.broker import MAX_FRAME

ORIGIN = "http://epm-admin.localhost:8765"
COMMAND = {
    "operation_id": "00000000-0000-4000-8000-000000000001",
    "instance": "c",
    "action": "disable",
    "expected_revision": 0,
    "expected_binding_revision": 0,
    "fence": 0,
    "reason": "Contain access",
    "confirmed": True,
}


def assert_problem(response, status, code, message):
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code, "message": message}}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("changes", "status", "code", "message"),
    [
        (
            {"reason": "x" * 1001},
            413,
            "request_payload_too_large",
            "Request content exceeds an allowed limit.",
        ),
        (
            {"subject": "private-subject" * 20},
            413,
            "request_payload_too_large",
            "Request content exceeds an allowed limit.",
        ),
        *[
            (changes, 422, "request_validation", "Request validation failed.")
            for changes in (
                {"expected_revision": -1},
                {"expected_revision": "private-invalid-revision"},
                {"operation_id": "x" * 36},
                {"confirmed": False},
                {"action": "private-unknown-action"},
                {"reason": " "},
                {"subject": "private-unexpected-subject"},
            )
        ],
    ],
)
def test_command_validation_uses_shared_problem_before_broker(changes, status, code, message):
    calls = []
    with TestClient(create_admin_app(ORIGIN, calls.append), base_url=ORIGIN) as client:
        response = client.post(
            "/commands", json={"command": COMMAND | changes}, headers={"Origin": ORIGIN}
        )
    assert_problem(response, status, code, message)
    assert calls == []


def test_oversized_credential_uses_shared_validation_without_reflecting_input():
    calls = []
    with TestClient(create_admin_app(ORIGIN, calls.append), base_url=ORIGIN) as client:
        for content_type, options in (
            ("application/json", {"json": {"credential": "private-grant" * 12}}),
            ("application/x-www-form-urlencoded", {"data": {"credential": "private-grant" * 12}}),
        ):
            response = client.post(
                "/login" if content_type == "application/json" else "/sign-in",
                headers={"Origin": ORIGIN, "Content-Type": content_type},
                **options,
            )
            assert_problem(
                response,
                413,
                "request_payload_too_large",
                "Request content exceeds an allowed limit.",
            )
    assert calls == []


@pytest.mark.parametrize(
    ("error", "status", "code", "message"),
    [
        (
            AdminError("admin_session_invalid", 401),
            401,
            "admin_session_invalid",
            "Sign in to private administration.",
        ),
        (
            AdminError("admin_csrf_invalid", 403),
            403,
            "admin_csrf_invalid",
            "The administration request is not permitted.",
        ),
        (
            AdminError("admin_operation_conflict", 409),
            409,
            "admin_operation_conflict",
            "The administration request conflicts with the current state.",
        ),
        (
            OSError("private socket /credentials must not escape"),
            503,
            "admin_broker_unavailable",
            "Private administration is unavailable. Try again later.",
        ),
        (
            ValueError("private response must not escape"),
            503,
            "admin_broker_unavailable",
            "Private administration is unavailable. Try again later.",
        ),
    ],
)
def test_broker_errors_use_safe_problem_envelope(error, status, code, message):
    def call(_payload):
        raise error

    with TestClient(create_admin_app(ORIGIN, call), base_url=ORIGIN) as client:
        response = client.get("/session")
    assert_problem(response, status, code, message)


def test_transport_frame_parse_and_framework_errors_use_problem_envelope():
    calls = []
    with TestClient(create_admin_app(ORIGIN, calls.append), base_url=ORIGIN) as client:
        assert_problem(
            client.post("/login", json={"credential": "private-grant"}),
            403,
            "admin_transport_denied",
            "The administration request is not permitted.",
        )
        headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
        assert_problem(
            client.post("/login", content=b"x" * (MAX_FRAME + 1), headers=headers),
            413,
            "admin_request_too_large",
            "Request content exceeds an allowed limit.",
        )
        for content in (b"private-invalid-json", b"[]", b'{"private-field":"private-value"}'):
            assert_problem(
                client.post("/commands", content=content, headers=headers),
                400,
                "admin_request_invalid",
                "The administration request is invalid.",
            )
        assert_problem(
            client.get("/docs"),
            405,
            "admin_request_invalid",
            "The administration request could not be completed.",
        )
    assert calls == []
