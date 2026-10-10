"""Raw browser clients exercise the boundary; domain tests use explicit local CLI clients."""

import json
import sqlite3
import re
from unittest.mock import patch, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, status
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from app import __main__ as cli

from app.bootstrap.api import create_app
from app.platform.browser_transport import BrowserTransportMiddleware, BrowserTransportPolicy
from app.platform.config import LocalConfig
from app.modules.workspace.application.service import WorkspaceService

LOCAL_ORIGIN = "http://127.0.0.1:8000"
DEV_ORIGIN = "http://localhost:5173"
ACCEPTED_CLIENT_MODES = 2
CLI_USAGE_ERROR = 2


def boundary(policy=BrowserTransportPolicy()):
    app = FastAPI()
    app.add_middleware(BrowserTransportMiddleware, policy=policy)
    reached = Mock()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def operation(request: Request):
        reached()
        await request.body()
        return {"accepted": True}

    return app, reached


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example",
        "127.0.0.1.attacker.example",
        "localhost.attacker.example",
        "0.0.0.0",
        "testserver",
        "localhost:",
    ],
)
def test_host_rejection_precedes_routes(host):
    app, reached = boundary()
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        result = client.post("/api/tasks", headers={"Host": host, "Origin": LOCAL_ORIGIN})
    assert result.status_code == status.HTTP_403_FORBIDDEN
    assert result.json()["detail"]["code"] == "transport_host_rejected"
    reached.assert_not_called()


@pytest.mark.parametrize("origin", ["http://localhost:8000", "http://[::1]:8000", LOCAL_ORIGIN])
def test_loopback_aliases_require_their_own_matching_origin(origin):
    app, reached = boundary()
    with TestClient(app, base_url=origin) as client:
        assert (
            client.post("/api/command", headers={"Origin": origin}).status_code
            == status.HTTP_200_OK
        )
        assert (
            client.post("/api/command", headers={"Origin": "http://localhost:8001"}).status_code
            == status.HTTP_403_FORBIDDEN
        )
    reached.assert_called_once()


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://attacker.example",
        "http://localhost:5173",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8000/path",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000\t",
    ],
)
def test_production_rejects_foreign_or_malformed_origins(origin):
    app, reached = boundary()
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        result = client.post(
            "/api/files", headers={"Origin": origin}, files={"file": ("a.txt", b"bytes")}
        )
    assert result.status_code == status.HTTP_403_FORBIDDEN
    reached.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_same_origin_and_explicit_cli_mutations(method):
    app, reached = boundary()
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        assert (
            client.request(method, "/api/command", headers={"Origin": LOCAL_ORIGIN}).status_code
            == status.HTTP_200_OK
        )
        assert (
            client.request(method, "/api/command", headers={"X-EPM-Local-Client": "1"}).status_code
            == status.HTTP_200_OK
        )
        assert client.request(method, "/api/command").status_code == status.HTTP_403_FORBIDDEN
        assert (
            client.request(
                method,
                "/api/command",
                headers={"X-EPM-Local-Client": "1", "Sec-Fetch-Site": "same-origin"},
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
    assert reached.call_count == ACCEPTED_CLIENT_MODES


def test_development_preflight_is_exact_and_does_not_dispatch():
    app, reached = boundary(BrowserTransportPolicy((DEV_ORIGIN,)))
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        response = client.options(
            "/api/files",
            headers={
                "Origin": DEV_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.headers["access-control-allow-origin"] == DEV_ORIGIN
        assert "access-control-allow-credentials" not in response.headers
        reached.assert_not_called()
        response = client.post(
            "/api/files",
            headers={"Origin": DEV_ORIGIN, "Sec-Fetch-Site": "cross-site"},
            files={"file": ("x.txt", b"bytes")},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["access-control-allow-origin"] == DEV_ORIGIN
        assert (
            client.options(
                "/api/files",
                headers={
                    "Origin": DEV_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "X-EPM-Local-Client",
                },
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            client.options(
                "/api/files",
                headers={
                    "Origin": "http://localhost:5174",
                    "Access-Control-Request-Method": "POST",
                },
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
    reached.assert_called_once()


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://remote.example",
        "http://localhost:0",
        "http://localhost:99999",
        "http://localhost:5173/",
        "http://localhost:5173?query",
    ],
)
def test_configuration_is_fail_closed(origin):
    with pytest.raises(ValueError):
        BrowserTransportPolicy((origin,))


def test_cross_site_metadata_without_origin_cannot_be_disguised_as_cli():
    app, reached = boundary()
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        for method in ("GET", "POST"):
            response = client.request(
                method,
                "/api/data",
                headers={"Sec-Fetch-Site": "cross-site", "X-EPM-Local-Client": "1"},
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
        assert (
            client.get("/api/data", headers={"Sec-Fetch-Site": "same-origin"}).status_code
            == status.HTTP_200_OK
        )
    reached.assert_called_once()


def test_duplicate_host_or_origin_is_rejected():
    app, reached = boundary()
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        for headers in (
            [("Host", "localhost"), ("Host", "attacker.example")],
            [("Origin", LOCAL_ORIGIN), ("Origin", "null")],
        ):
            assert (
                client.post("/api/command", headers=headers).status_code
                == status.HTTP_403_FORBIDDEN
            )
    reached.assert_not_called()


def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}), encoding="utf-8"
    )
    return path


def test_unavailable_workspace_and_blocked_requests_never_connect(tmp_path):
    path = config(tmp_path)
    with patch.object(Engine, "connect", side_effect=AssertionError("database read")):
        app = create_app(path)
        with TestClient(app, base_url=LOCAL_ORIGIN) as client:
            assert client.get("/openapi.json").status_code == status.HTTP_200_OK
            schema = client.get("/openapi.json").json()
            assert schema["paths"]["/api/properties"]["post"]["responses"]["403"]["content"][
                "application/json"
            ]["schema"]["$ref"].endswith("/TransportErrorResponse")
            assert (
                client.post("/api/properties", headers={"Origin": "null"}).status_code
                == status.HTTP_403_FORBIDDEN
            )
            assert client.post(
                "/api/properties", headers={"Origin": LOCAL_ORIGIN}, json={}
            ).status_code in {
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                status.HTTP_503_SERVICE_UNAVAILABLE,
            }
    assert not (tmp_path / "workspace").exists()


def test_real_mutations_replay_and_hostile_requests_leave_workspace_unchanged(tmp_path):
    path = config(tmp_path)
    workspace = WorkspaceService(LocalConfig(path, tmp_path / "workspace"))
    workspace.initialize()
    app = create_app(path)
    payload = {
        "expectedPropertyRevision": 0,
        "idempotencyKey": str(uuid4()),
        "displayName": "Transport office",
        "addressLine1": "10 Oak Road",
        "city": "Portland",
        "region": "OR",
        "countryCode": "US",
        "propertyType": "office",
        "ownerships": [{"ownerKind": "local_operator"}],
    }
    with TestClient(app, base_url=LOCAL_ORIGIN) as client:
        original = client.post("/api/properties", json=payload, headers={"Origin": LOCAL_ORIGIN})
        assert original.status_code == status.HTTP_201_CREATED, original.text
        assert (
            client.post("/api/properties", json=payload, headers={"X-EPM-Local-Client": "1"}).json()
            == original.json()
        )
        with sqlite3.connect(workspace.paths.database) as connection:
            before = list(connection.iterdump())
        files_before = sorted(workspace.paths.files.rglob("*"))
        with patch.object(Engine, "connect", side_effect=AssertionError("blocked request queried")):
            routes = [
                (method, re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000001", path))
                for path, operations in app.openapi()["paths"].items()
                for method in (name.upper() for name in operations)
                if method in {"POST", "PUT", "PATCH", "DELETE"}
            ]
            assert routes
            for method, route in routes:
                response = client.request(
                    method, route, headers={"Origin": "https://attacker.example"}, json=payload
                )
                assert response.status_code == status.HTTP_403_FORBIDDEN
                assert response.json()["detail"]["code"] == "transport_origin_rejected"
        with sqlite3.connect(workspace.paths.database) as connection:
            assert list(connection.iterdump()) == before
        assert sorted(workspace.paths.files.rglob("*")) == files_before


def test_cli_startup_is_loopback_without_forwarded_header_trust(tmp_path):
    path = config(tmp_path)
    runner, factory = Mock(), Mock()
    modules = {"uvicorn": runner, "app.bootstrap.api": factory}
    with (
        patch(
            "sys.argv", ["epm", "--config", str(path), "serve", "--development-origin", DEV_ORIGIN]
        ),
        patch.object(cli, "import_module", side_effect=modules.__getitem__),
    ):
        cli.main()
    kwargs = runner.run.call_args.kwargs
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["proxy_headers"] is False
    assert factory.create_app.call_args.kwargs["transport_policy"].development_origins == (
        DEV_ORIGIN,
    )


def test_invalid_cli_port_is_rejected_before_loading_workspace():
    with (
        patch("sys.argv", ["epm", "serve", "--port", "0"]),
        patch.object(
            cli.WorkspaceService,
            "from_local_config",
            side_effect=AssertionError("workspace loaded"),
        ),
        pytest.raises(SystemExit) as error,
    ):
        cli.main()
    assert error.value.code == CLI_USAGE_ERROR
