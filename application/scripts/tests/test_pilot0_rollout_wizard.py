"""Exercise Pilot 0 GCP rollout wizard guards without running cloud, build, or Docker commands."""

from __future__ import annotations

import io
import json
import shlex
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
WIZARD = SCRIPTS / "epm-pilot0-rollout.sh"
MAC_WIZARD = SCRIPTS / "epm-release-mac.sh"

SAMPLE_OP_HEX = "a" * 64
SAMPLE_ADMIN_HEX = "b" * 64
SAMPLE_OP_ID = f"sha256:{SAMPLE_OP_HEX}"
SAMPLE_ADMIN_ID = f"sha256:{SAMPLE_ADMIN_HEX}"
PRIVATE_FILE_MODE = 0o600


def wizard_functions() -> str:
    return WIZARD.read_text(encoding="utf-8").rsplit('\nmain "$@"', 1)[0]


def run_shell(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", wizard_functions() + "\n" + body],
        capture_output=True,
        text=True,
        check=False,
    )


def make_contexts_archive(
    path: Path,
    extra: dict[str, bytes] | None = None,
    omit: set[str] | None = None,
) -> None:
    omit = omit or set()
    entries: dict[str, bytes] = {
        "operator/Dockerfile": b"FROM scratch\n",
        "operator/dependencies.lock": b"lock\n",
        "operator/resources/hosted-candidate.json": b"{}\n",
        "admin/Dockerfile": b"FROM scratch\n",
        "admin/dependencies.lock": b"lock\n",
        "admin/resources/hosted-candidate.json": b"{}\n",
    }
    for key in omit:
        entries.pop(key, None)
    if extra:
        entries.update(extra)
    with tarfile.open(path, "w:gz") as archive:
        for name, data in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def test_syntax_help_and_noninteractive_guard() -> None:
    subprocess.run(["bash", "-n", str(WIZARD)], check=True)
    for flag in ("--help", "-h"):
        help_res = subprocess.run(
            ["bash", str(WIZARD), flag], capture_output=True, text=True, check=False
        )
        assert help_res.returncode == 0
        assert "Usage:" in help_res.stdout
        assert "rollout" in help_res.stdout
        assert "rollback" in help_res.stdout

    non_interactive = subprocess.run(
        ["bash", str(WIZARD)], capture_output=True, text=True, check=False
    )
    assert non_interactive.returncode != 0
    assert "Stopped:" in non_interactive.stderr

    too_many = subprocess.run(
        ["bash", str(WIZARD), "rollout", "extra"], capture_output=True, text=True, check=False
    )
    assert too_many.returncode != 0
    assert "Too many arguments" in too_many.stderr


def test_wizard_library_matches_existing_wizards() -> None:
    pilot0_lib = WIZARD.read_text(encoding="utf-8").split("# STAGES:")[0]
    mac_lib = MAC_WIZARD.read_text(encoding="utf-8").split("# STAGES:")[0]
    assert pilot0_lib == mac_lib


@pytest.mark.parametrize(
    "tag",
    ["pilot0-20261126-ui", "pilot0-20261125-tasks", "pilot0-20261126-v1.2_rc1"],
)
def test_valid_release_tags_accepted(tag: str) -> None:
    assert run_shell(f"valid_release_tag {shlex.quote(tag)}").returncode == 0


@pytest.mark.parametrize(
    "tag",
    [
        "release-20261126-01",
        "pilot0-2026112-ui",
        "PILOT0-20261126-ui",
        "pilot0-20261126-",
        "pilot0-20261126-ui;touch /tmp/bad",
        "../pilot0-20261126-ui",
    ],
)
def test_invalid_release_tags_rejected(tag: str) -> None:
    assert run_shell(f"valid_release_tag {shlex.quote(tag)}").returncode != 0


@pytest.mark.parametrize(
    "slug_list,expected_ok",
    [
        ("ALL", True),
        ("demo-a", True),
        ("demo-a,demo-c,wwjdf", True),
        ("", False),
        ("demo-a,../bad", False),
        ("demo-a,bad slug", False),
    ],
)
def test_slug_list_validation(slug_list: str, expected_ok: bool) -> None:
    res = run_shell(f"valid_slug_list {shlex.quote(slug_list)}")
    assert (res.returncode == 0) == expected_ok


@pytest.mark.parametrize(
    "path,expected_ok",
    [
        ("/private/tmp/epm-build", True),
        ("/private/tmp/epm-contexts.tar.gz", True),
        ("/tmp/epm-build", False),
        ("/tmp", False),
        ("", False),
    ],
)
def test_macos_private_tmp_guard(path: str, expected_ok: bool) -> None:
    res = run_shell(f"require_private_tmp_path {shlex.quote(path)}")
    assert (res.returncode == 0) == expected_ok


def test_verify_contexts_archive_accepts_clean_archive(tmp_path: Path) -> None:
    archive = tmp_path / "epm-contexts.tar.gz"
    make_contexts_archive(archive)
    res = run_shell(
        f"python_path={shlex.quote(sys.executable)}\n"
        f"verify_contexts_archive {shlex.quote(str(archive))}"
    )
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize(
    "extra,omit",
    [
        ({"operator/._Dockerfile": b"appledouble"}, set()),
        ({"admin/.DS_Store": b"finder"}, set()),
        ({"operator/__pycache__/x.pyc": b"pyc"}, set()),
        ({"../escape": b"bad"}, set()),
        ({}, {"admin/Dockerfile"}),
        ({}, {"operator/resources/hosted-candidate.json"}),
    ],
)
def test_verify_contexts_archive_rejects_bad_or_incomplete_tarballs(
    tmp_path: Path, extra: dict[str, bytes], omit: set[str]
) -> None:
    archive = tmp_path / "epm-contexts.tar.gz"
    make_contexts_archive(archive, extra=extra, omit=omit)
    res = run_shell(
        f"python_path={shlex.quote(sys.executable)}\n"
        f"verify_contexts_archive {shlex.quote(str(archive))}"
    )
    assert res.returncode != 0


def test_verify_contexts_archive_rejects_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "epm-contexts.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        link = tarfile.TarInfo("operator/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    res = run_shell(
        f"python_path={shlex.quote(sys.executable)}\n"
        f"verify_contexts_archive {shlex.quote(str(archive))}"
    )
    assert res.returncode != 0


def test_vm_ssh_and_scp_always_tunnel_through_iap() -> None:
    res = run_shell(
        "EPM_PROJECT=proj-1\nEPM_ZONE=us-west1-b\nEPM_INSTANCE=epm-h02-host\n"
        'gcloud() { printf "GCLOUD:%s\\n" "$*"; }\n'
        "vm_ssh --command='echo hi'\n"
        "vm_scp_to /private/tmp/a.tgz /tmp/a.tgz"
    )
    assert res.returncode == 0, res.stderr
    lines = res.stdout.splitlines()
    assert lines[0] == (
        "GCLOUD:compute ssh epm-h02-host --project=proj-1 --zone=us-west1-b "
        "--tunnel-through-iap --command=echo hi"
    )
    assert lines[1] == (
        "GCLOUD:compute scp /private/tmp/a.tgz epm-h02-host:/tmp/a.tgz "
        "--project=proj-1 --zone=us-west1-b --tunnel-through-iap"
    )


def test_build_remote_images_uses_offline_amd64_flags_and_records_digests(tmp_path: Path) -> None:
    env_file = tmp_path / "rollout.env"
    res = run_shell(
        f"ENV_FILE={shlex.quote(str(env_file))}\n"
        "EPM_INSTANCE=epm-h02-host\n"
        "EPM_RELEASE_TAG=pilot0-20261126-ui\n"
        "vm_ssh() {\n"
        '  printf "CMD:%s\\n" "$*"\n'
        f'  printf "EPM_IMG_OPERATOR=%s\\n" {shlex.quote(SAMPLE_OP_ID)}\n'
        f'  printf "EPM_IMG_ADMIN=%s\\n" {shlex.quote(SAMPLE_ADMIN_ID)}\n'
        "}\n"
        "build_remote_images"
    )
    assert res.returncode == 0, res.stderr
    assert "--platform linux/amd64 --network=none --provenance=false" in res.stdout
    assert "epm-pilot0-operator:pilot0-20261126-ui" in res.stdout
    assert "epm-pilot0-admin:pilot0-20261126-ui" in res.stdout
    env_text = env_file.read_text(encoding="utf-8")
    assert f"EPM_OPERATOR_IMAGE_ID={SAMPLE_OP_ID}" in env_text
    assert f"EPM_ADMIN_IMAGE_ID={SAMPLE_ADMIN_ID}" in env_text


def test_build_remote_images_fails_if_digests_missing(tmp_path: Path) -> None:
    env_file = tmp_path / "rollout.env"
    res = run_shell(
        f"ENV_FILE={shlex.quote(str(env_file))}\n"
        "EPM_INSTANCE=epm-h02-host\n"
        "EPM_RELEASE_TAG=pilot0-20261126-ui\n"
        'vm_ssh() { echo "no ids printed"; }\n'
        "build_remote_images"
    )
    assert res.returncode != 0
    assert "Failed to capture Operator image ID" in res.stderr


def test_recreate_operator_containers_never_passes_health_cmd() -> None:
    res = run_shell(
        'vm_python() { printf "ARGS:%s\\n" "$*"; cat; }\n'
        f"recreate_operator_containers {shlex.quote(SAMPLE_OP_ID)} demo-a"
    )
    assert res.returncode == 0, res.stderr
    assert f"ARGS:{SAMPLE_OP_ID} demo-a" in res.stdout
    # The docker run argument list must never pass --health-cmd (only comment mentions it).
    code_lines = [line for line in res.stdout.splitlines() if not line.lstrip().startswith("#")]
    assert not any("--health-cmd" in line for line in code_lines)
    assert "'--pull', 'never'" in res.stdout or '"--pull", "never"' in res.stdout
    assert "http://127.0.0.1:8081/health/ready" in res.stdout


def test_reinit_operator_workspace_preserves_workspace_id_and_rejects_bad_mode() -> None:
    bad = run_shell(f"reinit_operator_workspace op-1 demo-a invalid {shlex.quote(SAMPLE_OP_ID)}")
    assert bad.returncode != 0
    assert "Invalid reinit mode" in bad.stderr

    ok = run_shell(
        'vm_python() { printf "ARGS:%s\\n" "$*"; cat; }\n'
        f"reinit_operator_workspace op-1 demo-a demo {shlex.quote(SAMPLE_OP_ID)}"
    )
    assert ok.returncode == 0, ok.stderr
    assert f"ARGS:op-1 demo-a demo {SAMPLE_OP_ID}" in ok.stdout
    assert "workspace_metadata SET workspace_id = ?" in ok.stdout
    assert 'new_ws_json["workspaceId"] = original_ws_id' in ok.stdout


def test_capture_operator_recovery_point_restores_ownership_in_finally() -> None:
    res = run_shell(
        'vm_python() { printf "ARGS:%s\\n" "$*"; cat; }\n'
        f"capture_operator_recovery_point op-1 demo-a {shlex.quote(SAMPLE_OP_ID)}"
    )
    assert res.returncode == 0, res.stderr
    assert "finally:" in res.stdout
    assert '"65532:65532"' in res.stdout
    assert "WorkspaceBackupScheduler" in res.stdout


def test_smoke_gate_requires_storage_state_for_https_and_halts_on_failure(tmp_path: Path) -> None:
    app_dir = tmp_path / "application"
    app_dir.mkdir()
    missing = run_shell(
        f"application={shlex.quote(str(app_dir))}\n"
        'run_canary_smoke_gate "https://demo-a.epmdemo.xyz" ""'
    )
    assert missing.returncode != 0
    assert "EPM_SMOKE_STORAGE_STATE" in missing.stderr

    state_file = tmp_path / "state.json"
    state_file.write_text('{"cookies":[]}\n', encoding="utf-8")
    failing = run_shell(
        f"application={shlex.quote(str(app_dir))}\n"
        "npm() { return 1; }\n"
        f'run_canary_smoke_gate "https://demo-a.epmdemo.xyz" {shlex.quote(str(state_file))}'
    )
    assert failing.returncode != 0
    assert "HALT rollout" in failing.stdout
    assert "Canary smoke suite (SMOKE-01..SMOKE-05) failed." in failing.stderr


def test_smoke_gate_passes_env_vars_for_live_and_local(tmp_path: Path) -> None:
    app_dir = tmp_path / "application"
    app_dir.mkdir()
    state_file = tmp_path / "state.json"
    state_file.write_text('{"cookies":[]}\n', encoding="utf-8")

    live = run_shell(
        f"application={shlex.quote(str(app_dir))}\n"
        'npm() { printf "BASE=%s STATE=%s ARGS=%s\\n" '
        '"$EPM_SMOKE_BASE_URL" "${EPM_SMOKE_STORAGE_STATE:-}" "$*"; }\n'
        f'run_canary_smoke_gate "https://demo-a.epmdemo.xyz" {shlex.quote(str(state_file))}'
    )
    assert live.returncode == 0, live.stderr
    assert f"BASE=https://demo-a.epmdemo.xyz STATE={state_file} ARGS=run test:smoke" in live.stdout

    local = run_shell(
        f"application={shlex.quote(str(app_dir))}\n"
        'npm() { printf "BASE=%s STATE=%s ARGS=%s\\n" '
        '"$EPM_SMOKE_BASE_URL" "${EPM_SMOKE_STORAGE_STATE:-}" "$*"; }\n'
        'run_canary_smoke_gate "http://localhost:18802" ""'
    )
    assert local.returncode == 0, local.stderr
    assert "BASE=http://localhost:18802 STATE= ARGS=run test:smoke" in local.stdout


def test_roll_admin_service_validates_target_and_checks_all_six_services() -> None:
    bad = run_shell("roll_admin_service not-a-valid-target")
    assert bad.returncode != 0
    assert "Invalid Admin target" in bad.stderr

    ok = run_shell(
        'vm_python() { printf "ARGS:%s\\n" "$*"; cat; }\n'
        "roll_admin_service epm-pilot0-admin:pilot0-20261126-ui"
    )
    assert ok.returncode == 0, ok.stderr
    for svc in (
        "epm-h03-identity.service",
        "epm-gateway.service",
        "epm-tunnel.service",
        "epm-backup-proxy.service",
        "epm-host-guardian.service",
        "google-cloud-ops-agent.service",
    ):
        assert svc in ok.stdout
    assert "os.replace(tmp_path, identity_path)" in ok.stdout
    assert "identitytoolkit bearer refreshed (600s)" in ok.stdout


def test_snapshot_capture_and_operator_listing(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    env_file = tmp_path / "rollout.env"
    payload = {
        "admin_manifest": SAMPLE_ADMIN_HEX,
        "operators": {
            "op-2": {
                "operator_id": "op-2",
                "workspace_slug": "wwjdf",
                "ip": "10.90.0.3",
                "container": "epm-op-wwjdf",
                "image_id": SAMPLE_OP_ID,
                "image_ref": "epm-pilot0-operator:pilot0-20261125-tasks",
                "status": "running",
            },
            "op-1": {
                "operator_id": "op-1",
                "workspace_slug": "demo-a",
                "ip": "10.90.0.2",
                "container": "epm-op-demo-a",
                "image_id": SAMPLE_OP_ID,
                "image_ref": "epm-pilot0-operator:pilot0-20261125-tasks",
                "status": "running",
            },
        },
    }
    res = run_shell(
        f"ENV_FILE={shlex.quote(str(env_file))}\n"
        f"python_path={shlex.quote(sys.executable)}\n"
        f"vm_python() {{ printf '%s\\n' {shlex.quote(json.dumps(payload))}; }}\n"
        f"capture_pre_rollout_snapshot {shlex.quote(str(snapshot))}\n"
        'printf "LIST:\\n"\n'
        f"list_snapshot_operators {shlex.quote(str(snapshot))}"
    )
    assert res.returncode == 0, res.stderr
    assert stat.S_IMODE(snapshot.stat().st_mode) == PRIVATE_FILE_MODE
    rows = res.stdout.split("LIST:\n", 1)[1].strip().splitlines()
    assert rows == [
        f"op-1\tdemo-a\t{SAMPLE_OP_ID}",
        f"op-2\twwjdf\t{SAMPLE_OP_ID}",
    ]


def test_cleanup_build_artifacts_respects_confirmations_and_keeps_bundle_cache(
    tmp_path: Path,
) -> None:
    build_dir = tmp_path / "epm-build"
    build_dir.mkdir()
    archive = tmp_path / "epm-contexts.tar.gz"
    archive.write_text("archive", encoding="utf-8")
    bundle = tmp_path / "epm-agent-bundle"
    bundle.mkdir()

    res = run_shell(
        f"BUILD_DIR={shlex.quote(str(build_dir))}\n"
        f"CONTEXTS_ARCHIVE={shlex.quote(str(archive))}\n"
        f"AGENT_BUNDLE_DIR={shlex.quote(str(bundle))}\n"
        "EPM_INSTANCE=epm-h02-host\n"
        "confirm() { return 0; }\n"
        'vm_ssh() { printf "SSH:%s\\n" "$*"; }\n'
        "cleanup_build_artifacts"
    )
    assert res.returncode == 0, res.stderr
    assert "SSH:--command=sudo rm -rf /tmp/epm-contexts.tar.gz /tmp/build /tmp/epm-*" in res.stdout
    assert not build_dir.exists()
    assert not archive.exists()
    assert bundle.exists()
