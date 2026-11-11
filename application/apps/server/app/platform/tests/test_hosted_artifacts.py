"""Allowlisted candidate inventories; component fixtures never qualify a runtime."""

from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from app.platform.hosted_artifacts import (
    ArtifactInvalid,
    CandidateManifest,
    FilePin,
    SCHEMAS,
    digest,
    files,
    load_manifest,
    schema_states,
    stage_candidate,
    verify_candidate,
)
from scripts.hosted_package import copy_resources, copy_runtime, audit_wheel

APPLICATION = Path(__file__).resolve().parents[5]


@pytest.fixture
def payload(tmp_path):
    def make(component):
        package = tmp_path / component / "package"
        package.mkdir(parents=True)
        entry = "agent" if component == "host_agent" else component
        for name in [
            "__init__.py",
            "hosted_candidates/__init__.py",
            "hosted_candidates/runtime.py",
            "hosted_candidates/binding.py",
            "hosted_candidates/startup.py",
            "hosted_candidates/status_page.py",
            f"hosted_candidates/{entry}.py",
            "platform/config.py",
            "platform/hosted_artifacts.py",
        ]:
            path = package / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text("# Synthetic inventory fixture, not an installed application.\n")
        if component == "operator":
            assets = package / "web_build/assets"
            assets.mkdir(parents=True)
            (package / "web_build/index.html").write_text("<!doctype html><title>Synthetic</title>")
            (assets / "main.js").write_text("export {};\n")
        resources = package.parent / "resources"
        copy_resources(APPLICATION, resources, component)
        pins = tuple(
            FilePin(root=label, path=path.relative_to(folder).as_posix(), sha256=digest(path))
            for label, folder in [("package", package), ("resources", resources)]
            for path in files(folder)
        )
        manifest = CandidateManifest(
            component=component,
            architecture="amd64",
            source_sha256="a" * 64,
            dependency_lock_sha256="b" * 64,
            wheel_sha256="c" * 64,
            files=pins,
            schemas=schema_states(resources, component),
            ui={
                "admin": "unavailable",
                "operator": "compiled_operator",
                "host_agent": "not_applicable",
            }[component],
        )
        (resources / "hosted-candidate.json").write_text(manifest.model_dump_json())
        return manifest, package, resources

    return make


@pytest.mark.parametrize("component", tuple(SCHEMAS))
def test_owned_resources_and_unavailable_runtime_are_explicit(payload, component):
    manifest, package, resources = payload(component)
    parsed = load_manifest(resources / "hosted-candidate.json")
    assert parsed == manifest
    report = verify_candidate(parsed, package, resources, component=component)
    assert report["acceptance"] == "infrastructure_candidate"
    assert report["runtime"] == "unavailable"
    expected = {
        "admin": ["admin-recovery"],
        "operator": ["hosted-access", "recovery"],
        "host_agent": [],
    }
    assert report["unavailableSchemas"] == expected[component]


@pytest.mark.parametrize("component", tuple(SCHEMAS))
def test_fresh_staging_is_cwd_independent_and_never_overwrites(
    payload, component, tmp_path, monkeypatch
):
    manifest, package, resources = payload(component)
    installed = tmp_path / "installed"
    installed.mkdir()
    monkeypatch.chdir(tmp_path)
    stage_candidate(resources, component=component, package=package, target=installed)
    assert (
        verify_candidate(manifest, package, installed, component=component)["component"]
        == component
    )
    before = {str(p.relative_to(installed)): p.read_bytes() for p in files(installed)}
    with pytest.raises(ArtifactInvalid):
        stage_candidate(resources, component=component, package=package, target=installed)
    assert before == {str(p.relative_to(installed)): p.read_bytes() for p in files(installed)}


@pytest.mark.parametrize(
    "extra",
    [
        ".env",
        "credentials.json",
        "workspace.sqlite",
        "tests/probe.py",
        "web_build/assets/private.map",
    ],
)
def test_extra_data_cannot_enter_runtime(payload, extra):
    manifest, package, resources = payload("operator")
    path = package / extra
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text("synthetic-not-a-real-secret")
    with pytest.raises(ArtifactInvalid):
        verify_candidate(manifest, package, resources, component="operator")


@pytest.mark.parametrize("tamper", ["missing", "changed", "symlink"])
def test_runtime_byte_tampering_rejects(payload, tamper, tmp_path):
    manifest, package, resources = payload("admin")
    path = package / "platform/config.py"
    if tamper == "changed":
        path.write_text("changed")
    else:
        path.unlink()
        if tamper == "symlink":
            outside = tmp_path / "outside.py"
            outside.write_text("outside")
            path.symlink_to(outside)
    with pytest.raises(ArtifactInvalid):
        verify_candidate(manifest, package, resources, component="admin")


def test_wrong_component_and_false_acceptance_reject(payload):
    manifest, package, resources = payload("admin")
    with pytest.raises(ArtifactInvalid):
        verify_candidate(manifest, package, resources, component="operator")
    for changes in [{"acceptance": "qualified"}, {"runtime": "ready"}]:
        with pytest.raises(ValidationError):
            CandidateManifest(**(manifest.model_dump() | changes))


@pytest.mark.parametrize("component", tuple(SCHEMAS))
def test_missing_resources_publish_nothing(payload, component, tmp_path):
    manifest, package, resources = payload(component)
    first = next(
        pin for pin in manifest.files if pin.root == "resources" and pin.path.endswith("env.py")
    )
    (resources / first.path).unlink()
    target = tmp_path / "installed"
    target.mkdir()
    with pytest.raises(ArtifactInvalid):
        stage_candidate(resources, component=component, package=package, target=target)
    assert list(target.iterdir()) == []


def test_private_key_marker_fails_even_with_updated_file_hash(payload):
    manifest, package, resources = payload("admin")
    target = package / "platform/config.py"
    target.write_text("value = '-----BEGIN PRIVATE KEY-----'\n")
    pins = tuple(
        pin.model_copy(update={"sha256": digest(target)})
        if pin.path == "platform/config.py"
        else pin
        for pin in manifest.files
    )
    changed = CandidateManifest(**(manifest.model_dump() | {"files": pins}))
    with pytest.raises(ArtifactInvalid):
        verify_candidate(changed, package, resources, component="admin")


def test_duplicate_fields_and_unsafe_inventory_paths_reject(payload):
    _, _, resources = payload("admin")
    path = resources / "hosted-candidate.json"
    path.write_text('{"component":"operator","component":"admin"}')
    with pytest.raises(ArtifactInvalid):
        load_manifest(path)
    for name in ("../outside.py", "/absolute.py", ".", "a/../b.py"):
        with pytest.raises(ValidationError):
            FilePin(root="package", path=name, sha256="a" * 64)


def test_failed_publication_reverses_prior_entries(payload, tmp_path, monkeypatch):
    _, package, resources = payload("operator")
    target = tmp_path / "installed"
    target.mkdir()
    original = Path.rename

    def fail_manifest(path, destination):
        if path.name == "hosted-candidate.json":
            raise OSError("synthetic publication fault")
        return original(path, destination)

    monkeypatch.setattr(Path, "rename", fail_manifest)
    with pytest.raises(OSError):
        stage_candidate(resources, component="operator", package=package, target=target)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize(
    "relative", ["database/host-inventory-migrations/env.py", "database/sqlite-migrations/env.py"]
)
def test_unselected_private_stores_cannot_be_declared(payload, relative):
    manifest, _, _ = payload("admin")
    with pytest.raises(ArtifactInvalid):
        CandidateManifest(
            **(
                manifest.model_dump()
                | {
                    "files": (
                        *manifest.files,
                        FilePin(root="resources", path=relative, sha256="a" * 64),
                    )
                }
            )
        )


def test_runtime_copy_omits_test_corpus_data_and_generated_assets(tmp_path):
    source = tmp_path / "source"
    for name in [
        "__init__.py",
        "modules/demo/code.py",
        "modules/demo/tests/test_code.py",
        "web_build/index.html",
        "credentials.json",
        "modules/demo/quota_actor.py",
    ]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic")
    target = tmp_path / "target"
    copy_runtime(source, target)
    assert sorted(path.relative_to(target).as_posix() for path in files(target)) == [
        "__init__.py",
        "modules/demo/code.py",
    ]


def test_wheel_archive_rejects_unexpected_data(tmp_path):
    path = tmp_path / "unsafe.whl"
    with ZipFile(path, "w") as archive:
        archive.writestr("app/credentials.json", "synthetic")
    with pytest.raises(ArtifactInvalid):
        audit_wheel(path, "admin")
