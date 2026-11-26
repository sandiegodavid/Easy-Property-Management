"""Tests for Pilot 0 release cleanup wizard and Python classification helper."""

from __future__ import annotations

from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pilot0_release_cleanup as cleanup  # noqa: E402

WIZARD = SCRIPTS / "epm-pilot0-release-cleanup.sh"
ROLLOUT_WIZARD = SCRIPTS / "epm-pilot0-rollout.sh"


def wizard_functions() -> str:
    return WIZARD.read_text(encoding="utf-8").rsplit('\nmain "$@"', 1)[0]


def run_shell(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", wizard_functions() + "\n" + body],
        capture_output=True,
        text=True,
        check=False,
    )


def test_syntax_help_library_match_and_noninteractive_guard() -> None:
    subprocess.run(["bash", "-n", str(WIZARD)], check=True)

    # Shared wizard library above STAGES marker must stay identical to existing wizards.
    assert (
        WIZARD.read_text(encoding="utf-8").split("# STAGES:")[0]
        == ROLLOUT_WIZARD.read_text(encoding="utf-8").split("# STAGES:")[0]
    )

    for flag in ("--help", "-h"):
        res = subprocess.run(
            ["bash", str(WIZARD), flag], capture_output=True, text=True, check=False
        )
        assert res.returncode == 0
        assert "Usage:" in res.stdout
        assert "cleanup" in res.stdout
        assert "inspect" in res.stdout

    non_tty = subprocess.run(["bash", str(WIZARD)], capture_output=True, text=True, check=False)
    assert non_tty.returncode != 0
    assert "Stopped:" in non_tty.stderr

    too_many = subprocess.run(
        ["bash", str(WIZARD), "cleanup", "extra"], capture_output=True, text=True, check=False
    )
    assert too_many.returncode != 0
    assert "Too many arguments" in too_many.stderr


@pytest.mark.parametrize(
    "value,ok",
    [
        ("epm-pilot0-operator:pilot0-20261126-canary", True),
        ("sha256:" + "a" * 64, True),
        ("bbbbc05c88fc", True),
        ("", False),
        ("has space", False),
        ("bad;rm -rf /", False),
        ("line1\nline2", False),
    ],
)
def test_valid_image_ref(value: str, ok: bool) -> None:
    res = run_shell(f"valid_image_ref {shlex.quote(value)}")
    assert (res.returncode == 0) is ok


@pytest.mark.parametrize(
    "value,ok",
    [
        ("epm-op-demo-a-before-draft-void-fix", True),
        ("nervous_noyce", True),
        ("bad;id", False),
        ("../escape", False),
    ],
)
def test_valid_container_and_opt_dir_names(value: str, ok: bool) -> None:
    assert (run_shell(f"valid_container_name {shlex.quote(value)}").returncode == 0) is ok
    assert (run_shell(f"valid_opt_dir_name {shlex.quote(value)}").returncode == 0) is ok


def test_parse_space_list_is_bash32_compatible_and_does_not_glob(tmp_path: Path) -> None:
    (tmp_path / "should-not-match").write_text("x", encoding="utf-8")
    res = run_shell(
        f"cd {shlex.quote(str(tmp_path))} && parse_space_list 'alpha beta' && "
        'printf "%s\\n" "${PARSED_ITEMS[@]}"'
    )
    assert res.returncode == 0
    assert res.stdout.splitlines() == ["alpha", "beta"]


def test_classify_images_protects_live_manifest_catalog_python_keep_and_stopped() -> None:
    live_op_id = "sha256:" + "1" * 64
    admin_id = "sha256:" + "2" * 64
    catalog_id = "sha256:" + "3" * 64
    python_id = "sha256:" + "4" * 64
    rollback_id = "sha256:" + "5" * 64
    stopped_pinned_id = "sha256:" + "6" * 64
    old_unused_id = "sha256:" + "7" * 64

    images = [
        cleanup.ImageRecord(
            live_op_id, "epm-pilot0-operator", "pilot0-20261126-canary", "290MB", "today"
        ),
        cleanup.ImageRecord(
            admin_id, "epm-pilot0-admin", "pilot0-20261125-si", "285MB", "yesterday"
        ),
        cleanup.ImageRecord(
            catalog_id, "epm-pilot0-operator", "pilot0-20261125-tasks", "290MB", "yesterday"
        ),
        cleanup.ImageRecord(python_id, "python", "<none>", "183MB", "2 weeks ago"),
        cleanup.ImageRecord(
            rollback_id, "epm-pilot0-operator", "pilot0-20261125-ui", "290MB", "2 days ago"
        ),
        cleanup.ImageRecord(stopped_pinned_id, "epm-h02-capacity", "old", "288MB", "12 days ago"),
        cleanup.ImageRecord(old_unused_id, "epm-h04-sizing", "old", "298MB", "3 days ago"),
    ]
    containers = [
        cleanup.ContainerRecord(
            "c1",
            "epm-op-demo-a",
            live_op_id,
            "epm-pilot0-operator:pilot0-20261126-canary",
            "Up 2h",
            True,
        ),
        cleanup.ContainerRecord(
            "c2",
            "epm-old-stopped",
            stopped_pinned_id,
            "epm-h02-capacity:old",
            "Exited (0)",
            False,
        ),
    ]

    classified = cleanup.classify_images(
        images,
        containers,
        cleanup.ImageProtectionContext(
            admin_manifest_digest=admin_id,
            catalog_latest_digests=(catalog_id,),
            keep_refs=("epm-pilot0-operator:pilot0-20261125-ui",),
        ),
    )
    by_id = {ci.record.image_id: ci for ci in classified}

    assert by_id[live_op_id].protected
    assert any("running container: epm-op-demo-a" in r for r in by_id[live_op_id].reasons)

    assert by_id[admin_id].protected
    assert any("MANIFEST" in r for r in by_id[admin_id].reasons)

    assert by_id[catalog_id].protected
    assert any("qualified_releases" in r for r in by_id[catalog_id].reasons)

    assert by_id[python_id].protected
    assert any("offline build base image" in r for r in by_id[python_id].reasons)

    assert by_id[rollback_id].protected
    assert any("explicit rollback retention" in r for r in by_id[rollback_id].reasons)

    assert by_id[stopped_pinned_id].protected
    assert any("stopped container: epm-old-stopped" in r for r in by_id[stopped_pinned_id].reasons)

    assert not by_id[old_unused_id].protected
    assert by_id[old_unused_id].record.remove_target == "epm-h04-sizing:old"


def test_classify_images_rejects_unknown_keep_ref() -> None:
    img = cleanup.ImageRecord("sha256:" + "a" * 64, "epm-pilot0-operator", "tag1", "290MB", "today")
    with pytest.raises(ValueError, match="Retained rollback image not found"):
        cleanup.classify_images(
            [img],
            [],
            cleanup.ImageProtectionContext(keep_refs=("epm-pilot0-operator:does-not-exist",)),
        )


def test_classify_opt_dirs_protects_core_systemd_symlink_and_process_refs(tmp_path: Path) -> None:
    opt = tmp_path / "opt-epm"
    opt.mkdir()
    for name in (
        "python",
        "agent-bundle",
        "host-agent-active",
        "systemd-referenced",
        "proc-referenced",
        "qual-source-1",
    ):
        (opt / name).mkdir()
    (opt / "host-agent").symlink_to(opt / "host-agent-active")

    ref_root = tmp_path / "systemd"
    ref_root.mkdir()
    (ref_root / "epm-demo.service").write_text(
        f"ExecStart={opt}/systemd-referenced/bin/run\n", encoding="utf-8"
    )

    processes = [(Path("/proc/1234/cmdline"), f"{opt}/proc-referenced/bin/python".encode())]
    classified = cleanup.classify_opt_dirs(
        opt,
        [ref_root],
        processes,
        sizes={"qual-source-1": "6.5M"},
    )
    by_name = {d.name: d for d in classified}

    assert by_name["python"].protected
    assert by_name["agent-bundle"].protected
    assert by_name["host-agent"].protected
    assert by_name["host-agent-active"].protected
    assert by_name["systemd-referenced"].protected
    assert by_name["proc-referenced"].protected

    assert not by_name["qual-source-1"].protected
    assert by_name["qual-source-1"].size == "6.5M"


def test_read_admin_manifest_and_catalog_digests(tmp_path: Path) -> None:
    hex_manifest = "ab" * 32
    run_id = tmp_path / "run_identity.py"
    run_id.write_text(f'MANIFEST = "{hex_manifest}"\n', encoding="utf-8")
    assert cleanup.read_admin_manifest(run_id) == f"sha256:{hex_manifest}"

    db_path = tmp_path / "admin.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE qualified_releases (release_id TEXT, image_digest TEXT, created_at TEXT)"
    )
    conn.execute("CREATE TABLE operators (operator_id TEXT, current_release_id TEXT)")
    old_digest = "sha256:" + "1" * 64
    latest_digest = "sha256:" + "2" * 64
    conn.execute(
        "INSERT INTO qualified_releases VALUES (?, ?, ?)",
        ("rel-1", old_digest, "2026-11-24T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO qualified_releases VALUES (?, ?, ?)",
        ("rel-2", latest_digest, "2026-11-25T00:00:00Z"),
    )
    conn.execute("INSERT INTO operators VALUES (?, ?)", ("op-1", "rel-1"))
    conn.commit()
    conn.close()

    latest, referenced = cleanup.read_catalog_digests(db_path)
    assert latest == {latest_digest}
    assert referenced == {old_digest}


def test_list_tmp_build_artifacts_only_matches_epm_staging(tmp_path: Path) -> None:
    (tmp_path / "epm-contexts.tar.gz").write_bytes(b"tar")
    (tmp_path / "build").mkdir()
    (tmp_path / "epm-inspector-build.abc").mkdir()
    (tmp_path / "systemd-private-12345").mkdir()
    (tmp_path / "other-file.txt").write_text("keep", encoding="utf-8")

    found = [p.name for p in cleanup.list_tmp_build_artifacts(tmp_path)]
    assert found == ["build", "epm-contexts.tar.gz", "epm-inspector-build.abc"]
