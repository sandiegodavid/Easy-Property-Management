"""Build-input integrity, deterministic agent delivery and unchanged local defaults."""

from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import hosted_package, stage_schema_resources, verify_installation

APPLICATION = Path(__file__).resolve().parents[2]
DEPLOY = APPLICATION / "deploy/hosted-mvp"


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "resources").mkdir()
    (root / "wheelhouse").mkdir()
    wheel = root / "app.whl"
    wheel.write_bytes(b"synthetic app")
    dependency = root / "wheelhouse/example-1-py3-none-any.whl"
    dependency.write_bytes(b"synthetic dependency")
    lock = root / "dependencies.lock"
    lock.write_text(f"example==1 --hash=sha256:{sha256(dependency.read_bytes()).hexdigest()}\n")
    manifest = {
        "component": "host_agent",
        "wheel_sha256": sha256(wheel.read_bytes()).hexdigest(),
        "dependency_lock_sha256": sha256(lock.read_bytes()).hexdigest(),
        "files": [],
    }
    (root / "resources/hosted-candidate.json").write_text(json.dumps(manifest))
    for name in (
        "install_agent.py",
        "verify_build_inputs.py",
        "stage_schema_resources.py",
        "verify_installation.py",
    ):
        (root / name).write_text("# synthetic bundle fixture\n")
    return root


def verify(root):
    return runpy.run_path(str(DEPLOY / "verify_build_inputs.py"))["verify"](root)


def test_closed_build_inputs_accept_exact_bytes(bundle):
    assert verify(bundle) == bundle / "app.whl"


@pytest.mark.parametrize("tamper", ["app", "lock", "dependency", "extra", "symlink", "unpinned"])
def test_closed_build_inputs_reject_tampering(bundle, tamper):
    if tamper == "app":
        (bundle / "app.whl").write_bytes(b"changed")
    elif tamper == "lock":
        (bundle / "dependencies.lock").write_text("changed")
    elif tamper == "dependency":
        next((bundle / "wheelhouse").iterdir()).write_bytes(b"changed")
    elif tamper == "extra":
        (bundle / "wheelhouse/extra.whl").write_bytes(b"extra")
    elif tamper == "symlink":
        (bundle / "wheelhouse/extra.whl").symlink_to(bundle / "app.whl")
    else:
        lock = bundle / "dependencies.lock"
        lock.write_text("example>=1\n")
        path = bundle / "resources/hosted-candidate.json"
        manifest = json.loads(path.read_text())
        manifest["dependency_lock_sha256"] = sha256(lock.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(bundle)


def archive(bundle, output):
    return subprocess.run(
        [sys.executable, str(DEPLOY / "archive_agent.py"), str(bundle), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_agent_archive_is_deterministic_and_never_overwrites(bundle, tmp_path):
    first, second = tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"
    assert archive(bundle, first).returncode == 0
    assert archive(bundle, second).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    assert archive(bundle, first).returncode != 0


def test_agent_archive_rejects_unexpected_data_before_creating_output(bundle, tmp_path):
    (bundle / "credentials.json").write_text("synthetic")
    output = tmp_path / "bundle.tar.gz"
    assert archive(bundle, output).returncode != 0
    assert not output.exists()


def test_pinned_builder_supports_checkout_paths_with_spaces(tmp_path, monkeypatch):
    constraints = tmp_path / "My Apps/build-constraints.txt"
    source = tmp_path / "source"
    output = tmp_path / "built"
    calls = []

    def build(command, **kwargs):
        calls.append((command, kwargs))
        output.mkdir()
        (output / "app.whl").write_bytes(b"fixture")

    monkeypatch.setattr(hosted_package.subprocess, "run", build)
    hosted_package.build_wheel(source, output, constraints)
    command, options = calls[0]
    assert command[command.index("--build-constraints") + 1] == constraints.name
    assert options["cwd"] == constraints.parent
    assert options["env"]["SOURCE_DATE_EPOCH"] == "1704067200"


def test_local_staging_default_keeps_business_only(tmp_path, monkeypatch):
    source, runtime = tmp_path / "release", tmp_path / "venv"
    resources = source / "database/sqlite-migrations"
    (resources / "versions").mkdir(parents=True)
    (resources / "env.py").write_text("# fixture")
    (resources / "versions/0001.py").write_text("# fixture")
    (source / "alembic.ini").write_text("[alembic]")
    installed = runtime / "lib"
    installed.mkdir(parents=True)
    monkeypatch.setattr(stage_schema_resources.sys, "prefix", str(runtime))
    monkeypatch.setattr(stage_schema_resources.sys, "base_prefix", "/fixture/base")
    monkeypatch.setattr(
        stage_schema_resources,
        "import_module",
        lambda name: SimpleNamespace(application_root=lambda: installed),
    )
    monkeypatch.chdir(tmp_path)
    assert stage_schema_resources.stage(source) == installed
    assert (installed / "database/sqlite-migrations/env.py").is_file()
    assert not (installed / "hosted-candidate.json").exists()
    with pytest.raises(RuntimeError, match="already exist"):
        stage_schema_resources.stage(source)


def test_local_verification_default_does_not_dispatch_hosted(tmp_path, monkeypatch, capsys):
    package = tmp_path / "app"
    assets = package / "web_build/assets"
    assets.mkdir(parents=True)
    (package / "web_build/index.html").write_text("<title>fixture</title>")
    (assets / "main.js").write_text("export {};")
    imports = []

    def load(name):
        imports.append(name)
        if name == "app":
            return SimpleNamespace(__file__=str(package / "__init__.py"))
        assert name == "app.platform.product_migrations"
        return SimpleNamespace(current_revision=lambda: "0001_initial_schema")

    monkeypatch.setattr(verify_installation, "import_module", load)
    monkeypatch.setattr(verify_installation, "version", lambda name: "fixture")
    verify_installation.verify()
    assert "Installed resource checks passed" in capsys.readouterr().out
    assert "app.hosted_candidates.runtime" not in imports
