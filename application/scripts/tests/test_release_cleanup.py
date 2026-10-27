"""Verify cleanup protections using temporary directories, never real VM releases."""

import ast
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_cleanup", SCRIPTS / "release_cleanup.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.fixture
def releases(tmp_path):
    root = tmp_path / "releases"
    root.mkdir()
    for name in ("current", "rollback", "unused"):
        (root / name).mkdir()
    return root


def inspect(root, **kwargs):
    return tool.inventory(
        root,
        kwargs.get("sources", ()),
        kwargs.get("effective", b""),
        kwargs.get("processes", ()),
        kwargs.get("keep", ("rollback",)),
    )


def test_current_and_explicit_rollback_are_protected(releases):
    result = inspect(releases, effective=f"{releases}/current/venv/bin/python".encode())
    assert result["current"] == ["effective A/B service command"]
    assert result["rollback"] == ["explicit rollback retention"]
    assert result["unused"] == []


@pytest.mark.parametrize("source", ["service.conf", "timer.service", "cron", "hosted.json"])
def test_config_and_job_references_are_protected(releases, tmp_path, source):
    config = tmp_path / source
    config.write_text(f"{releases}/unused/venv/bin/python")
    assert inspect(releases, sources=(config,))["unused"]


def test_checkpoint_owner_and_old_interpreter_stay_protected(releases):
    record = releases / "current/wizard-state/a.record"
    record.mkdir(parents=True)
    (record / "reset.json").write_text(f'{{"old_python":"{releases}/unused/venv/bin/python"}}')
    result = inspect(releases)
    assert any("checkpoints" in reason for reason in result["current"])
    assert any("rollback reference" in reason for reason in result["unused"])


def test_install_checksum_alone_does_not_count_as_checkpoint(releases):
    state = releases / "unused/wizard-state"
    state.mkdir()
    (state / "archive-sha256.txt").write_text("hash")
    assert inspect(releases)["unused"] == []


def test_running_process_and_release_alias_protect_targets(releases):
    result = inspect(
        releases, processes=((Path("/proc/1/maps"), f"{releases}/unused/lib.so".encode()),)
    )
    assert result["unused"]
    (releases / "alias").symlink_to("unused")
    result = inspect(releases)
    assert result["alias"]
    assert result["unused"] == ["release alias: alias"]


@pytest.mark.parametrize("name", ["../unused", "/tmp/unused", "unused;echo", ""])
def test_invalid_removal_name_never_runs_inventory(monkeypatch, name):
    monkeypatch.setattr(tool, "host_inventory", lambda keep: pytest.fail("must reject first"))
    with pytest.raises(ValueError, match="Invalid release name"):
        tool.remove_release(name, ["rollback"])


def test_remove_rechecks_references_and_refuses_newly_protected_release(monkeypatch):
    monkeypatch.setattr(tool, "host_inventory", lambda keep: {"unused": ["new service reference"]})
    with pytest.raises(ValueError, match="new service reference"):
        tool.remove_release("unused", ["rollback"])


def test_confirmed_removal_deletes_only_selected_release(releases, tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "RELEASES", releases)
    monkeypatch.setattr(tool, "host_inventory", lambda keep: {"unused": []})
    original = Path.lstat
    original_read = Path.read_text

    def mount_info(path, *args, **kwargs):
        if str(path) == "/proc/self/mountinfo":
            return ""
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", mount_info)

    def root_owned(path):
        values = list(original(path))
        values[4] = 0
        return os.stat_result(values)

    monkeypatch.setattr(Path, "lstat", root_owned)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = workspace / "keep.txt"
    data.write_text("preserved")
    (releases / "unused/linked-data").symlink_to(workspace)
    (releases / "unused/code.py").write_text("old code")
    tool.remove_release("unused", ["rollback"])
    assert not (releases / "unused").exists()
    assert (releases / "current").is_dir()
    assert (releases / "rollback").is_dir()
    assert data.read_text() == "preserved"


def test_mounted_content_cannot_be_removed(releases, monkeypatch):
    monkeypatch.setattr(tool, "RELEASES", releases)
    monkeypatch.setattr(tool, "host_inventory", lambda keep: {"unused": []})
    monkeypatch.setattr(
        Path, "read_text", lambda path: f"1 2 0:1 / {releases}/unused/data rw - ext4 x rw"
    )
    with pytest.raises(ValueError, match="contains a mount"):
        tool.remove_release("unused", ["rollback"])
    assert (releases / "unused").is_dir()


def test_missing_rollback_release_stops_inventory(releases):
    with pytest.raises(ValueError, match="does not exist"):
        inspect(releases, keep=("missing",))


def test_symlink_root_is_rejected(releases, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(releases)
    with pytest.raises(ValueError, match="real directory"):
        inspect(alias)


def test_unreadable_reference_stops_inventory(releases, monkeypatch, tmp_path):
    source = tmp_path / "service.conf"
    source.touch()

    def denied(path):
        raise PermissionError("cannot inspect reference")

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(PermissionError):
        inspect(releases, sources=(source,))


def test_wizard_help_syntax_and_shared_library():
    script = SCRIPTS / "epm-release-cleanup-vm.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    result = subprocess.run(
        ["bash", str(script), "--help"], capture_output=True, text=True, check=True
    )
    assert "one unreferenced installed release" in result.stdout
    marker = "# STAGES:"
    assert (
        script.read_text().split(marker)[0]
        == (SCRIPTS / "epm-release-vm.sh").read_text().split(marker)[0]
    )
    ast.parse((SCRIPTS / "release_cleanup.py").read_text(), feature_version=(3, 12))
