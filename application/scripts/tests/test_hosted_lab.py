"""Source custody and exact-image rejection before isolated effects."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import tarfile

import pytest

LAB = Path(__file__).resolve().parents[2] / "deploy/hosted-mvp/lab"


def test_source_archive_is_deterministic_and_excludes_user_material(tmp_path):
    code = tmp_path / "application"
    for name in (
        "apps/server/app/a.py",
        "apps/server/app/native.c",
        "apps/server/app/tests/test_private.py",
        "apps/server/app/.env",
        "apps/server/app/workspace.sqlite",
        "apps/server/app/web_build/main.js",
        "deploy/hosted-mvp/lab/driver.py",
        "deploy/hosted-mvp/sandbox/epm-h02-operator-v1",
    ):
        path = code / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic")
    snapshot = runpy.run_path(str(LAB / "snapshot.py"))["snapshot"]
    first, second = tmp_path / "first.tar", tmp_path / "second.tar"
    manifest = snapshot(code, first)
    snapshot(code, second)
    assert first.read_bytes() == second.read_bytes()
    assert (
        manifest["source_sha256"]
        == sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    )
    with tarfile.open(first) as archive:
        assert set(archive.getnames()) == {
            "apps/server/app/a.py",
            "apps/server/app/native.c",
            "deploy/hosted-mvp/lab/driver.py",
            "deploy/hosted-mvp/sandbox/epm-h02-operator-v1",
            "qualification-source.json",
        }
    with pytest.raises(FileExistsError):
        snapshot(code, first)
    (code / "apps/server/app/link.py").symlink_to(code / "apps/server/app/a.py")
    with pytest.raises(ValueError):
        snapshot(code, tmp_path / "bad.tar")


@pytest.mark.parametrize("value", ["latest", "epm:test", "sha256:" + "A" * 64, "/tmp/image"])
def test_desktop_driver_rejects_mutable_or_unsafe_image_selection(value):
    validate = runpy.run_path(str(LAB / "desktop.py"))["image_id"]
    with pytest.raises(argparse.ArgumentTypeError):
        validate(value)


def test_desktop_driver_accepts_only_exact_image_identity():
    validate = runpy.run_path(str(LAB / "desktop.py"))["image_id"]
    assert validate("sha256:" + "a" * 64) == "sha256:" + "a" * 64


def test_reboot_source_pin_rejects_file_or_manifest_rewrites(tmp_path):
    verify = runpy.run_path(str(LAB / "qualify_reboot.py"))["verify_source"]
    source = tmp_path / "one.py"
    source.write_text("synthetic")
    pins = {"one.py": sha256(source.read_bytes()).hexdigest()}
    digest = sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()
    manifest = {"files": pins, "source_sha256": digest}
    saved = tmp_path / "qualification-source.json"
    saved.write_text(json.dumps(manifest))
    assert verify(tmp_path) == digest
    source.write_text("changed")
    with pytest.raises(AssertionError):
        verify(tmp_path)
    pins["one.py"] = sha256(source.read_bytes()).hexdigest()
    saved.write_text(json.dumps(manifest))
    with pytest.raises(AssertionError, match="Manifest identity changed"):
        verify(tmp_path)
