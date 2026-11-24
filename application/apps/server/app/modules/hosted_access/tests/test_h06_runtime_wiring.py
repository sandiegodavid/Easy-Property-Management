"""H06.2 focused tests: live readiness, AdminControl/recovery fallback, backup_proxy CLI/unit, supervisor."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.modules.host_agent.application.build_inputs import PrincipalRange
from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyDenied,
    _resolve_cli_settings,
    build_cli_parser,
    load_r2_credentials,
)
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile
from app.modules.host_agent.infrastructure.host_services import TunnelSettings, service_unit
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings
from app.modules.host_agent.infrastructure.schema_store import HostMetadata, bind_host
from app.modules.host_agent.infrastructure.service_config import ServiceInputs, ServiceLayout
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.host_agent.infrastructure.supervisor import (
    _emit_containment_alert,
    build_supervision_agent,
)
from app.modules.hosted_access.infrastructure import admin_entry
from app.modules.hosted_access.infrastructure.shared_identity_entry import AdminWorkspaceReadiness
from app.modules.hosted_access.tests.test_identity_contracts import setup as load_identity_setup
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000620"
OPERATOR_ID = "00000000-0000-4000-8000-000000000621"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000622"


def _seed_admin_db_with_operator(
    db_path: Path, *, setup_state: str, desired_enabled: int, protection_state: str | None
) -> None:
    initialize_store(HostedStore.ADMIN, db_path, application_directory=APPLICATION)
    engine = create_sqlite_engine(db_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO control_meta (id, deployment_id, public_base_domain, login_origin, "
                    "registry_generation, created_at) VALUES "
                    "(1, :dep, 'epmdemo.xyz', 'https://login.epmdemo.xyz', 1, 1000)"
                ),
                {"dep": DEPLOYMENT_ID},
            )
            conn.execute(
                text(
                    "INSERT INTO storage_policies (policy_id, plan_code, policy_version, usable_bytes, "
                    "backup_interval_seconds, retained_nightly_points, keep_warm, created_at) VALUES "
                    "('00000000-0000-4000-8000-000000000629', 'free', 1, 50000000, 86400, 7, 1, 1000)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO operators ("
                    "operator_id, workspace_id, display_name, invited_email, email_key, "
                    "workspace_slug, issuer, subject, desired_policy_id, desired_access, "
                    "setup_state, support_contact, access_epoch, revision, created_at, updated_at"
                    ") VALUES ("
                    ":op, :ws, 'Pilot A', 'pilot@example.invalid', "
                    "'identity-epmdemo-v1:pilot@example.invalid', 'pilot-a', "
                    "'identity-epmdemo-v1', 'firebase-uid-1', '00000000-0000-4000-8000-000000000629', "
                    ":access, :state, 'owner@example.invalid', 2, 1, 1000, 1000)"
                ),
                {
                    "op": OPERATOR_ID,
                    "ws": WORKSPACE_ID,
                    "state": setup_state,
                    "access": "enabled" if desired_enabled else "disabled",
                },
            )
            if protection_state is not None:
                conn.execute(
                    text(
                        "INSERT INTO workspace_recovery_status ("
                        "operator_id, workspace_id, source_epoch, source_revision, "
                        "latest_point_ref, captured_at, verified_at, checked_at, observed_at, "
                        "dirty_since, protection_state, active_operation_ref, revision"
                        ") VALUES (:op, :ws, 2, 1, 'pt:1', 1000, 1000, 1000, 1000, NULL, "
                        ":pstate, NULL, 1)"
                    ),
                    {"op": OPERATOR_ID, "ws": WORKSPACE_ID, "pstate": protection_state},
                )
    finally:
        engine.dispose()


def test_admin_workspace_readiness_enforces_setup_epoch_and_verified_protection(tmp_path):
    db_path = tmp_path / "admin.sqlite"
    _seed_admin_db_with_operator(
        db_path, setup_state="active", desired_enabled=1, protection_state="healthy"
    )
    engine = create_sqlite_engine(db_path)
    try:
        readiness = AdminWorkspaceReadiness(engine)
        assert readiness.ready(OPERATOR_ID, 2) is True
        assert readiness.ready(OPERATOR_ID, 1) is False
        assert readiness.ready("00000000-0000-4000-8000-000000000999", 2) is False

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE workspace_recovery_status SET protection_state = 'unchanged' "
                    "WHERE operator_id = :op"
                ),
                {"op": OPERATOR_ID},
            )
        assert readiness.ready(OPERATOR_ID, 2) is True

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE workspace_recovery_status SET protection_state = 'overdue' "
                    "WHERE operator_id = :op"
                ),
                {"op": OPERATOR_ID},
            )
        assert readiness.ready(OPERATOR_ID, 2) is False

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE workspace_recovery_status SET protection_state = 'healthy' "
                    "WHERE operator_id = :op"
                ),
                {"op": OPERATOR_ID},
            )
            conn.execute(
                text("UPDATE operators SET desired_access = 'disabled' WHERE operator_id = :op"),
                {"op": OPERATOR_ID},
            )
        assert readiness.ready(OPERATOR_ID, 2) is False
    finally:
        engine.dispose()


def _make_admin_deployment(tmp_path: Path, *, corrupt_admin_db: bool) -> tuple[Path, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    private = tmp_path.resolve()
    private.chmod(0o700)

    def write(name: str, content: str) -> Path:
        path = private / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        return path

    selected = load_identity_setup()
    provider = {
        "version": 1,
        "realm": selected.realm.model_dump(),
        "origins": selected.origins.model_dump(),
        "api_key": "synthetic-provider-api-key",
        "google_enabled": True,
        "email_link_enabled": True,
        "totp_enabled": True,
        "provider_email_sends_per_day": selected.provider_sends_per_day,
    }
    raw = json.dumps(provider)
    provider_path = write("provider.json", raw)
    selected = selected.model_copy(
        update={
            "configuration_state": "verified",
            "provider_config_sha256": sha256(raw.encode()).hexdigest(),
        }
    )

    admin_db = private / "admin.sqlite"
    if corrupt_admin_db:
        admin_db.write_bytes(b"corrupted-not-sqlite")
    else:
        initialize_store(HostedStore.ADMIN, admin_db, application_directory=APPLICATION)
    admin_db.chmod(0o600)

    admin_rec_db = private / "admin-recovery.sqlite"
    initialize_store(HostedStore.ADMIN_RECOVERY, admin_rec_db, application_directory=APPLICATION)
    admin_rec_db.chmod(0o600)

    authority_path = write(
        "admin-recovery-authority.json",
        json.dumps(
            {
                "version": 1,
                "deployment_id": DEPLOYMENT_ID,
                "principals": [
                    {
                        "issuer": selected.realm.alias,
                        "subject": "admin-uid-1",
                        "principal_ref": "admin:primary",
                        "mfa_required": True,
                    }
                ],
            }
        ),
    )
    control_root = private / "control"
    scratch_root = private / "scratch"
    control_root.mkdir(mode=0o700)
    scratch_root.mkdir(mode=0o700)

    config = {
        "database": str(admin_db),
        "writer_lock": str(write("writer.lock", "")),
        "setup": str(write("setup.json", selected.model_dump_json())),
        "provider_configuration": str(provider_path),
        "bearer_file": str(write("bearer", "synthetic-bearer")),
        "mail_key_file": str(write("mail-key", "x" * 32)),
        "deployment_id": DEPLOYMENT_ID,
        "application_directory": str(APPLICATION),
        "support_contact": "owner@example.invalid",
        "admin_recovery_database": str(admin_rec_db),
        "bootstrap_authority": str(authority_path),
        "control_root": str(control_root),
        "scratch_root": str(scratch_root),
        "backup_proxy_socket": str(private / "backup-proxy.sock"),
        "backup_proxy_uid": 955,
    }
    cfg_path = write("deployment.json", json.dumps(config))
    return cfg_path, selected


def test_admin_entry_mounts_admin_control_and_falls_back_to_recovery_mode(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>Admin</title>", encoding="utf-8")

    # Normal mode mounts Admin-lite (/api/admin/operators) and Admin recovery (/api/admin/recovery/status).
    normal_cfg, selected = _make_admin_deployment(tmp_path / "normal", corrupt_admin_db=False)
    deployment, setup = admin_entry.load_deployment(normal_cfg)
    bundle = admin_entry.build_admin_runtime(deployment, setup, ui_directory=ui)
    try:
        assert bundle.recovery_mode is False
        assert bundle.engine is not None
        assert bundle.admin_recovery_engine is not None
        with TestClient(bundle.app, base_url=selected.origins.admin) as client:
            assert client.get("/api/admin/operators").status_code == 401
            assert client.get("/api/admin/recovery/status").status_code == 401
    finally:
        if bundle.admin_recovery_engine is not None:
            bundle.admin_recovery_engine.dispose()
        if bundle.engine is not None:
            bundle.engine.dispose()

    # Corrupt admin.sqlite falls back cleanly to standalone D5 Admin recovery app.
    corrupt_cfg, selected = _make_admin_deployment(tmp_path / "corrupt", corrupt_admin_db=True)
    deployment, setup = admin_entry.load_deployment(corrupt_cfg)
    rec_bundle = admin_entry.build_admin_runtime(deployment, setup, ui_directory=ui)
    try:
        assert rec_bundle.recovery_mode is True
        assert rec_bundle.engine is None
        assert rec_bundle.admin_recovery_engine is not None
        with TestClient(rec_bundle.app, base_url=selected.origins.admin) as client:
            assert client.get("/api/admin/recovery/status").status_code == 401
            assert client.get("/api/admin/operators").status_code == 404
    finally:
        if rec_bundle.admin_recovery_engine is not None:
            rec_bundle.admin_recovery_engine.dispose()


def test_backup_proxy_cli_credentials_and_systemd_unit(tmp_path, monkeypatch):
    creds_path = tmp_path / "r2.json"
    creds_path.write_text(
        json.dumps(
            {
                "endpoint_url": "https://" + "a" * 32 + ".r2.cloudflarestorage.com",
                "bucket": "epm-hosted-recovery",
                "access_key_id": "AKIA_TEST",
                "secret_access_key": "SECRET_TEST",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_r2_credentials(creds_path)
    assert loaded["bucket"] == "epm-hosted-recovery"

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({"bucket": "only-one-key"}), encoding="utf-8")
    with pytest.raises(BackupProxyDenied):
        load_r2_credentials(bad_path)

    cfg_path = tmp_path / "backup-proxy.json"
    cfg_path.write_text(
        json.dumps(
            {
                "socket": "/run/epm-backup-proxy/backup-proxy.sock",
                "inventory": "/srv/epm/data/host/inventory/inventory.sqlite",
                "deployment_id": DEPLOYMENT_ID,
                "admin_uid": 959,
                "operator_key_refs": [
                    "projects/p/locations/us-west1/keyRings/r/cryptoKeys/operator-workspace-kek"
                ],
                "control_key_refs": [
                    "projects/p/locations/us-west1/keyRings/r/cryptoKeys/admin-control-kek"
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    parsed = build_cli_parser().parse_args(["--config", str(cfg_path)])
    settings = _resolve_cli_settings(parsed)
    assert settings["credentials_file"] == tmp_path / "r2.json"
    assert settings["admin_uid"] == 959

    unit = service_unit("backup_proxy")
    assert "User=epm-backup-proxy" in unit
    assert "LoadCredential=r2.json:/etc/epm/secrets/r2.json" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ProtectSystem=strict" in unit
    assert "/run/docker.sock" in unit
    assert "epm-ingress-projection.service" not in unit


def test_supervisor_builds_production_host_agent_and_emits_structured_alert(tmp_path, capsys):
    root = tmp_path.resolve()
    root.chmod(0o700)
    inv_dir = root / "inventory"
    inv_dir.mkdir(mode=0o700)
    inv_path = inv_dir / "inventory.sqlite"
    initialize_store(HostedStore.HOST_INVENTORY, inv_path, application_directory=APPLICATION)
    meta = HostMetadata(
        host_id=str(uuid4()),
        deployment_id=DEPLOYMENT_ID,
        filesystem_identity="gcp-data:8d2fd2e0-274b-4535-90d5-da78aa6bd9b6",
        agent_contract_version="host-agent-v1",
        created_at=1000,
    )
    inv_engine = create_sqlite_engine(inv_path)
    try:
        with inv_engine.begin() as conn:
            bind_host(conn, meta, application_directory=APPLICATION)
    finally:
        inv_engine.dispose()

    stops_dir = root / "stops"
    stops_dir.mkdir(mode=0o700)
    data_dir = root / "data"
    data_dir.mkdir(mode=0o700)
    app_dir = root / "app"
    db_dir = app_dir / "database"
    db_dir.mkdir(parents=True)
    shutil.copytree(
        APPLICATION / "database" / "host-inventory-migrations",
        db_dir / "host-inventory-migrations",
    )
    shutil.copyfile(APPLICATION / "database" / "hosted_ddl.py", db_dir / "hosted_ddl.py")
    layout = ServiceLayout(
        inventory=str(inv_path),
        application=str(app_dir),
        stops=str(stops_dir),
        data=str(data_dir),
        gateway_runtime=str(root / "caddy"),
        gateway_projection=str(root / "proj-caddy"),
        proxy_runtime=str(root / "proxy"),
        proxy_projection=str(root / "proj-proxy"),
        tunnel_runtime=str(root / "tunnel"),
        tunnel_projection=str(root / "proj-tunnel"),
        tunnel_secret=str(root / "tunnel.json"),
        config=str(root / "host-services.json"),
    )
    inputs = ServiceInputs(
        layout=layout,
        metadata=meta,
        uids=PrincipalRange(first=100000, last=165535),
        gids=PrincipalRange(first=100000, last=165535),
        projects=PrincipalRange(first=1001, last=65535),
        public_domain="epmdemo.xyz",
        network=NetworkSettings("10.246.0.0/16", "fd47:6570:7000::/48", 1001, 951, 952, 953),
        tunnel=TunnelSettings(tunnel_id=str(uuid4())),
    )
    cfg_path = root / "host-services.json"
    cfg_path.write_text(inputs.model_dump_json(), encoding="utf-8")
    cfg_path.chmod(0o600)

    with pytest.raises(ValueError, match="--profile"):
        build_supervision_agent(
            cfg_path,
            registry=StopRegistry(stops_dir),
            engine=object(),
            owner=os.getuid(),
        )

    profile_path = root / "runtime-profile.json"
    profile_path.write_text(
        RuntimeProfile(
            architecture="amd64",
            apparmor_sha256="a" * 64,
            memory_bytes=512 * 1024 * 1024,
            cpu_millicores=1000,
            pids=128,
            file_descriptors=1024,
            log_bytes=8 * 1024 * 1024,
            log_files=3,
        ).model_dump_json(),
        encoding="utf-8",
    )
    profile_path.chmod(0o600)

    agent = build_supervision_agent(
        cfg_path,
        registry=StopRegistry(stops_dir),
        engine=object(),
        profile_path=profile_path,
        owner=os.getuid(),
    )
    assert agent.inventory is not None
    assert agent.driver is not None
    assert agent.driver.networks is not None

    line = _emit_containment_alert()
    payload = json.loads(line)
    assert payload["event"] == "runtime_containment_attention"
    assert payload["component"] == "epm-host-guardian"
    assert payload["severity"] == "CRITICAL"
