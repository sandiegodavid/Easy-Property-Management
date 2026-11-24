"""H06.3 focused tests: nightly schedulers (D6), summary relay (D7), alerting (D3), maintenance (D5)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from sqlalchemy import text

from app.modules.hosted_access.infrastructure.maintenance_notice import (
    is_maintenance_in_progress,
    read_maintenance_notice,
)
from app.modules.hosted_admin.infrastructure.recovery_status_ingest import (
    INTERNAL_RECOVERY_STATUS_ROUTE,
    RecoveryStatusIngestService,
    UnixSummaryPublisher,
    WorkspaceProtectionSummary,
    handle_recovery_status_connection,
    sign_protection_summary,
)
from app.modules.hosted_recovery.infrastructure.alerting import build_alert_emitter
from app.modules.hosted_recovery.infrastructure.scheduler import (
    AdminControlBackupScheduler,
    NIGHTLY_INTERVAL_MS,
    WorkspaceBackupScheduler,
    deterministic_nightly_jitter_seconds,
)
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000630"
OPERATOR_ID = "00000000-0000-4000-8000-000000000631"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000632"
NOW_MS = 1_760_000_000_000


def test_maintenance_notice_reader_handles_missing_inactive_malformed_and_active(tmp_path):
    missing = tmp_path / "maintenance-notice.json"
    sec = read_maintenance_notice(missing, clock=lambda: NOW_MS)
    assert sec.state == "unavailable"
    assert sec.freshness is not None
    assert sec.freshness.error_code == "no_announced_maintenance"
    assert is_maintenance_in_progress(missing) is False

    missing.write_text(json.dumps({"active": False}), encoding="utf-8")
    sec = read_maintenance_notice(missing, clock=lambda: NOW_MS)
    assert sec.state == "unavailable"
    assert sec.freshness.error_code == "no_announced_maintenance"

    missing.write_text("{not-json", encoding="utf-8")
    sec = read_maintenance_notice(missing, clock=lambda: NOW_MS)
    assert sec.state == "unavailable"
    assert sec.freshness.error_code == "maintenance_notice_unavailable"

    missing.write_text(
        json.dumps(
            {
                "active": True,
                "window_start_utc": NOW_MS + 60_000,
                "window_end_utc": NOW_MS + 660_000,
                "message": "Scheduled Pilot 0 maintenance window.",
                "state": "announced",
            }
        ),
        encoding="utf-8",
    )
    sec = read_maintenance_notice(missing, clock=lambda: NOW_MS)
    assert sec.state == "ready"
    assert sec.data is not None
    assert sec.data.message == "Scheduled Pilot 0 maintenance window."
    assert sec.freshness is not None
    assert sec.freshness.source_revision == f"maintenance:announced:{NOW_MS + 60_000}"
    assert is_maintenance_in_progress(missing, clock=lambda: NOW_MS) is False

    missing.write_text(
        json.dumps(
            {
                "active": True,
                "window_start_utc": NOW_MS,
                "window_end_utc": NOW_MS + 600_000,
                "message": "Updating your workspace.",
                "state": "in_progress",
            }
        ),
        encoding="utf-8",
    )
    assert is_maintenance_in_progress(missing, clock=lambda: NOW_MS) is True
    assert is_maintenance_in_progress(missing, clock=lambda: NOW_MS + 600_000) is False


def test_build_alert_emitter_validates_webhook_url():
    log_only = build_alert_emitter()
    assert len(log_only._sinks) == 1

    with_hook = build_alert_emitter(webhook_url="https://alerts.example.com/epm")
    assert len(with_hook._sinks) == 2

    with pytest.raises(ValueError, match="HTTPS"):
        build_alert_emitter(webhook_url="http://alerts.example.com/epm")
    with pytest.raises(ValueError, match="private"):
        build_alert_emitter(webhook_url="https://127.0.0.1/hook")


def _send_relay_request(
    ingest: RecoveryStatusIngestService,
    raw_request: bytes,
    *,
    allowed_uid: int,
) -> tuple[int, dict]:
    srv_sock, cli_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    t = threading.Thread(
        target=handle_recovery_status_connection,
        args=(srv_sock, ingest),
        kwargs={"allowed_uid": allowed_uid},
    )
    t.start()
    try:
        cli_sock.sendall(raw_request)
        resp = cli_sock.recv(8192).decode("utf-8")
    finally:
        cli_sock.close()
        t.join(timeout=5.0)
        srv_sock.close()
    head, _, body = resp.partition("\r\n\r\n")
    status_code = int(head.split(" ", 2)[1])
    return status_code, json.loads(body)


def test_recovery_status_relay_authenticates_peer_uid_and_ed25519(tmp_path):
    admin_db = tmp_path / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, admin_db, application_directory=APPLICATION)
    engine = create_sqlite_engine(admin_db)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
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
                    "('00000000-0000-4000-8000-000000000639', 'free', 1, 50000000, 86400, 7, 1, 1000)"
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
                    "'identity-epmdemo-v1', 'uid-1', '00000000-0000-4000-8000-000000000639', "
                    "'enabled', 'active', 'owner@example.invalid', 1, 1, 1000, 1000)"
                ),
                {"op": OPERATOR_ID, "ws": WORKSPACE_ID},
            )

        ingest = RecoveryStatusIngestService(
            engine,
            resolve_public_key=lambda op, ws, kid: (
                pub if (op, ws, kid) == (OPERATOR_ID, WORKSPACE_ID, "op-key-1") else None
            ),
            clock=lambda: NOW_MS,
        )
        summary = WorkspaceProtectionSummary(
            operator_id=OPERATOR_ID,
            workspace_id=WORKSPACE_ID,
            source_epoch=1,
            source_revision=3,
            latest_point_ref="pt:1",
            captured_at=NOW_MS - 10_000,
            verified_at=NOW_MS - 5_000,
            checked_at=NOW_MS,
            protection_state="healthy",
            key_id="op-key-1",
            issued_at=NOW_MS - 1000,
            expires_at=NOW_MS + 60_000,
        )
        token = sign_protection_summary(summary, private_key=priv)
        body = json.dumps({"token": token}).encode("utf-8")
        req = (
            f"POST {INTERNAL_RECOVERY_STATUS_ROUTE} HTTP/1.1\r\nContent-Length: {len(body)}\r\n\r\n"
        ).encode("ascii") + body

        # Valid SO_PEERCRED UID + Ed25519 inserts row.
        status, payload = _send_relay_request(ingest, req, allowed_uid=os.getuid())
        assert status == 200
        assert payload["applied"] is True
        assert payload["reason"] == "inserted"

        # Duplicate replay is idempotent (stale_revision).
        status2, payload2 = _send_relay_request(ingest, req, allowed_uid=os.getuid())
        assert status2 == 200
        assert payload2["applied"] is False
        assert payload2["reason"] == "stale_revision"

        # Wrong peer UID denied with 403.
        status3, payload3 = _send_relay_request(ingest, req, allowed_uid=os.getuid() + 1)
        assert status3 == 403
        assert payload3["code"] == "peer_uid_denied"

        # Forged signature denied with 403.
        forged_body = json.dumps({"token": token[:-4] + "AAAA"}).encode("utf-8")
        forged_req = (
            f"POST {INTERNAL_RECOVERY_STATUS_ROUTE} HTTP/1.1\r\n"
            f"Content-Length: {len(forged_body)}\r\n\r\n"
        ).encode("ascii") + forged_body
        status4, payload4 = _send_relay_request(ingest, forged_req, allowed_uid=os.getuid())
        assert status4 == 403
        assert payload4["code"] == "recovery_summary_denied"

        # Best-effort publisher never raises when socket is missing.
        publisher = UnixSummaryPublisher(tmp_path / "missing.sock", expected_peer_uid=os.getuid())
        publisher(token)
    finally:
        engine.dispose()


def test_nightly_schedulers_trigger_capture_only_when_due(tmp_path):
    assert 0 <= deterministic_nightly_jitter_seconds(WORKSPACE_ID, window_seconds=3600) < 3600
    assert deterministic_nightly_jitter_seconds(
        WORKSPACE_ID
    ) == deterministic_nightly_jitter_seconds(WORKSPACE_ID)

    calls: list[object] = []
    now = [NOW_MS]
    snap = SimpleNamespace(last_verified_at=None, revision=1)
    fake_ws = SimpleNamespace(
        evaluate_freshness=lambda: snap,
        execute=lambda actor, cmd: calls.append((actor, cmd)),
    )
    ws_sched = WorkspaceBackupScheduler(
        fake_ws,
        deployment_id=DEPLOYMENT_ID,
        operator_id=OPERATOR_ID,
        workspace_id=WORKSPACE_ID,
        clock=lambda: now[0],
        jitter_window_seconds=0,
    )
    assert ws_sched.run_once() is True
    assert len(calls) == 1

    # Recent verified point skips capture.
    snap.last_verified_at = now[0]
    assert ws_sched.run_once() is False
    assert len(calls) == 1

    # Advancing 24h triggers next nightly capture.
    now[0] += NIGHTLY_INTERVAL_MS
    assert ws_sched.run_once() is True
    assert len(calls) == 2

    # Admin control backup scheduler against real initialized admin-recovery.sqlite.
    admin_rec_db = tmp_path / "admin-recovery.sqlite"
    initialize_store(HostedStore.ADMIN_RECOVERY, admin_rec_db, application_directory=APPLICATION)
    rec_engine = create_sqlite_engine(admin_rec_db)
    admin_calls: list[object] = []
    try:
        fake_admin_rec = SimpleNamespace(
            admin_recovery_engine=rec_engine,
            execute=lambda actor, cmd: admin_calls.append((actor, cmd)),
        )
        admin_sched = AdminControlBackupScheduler(
            fake_admin_rec,
            deployment_id=DEPLOYMENT_ID,
            clock=lambda: now[0],
            jitter_window_seconds=0,
        )
        assert admin_sched.run_once() is True
        assert len(admin_calls) == 1
    finally:
        rec_engine.dispose()
