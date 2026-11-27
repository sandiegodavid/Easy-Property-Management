"""Unit tests for the host-side Pilot 0 Operator verified backup runner."""

from __future__ import annotations

import json
import runpy
import sqlite3
from pathlib import Path

import pytest

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
RUNNER = runpy.run_path(str(GCP_DIR / "operator_backup_runner.py"))
EXPECTED_UID_A = 100001
EXPECTED_UID_B = 100002


def _create_recovery_db(
    path: Path,
    *,
    protection_state: str = "healthy",
    dirty_since: int | None = None,
    last_error_code: str | None = None,
    consecutive_failures: int = 0,
) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE backup_state ("
            "id INTEGER PRIMARY KEY, protection_state TEXT, dirty_since INTEGER, "
            "last_error_code TEXT, consecutive_failures INTEGER)"
        )
        conn.execute(
            "INSERT INTO backup_state VALUES (1, ?, ?, ?, ?)",
            (protection_state, dirty_since, last_error_code, consecutive_failures),
        )
        conn.commit()
    finally:
        conn.close()


def test_load_targets_joins_registry_with_active_principals(tmp_path: Path) -> None:
    reg = tmp_path / "registry.json"
    reg.write_text(
        json.dumps(
            {
                "operators": {
                    "op-b": {"workspace_slug": "wwjdf", "ip": "10.90.0.3"},
                    "op-a": {"workspace_slug": "demo-a", "ip": "10.90.0.2"},
                    "op-retired": {"workspace_slug": "old", "ip": "10.90.0.4"},
                }
            }
        ),
        encoding="utf-8",
    )
    inv = tmp_path / "inventory.sqlite"
    conn = sqlite3.connect(str(inv))
    try:
        conn.execute(
            "CREATE TABLE operator_principals "
            "(operator_id TEXT, host_uid INTEGER, retired_at INTEGER)"
        )
        conn.executemany(
            "INSERT INTO operator_principals VALUES (?, ?, ?)",
            [
                ("op-a", EXPECTED_UID_A, None),
                ("op-b", EXPECTED_UID_B, None),
                ("op-retired", 100003, 1795000000000),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    targets = RUNNER["load_targets"](reg, inv)
    assert [(t.operator_id, t.workspace_slug, t.host_uid) for t in targets] == [
        ("op-a", "demo-a", EXPECTED_UID_A),
        ("op-b", "wwjdf", EXPECTED_UID_B),
    ]
    filtered = RUNNER["load_targets"](reg, inv, slug_filter="demo-a")
    assert [t.operator_id for t in filtered] == ["op-a"]


@pytest.mark.parametrize(
    "row,expected",
    [
        (("healthy", None, None, 0), False),
        (("unchanged", None, None, 0), False),
        (("healthy", 1795740382645, None, 0), True),
        (("overdue", 1795740382645, "backup_proxy_unavailable", 5), True),
        (("unknown", None, None, 0), True),
        (("healthy", None, "backup_proxy_unavailable", 1), True),
    ],
)
def test_needs_backup_skips_clean_and_triggers_dirty_or_degraded(
    tmp_path: Path,
    row: tuple[str, int | None, str | None, int],
    expected: bool,
) -> None:
    state, dirty_since, error_code, failures = row
    db = tmp_path / "recovery.sqlite"
    _create_recovery_db(
        db,
        protection_state=state,
        dirty_since=dirty_since,
        last_error_code=error_code,
        consecutive_failures=failures,
    )
    due, _reason = RUNNER["needs_backup"](db)
    assert due is expected
    forced, forced_reason = RUNNER["needs_backup"](db, force=True)
    assert forced is True
    assert forced_reason == "forced"


def test_systemd_units_define_six_hour_timer_and_oneshot_service() -> None:
    units = RUNNER["systemd_units"]()
    assert set(units) == {"epm-operator-backup.service", "epm-operator-backup.timer"}
    assert "Type=oneshot" in units["epm-operator-backup.service"]
    assert "epm-backup-proxy.service" in units["epm-operator-backup.service"]
    assert "OnCalendar=*-*-* 02,08,14,20:00:00 UTC" in units["epm-operator-backup.timer"]
    assert "Persistent=true" in units["epm-operator-backup.timer"]
