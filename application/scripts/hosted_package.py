"""Prepare allowlisted component build contexts; never install or provision a host."""

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app.platform.hosted_artifacts import (
    ArtifactInvalid,
    CandidateManifest,
    FilePin,
    SCHEMAS,
    digest,
    files,
    resource_files,
    schema_states,
    validate_path,
    verify_candidate,
)

APPLICATION = Path(__file__).resolve().parents[1]
SKIPPED = {"tests", "__pycache__", "web_build"}
HARNESSES = {"quota_actor.py", "project_quota_qualification.py"}


@dataclass(frozen=True)
class BuildInput:
    component: str
    architecture: str
    lock: Path
    wheelhouse: Path
    output: Path


def _copy_file(source, target):
    if source.is_symlink() or not source.is_file():
        raise ArtifactInvalid()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def copy_runtime(source: Path, target: Path):
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in SKIPPED for part in relative.parts) or path.name in HARNESSES:
            continue
        if path.is_symlink():
            raise ArtifactInvalid()
        if path.is_file() and path.suffix == ".py":
            _copy_file(path, target / relative)


def copy_resources(application, target, component):
    _copy_file(application / "database/hosted_ddl.py", target / "database/hosted_ddl.py")
    for store in SCHEMAS[component]:
        if store == "business":
            _copy_file(application / "alembic.ini", target / "alembic.ini")
        name = "sqlite-migrations" if store == "business" else store + "-migrations"
        root = application / "database" / name
        if store != "business":
            _copy_file(root / "alembic.ini", target / "database" / name / "alembic.ini")
        _copy_file(root / "env.py", target / "database" / name / "env.py")
        (target / "database" / name / "versions").mkdir(exist_ok=True)
        for revision in sorted((root / "versions").glob("*.py")):
            _copy_file(revision, target / "database" / name / "versions" / revision.name)


def copy_assets(application, package):
    build = application / "apps/web/dist"
    if not (build / "index.html").is_file():
        raise ArtifactInvalid()
    for path in files(build):
        relative = "web_build/" + path.relative_to(build).as_posix()
        validate_path("package", relative, "operator")
        _copy_file(path, package / relative)
    if not any((package / "web_build/assets").glob("*.js")):
        raise ArtifactInvalid()


def inventory(package, resources):
    pins = []
    for label, root in (("package", package), ("resources", resources)):
        candidates = files(root) if label == "package" else resource_files(root)
        pins.extend(
            FilePin(root=label, path=path.relative_to(root).as_posix(), sha256=digest(path))
            for path in candidates
        )
    return tuple(sorted(pins, key=lambda pin: (pin.root, pin.path)))


def build_wheel(source, output, constraints):
    environment = {**os.environ, "SOURCE_DATE_EPOCH": "1704067200"}
    subprocess.run(
        [
            "uv",
            "build",
            str(source),
            "--wheel",
            "--offline",
            "--build-constraints",
            constraints.name,
            "--out-dir",
            str(output),
        ],
        check=True,
        cwd=constraints.parent,
        env=environment,
        capture_output=True,
        text=True,
    )
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1:
        raise ArtifactInvalid()
    return wheels[0]


def audit_wheel(wheel, component):
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("app/"):
                validate_path("package", name.removeprefix("app/"), component)
                data = archive.read(name)
                if (
                    b"-----BEGIN PRIVATE KEY-----" in data
                    or b"-----BEGIN RSA PRIVATE KEY-----" in data
                ):
                    raise ArtifactInvalid()
            elif ".dist-info/" not in name or name.split("/")[-1] not in {
                "METADATA",
                "WHEEL",
                "RECORD",
                "top_level.txt",
                "entry_points.txt",
            }:
                raise ArtifactInvalid()


def prepare(config: BuildInput, *, application: Path = APPLICATION):
    if config.output.exists() or config.output.is_symlink():
        raise ArtifactInvalid()
    if config.component not in SCHEMAS or config.architecture not in {"amd64", "arm64"}:
        raise ArtifactInvalid()
    config.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".epm-artifact-", dir=config.output.parent) as temporary:
        work = Path(temporary)
        source = work / "source"
        package = source / "apps/server/app"
        package.mkdir(parents=True)
        copy_runtime(application / "apps/server/app", package)
        _copy_file(application / "pyproject.toml", source / "pyproject.toml")
        if config.component == "operator":
            subprocess.run(["npm", "run", "build"], cwd=application, check=True)
            copy_assets(application, package)
        resources = work / "context/resources"
        copy_resources(application, resources, config.component)
        wheelhouse = work / "context/wheelhouse"
        wheelhouse.mkdir()
        for path in files(config.wheelhouse):
            if path.suffix != ".whl":
                raise ArtifactInvalid()
            _copy_file(path, wheelhouse / path.name)
        wheel = build_wheel(
            source, work / "built", application / "deploy/hosted-mvp/build-constraints.txt"
        )
        audit_wheel(wheel, config.component)
        _copy_file(wheel, work / "context" / wheel.name)
        _copy_file(config.lock, work / "context/dependencies.lock")
        pins = inventory(package, resources)
        manifest = CandidateManifest(
            component=config.component,
            architecture=config.architecture,
            source_sha256=sha256(
                json.dumps([pin.model_dump() for pin in pins], sort_keys=True).encode()
            ).hexdigest(),
            dependency_lock_sha256=digest(config.lock),
            wheel_sha256=digest(wheel),
            files=pins,
            schemas=schema_states(resources, config.component),
            ui={
                "operator": "compiled_operator",
                "admin": "unavailable",
                "host_agent": "not_applicable",
            }[config.component],
        )
        (resources / "hosted-candidate.json").write_text(manifest.model_dump_json(indent=2) + "\n")
        verify_candidate(manifest, package, resources, component=config.component)
        for name in ("stage_schema_resources.py", "verify_installation.py"):
            _copy_file(application / "scripts" / name, work / "context" / name)
        _copy_file(
            application / "deploy/hosted-mvp/verify_build_inputs.py",
            work / "context/verify_build_inputs.py",
        )
        dockerfile = application / "deploy/hosted-mvp" / ("Dockerfile." + config.component)
        if config.component != "host_agent":
            _copy_file(dockerfile, work / "context/Dockerfile")
        else:
            _copy_file(
                application / "deploy/hosted-mvp/install_agent.py",
                work / "context/install_agent.py",
            )
        (work / "context").rename(config.output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=tuple(SCHEMAS), required=True)
    parser.add_argument("--architecture", choices=("amd64", "arm64"), default="amd64")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(
        BuildInput(
            args.component,
            args.architecture,
            args.lock.resolve(),
            args.wheelhouse.resolve(),
            args.output.absolute(),
        )
    )
    print(manifest.model_dump_json(exclude={"files"}))


if __name__ == "__main__":
    main()
