"""Fresh candidate launch remains unavailable without its real owning authorities."""

from contextlib import closing, contextmanager
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import HTTPServer
import json
import os
import runpy
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import create_engine
from pydantic import ValidationError

from app.hosted_candidates import runtime, startup
from app.hosted_candidates.binding import LaunchBinding, load_binding
from app.hosted_candidates.runtime import HostedStatusHandler
from app.platform.config import LocalConfig
from app.platform.hosted_artifacts import ArtifactInvalid, ArtifactUnavailable
from app.platform.hosted_schema import initialize_store
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.locking import WorkspaceOperationInProgressError
from app.platform.schema_resources import HostedStore, SchemaResourcesUnavailable
from app.modules.workspace.application.service import WorkspaceService
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment

UNAVAILABLE_EXIT = 3
APPLICATION = Path(__file__).resolve().parents[5]
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def values(tmp_path):
    root = tmp_path.resolve()
    control = root / "control"
    control.mkdir(mode=0o700)
    (control / "data").mkdir(mode=0o700)
    (control / "writer.lock").touch(mode=0o600)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    return dict(
        component="operator",
        deployment_id=FIRST,
        operator_id=FIRST,
        workspace_id=FIRST,
        origin="https://operator.example.com",
        workspace_path=str(workspace),
        control_path=str(control),
        resource_generation=1,
    )


def test_protected_configuration_never_reads_local_or_environment(values, monkeypatch):
    path = Path(values["control_path"]) / "launch.json"
    path.write_text(json.dumps(values))
    path.chmod(0o644)
    monkeypatch.setenv("EPM_WORKSPACE", "/untrusted/workspace")
    if os.geteuid() != 0:
        with pytest.raises(ArtifactInvalid):
            load_binding(path, "operator")
    real = os.fstat

    def root_owned(fd):
        info = real(fd)
        return SimpleNamespace(
            st_mode=info.st_mode, st_uid=0, st_size=info.st_size, st_nlink=info.st_nlink
        )

    monkeypatch.setattr(os, "fstat", root_owned)
    assert load_binding(path, "operator").workspace_path == values["workspace_path"]
    with pytest.raises(ArtifactInvalid):
        load_binding(path, "admin")
    path.chmod(0o666)
    with pytest.raises(ArtifactInvalid):
        load_binding(path, "operator")
    path.chmod(0o644)
    path.write_text('{"component":"admin","component":"operator"}')
    with pytest.raises(ArtifactInvalid):
        load_binding(path, "operator")


@pytest.mark.parametrize(
    "changes",
    [
        {"expiry": "tomorrow"},
        {"workspace_id": None},
        {"operator_id": None},
        {"origin": "https://operator.example.com/"},
        {"origin": "http://operator.example.com"},
        {"origin": "https://operator.example.com:443"},
        {"workspace_path": "."},
        {"component": "admin"},
        {"resource_generation": 0},
    ],
)
def test_incomplete_legacy_or_browser_selected_bindings_reject(values, changes):
    with pytest.raises((ValidationError, ValueError)):
        LaunchBinding(**(values | changes))


def test_binding_paths_cannot_alias_or_follow_symlinks(values, tmp_path):
    with pytest.raises(ValidationError):
        LaunchBinding(**(values | {"workspace_path": values["control_path"]}))
    link = tmp_path / "link"
    link.symlink_to(values["workspace_path"])
    with pytest.raises(ValidationError):
        LaunchBinding(**(values | {"workspace_path": str(link)}))
    with pytest.raises(ArtifactInvalid):
        load_binding(link, "operator")


def test_real_workspace_identity_and_stable_lock_no_schema_creation(values):
    workspace = WorkspaceService(
        LocalConfig(Path(values["control_path"]) / "launch.json", Path(values["workspace_path"]))
    )
    manifest = workspace.initialize()
    values["workspace_id"] = manifest.workspace_id
    binding = LaunchBinding(**values)
    lock_path = Path(values["control_path"]) / "writer.lock"
    inode = lock_path.stat().st_ino
    with HostedWriterLock(lock_path), pytest.raises(WorkspaceOperationInProgressError):
        startup.validate_startup(binding, APPLICATION)
    with pytest.raises(SchemaResourcesUnavailable):
        startup.validate_startup(binding, APPLICATION)
    assert list((Path(values["control_path"]) / "data").iterdir()) == []
    assert not (workspace.paths.root.parent / ".workspace.server.lock").exists()
    with pytest.raises(ArtifactUnavailable):
        startup.validate_startup(binding.model_copy(update={"workspace_id": SECOND}), APPLICATION)
    with HostedWriterLock(lock_path):
        assert lock_path.stat().st_ino == inode


def test_admin_missing_store_is_never_created_and_bound_schema_is_read_only(values):
    values = values | dict(
        component="admin", workspace_id=None, operator_id=None, workspace_path=None
    )
    binding = LaunchBinding(**values)
    target = Path(binding.control_path) / "data/admin.sqlite"
    with pytest.raises(FileNotFoundError):
        startup.validate_startup(binding, APPLICATION)
    assert not target.exists()
    initialize_store(HostedStore.ADMIN, target, application_directory=APPLICATION)
    before = target.read_bytes()
    # An initialized structural store without the deployment binding is not usable.
    with pytest.raises(ArtifactUnavailable):
        startup.validate_startup(binding, APPLICATION)
    assert target.read_bytes() == before
    engine = create_engine(f"sqlite:///{target}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            bind_deployment(
                connection,
                DeploymentMetadata(
                    deployment_id=FIRST,
                    public_base_domain="example.com",
                    login_origin="https://login.example.com",
                    registry_generation=1,
                    created_at=1,
                ),
                application_directory=APPLICATION,
            )
            connection.commit()
    finally:
        engine.dispose()
    before = target.read_bytes()
    with pytest.raises(SchemaResourcesUnavailable):
        startup.validate_startup(binding, APPLICATION)
    assert target.read_bytes() == before


@contextmanager
def server(binding=None):
    with HTTPServer(("127.0.0.1", 0), HostedStatusHandler) as http:
        http.binding = binding
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield http.server_port
        finally:
            http.shutdown()
            thread.join()


def request(port, path, method="GET", **headers):
    with closing(HTTPConnection("127.0.0.1", port, timeout=3)) as client:
        client.request(method, path, headers=headers)
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()


def test_safe_status_is_fresh_no_cache_and_never_serves_business_or_replays(values):
    with server(LaunchBinding(**values)) as port:
        for path in ["/api/tasks", "/openapi.json", "/health/ready", "/assets/main.js"]:
            code, headers, body = request(port, path, Host="operator.example.com")
            assert code == HTTPStatus.SERVICE_UNAVAILABLE
            data = json.loads(body)
            assert data["ready"] is False and data["checkedAt"]
            assert headers["Cache-Control"] == "no-store"
            assert headers["Retry-After"] == "30"
            assert "Python" not in headers["Server"]
            assert values["workspace_path"].encode() not in body
        assert (
            request(
                port, "/", Host="attacker.example", **{"X-Forwarded-Host": "operator.example.com"}
            )[0]
            == HTTPStatus.MISDIRECTED_REQUEST
        )
        assert request(port, "/health/live")[0] == HTTPStatus.OK
        for method in ["POST", "PATCH", "PUT", "DELETE", "OPTIONS"]:
            assert request(port, "/api/tasks", method)[0] == HTTPStatus.SERVICE_UNAVAILABLE
        code, headers, body = request(port, "/", Host="operator.example.com")
        assert code == HTTPStatus.SERVICE_UNAVAILABLE
        assert b"Keep any open form" in body
        assert b'<a href="/">Check availability again</a>' in body
        assert b"<script" not in body and b"<form" not in body
        assert b"http-equiv" not in body
        assert "form-action 'none'" in headers["Content-Security-Policy"]
        code, _, body = request(
            port, "/properties?private=draft-data", Host="operator.example.com", Accept="text/html"
        )
        assert code == HTTPStatus.SERVICE_UNAVAILABLE
        assert b"Temporarily unavailable" in body and b"draft-data" not in body


@pytest.mark.parametrize("arguments", [[], ["--health-only", "--binding", "/control/launch.json"]])
def test_normal_launch_cannot_fall_back_to_health_only_or_local(monkeypatch, arguments):
    monkeypatch.setattr(runtime, "inspect", Mock(return_value={}))
    http = MagicMock()
    monkeypatch.setattr(runtime, "HTTPServer", http)
    monkeypatch.setattr("sys.argv", ["operator", *arguments])
    with pytest.raises(SystemExit) as result:
        runtime.launch("operator")
    assert result.value.code == UNAVAILABLE_EXIT
    http.assert_not_called()


def test_normal_fixed_entry_serves_only_unavailable_after_private_validation(values, monkeypatch):
    binding = LaunchBinding(**values)
    load = Mock(return_value=binding)
    validate = Mock(side_effect=RuntimeError("private-store-path-and-identity"))
    http = MagicMock()
    monkeypatch.setattr(runtime, "inspect", Mock(return_value={}))
    monkeypatch.setattr(runtime, "load_binding", load)
    monkeypatch.setattr(runtime, "validate_startup", validate)
    monkeypatch.setattr(runtime, "HTTPServer", http)
    monkeypatch.setattr("sys.argv", ["operator", "--binding", "/control/launch.json"])
    runtime.launch("operator")
    load.assert_called_once_with(Path("/control/launch.json"), "operator")
    validate.assert_called_once_with(binding, runtime.application_root())
    assert http.call_args.args[1] is HostedStatusHandler
    assert http.return_value.__enter__.return_value.binding == binding


def test_health_only_never_opens_a_workspace_or_source_store(monkeypatch):
    load, validate = Mock(), Mock()
    monkeypatch.setattr(runtime, "inspect", Mock(return_value={}))
    monkeypatch.setattr(runtime, "load_binding", load)
    monkeypatch.setattr(runtime, "validate_startup", validate)
    monkeypatch.setattr(runtime, "HTTPServer", MagicMock())
    monkeypatch.setattr("sys.argv", ["operator", "--health-only"])
    runtime.launch("operator")
    load.assert_not_called()
    validate.assert_not_called()


def test_installed_candidate_probe_understands_the_safe_status_contract():
    probe = runpy.run_path(str(APPLICATION / "deploy/hosted-mvp/probe.py"))
    assert probe["health"]() == {
        "/health/live": 200,
        "/health/ready": 503,
        "/api/properties": 503,
        "/": 503,
    }
