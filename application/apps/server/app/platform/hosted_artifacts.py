"""H02.4 candidate inventories; never a qualified release or runtime admission grant."""

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import Field, model_validator

from app.platform.hosted_contracts.values import Contract, RequestHash
from app.platform.schema_resources import HostedStore, resource_config, scaffold_config

Component = Literal["admin", "operator", "host_agent"]
SCHEMAS = {
    "admin": ("admin", "admin-recovery"),
    "operator": ("business", "hosted-access", "recovery"),
    "host_agent": ("host-inventory",),
}
MAX_MANIFEST = 8 * 1024 * 1024
MAX_RUNTIME_FILE = 64 * 1024 * 1024
PUBLIC_SUFFIXES = {".js", ".css", ".svg", ".png", ".jpg", ".webp", ".ico", ".woff2"}


class ArtifactInvalid(RuntimeError):
    code = "hosted_artifact_invalid"

    def __init__(self):
        super().__init__("The candidate does not match its declared component inventory.")


class ArtifactUnavailable(RuntimeError):
    code = "hosted_artifact_unavailable"

    def __init__(self):
        super().__init__("Required hosted resources or runtime composition are unavailable.")


class FilePin(Contract):
    root: Literal["package", "resources"]
    path: Annotated[str, Field(min_length=1, max_length=512)]
    sha256: RequestHash

    @model_validator(mode="after")
    def safe_path(self):
        path = PurePosixPath(self.path)
        if (
            not path.parts
            or path.is_absolute()
            or str(path) != self.path
            or any(part in {"..", "."} for part in path.parts)
            or "\\" in self.path
        ):
            raise ValueError("A canonical relative inventory path is required.")
        return self


class SchemaPin(Contract):
    store: str
    state: Literal["implemented", "unavailable"]
    revision: str | None


class CandidateManifest(Contract):
    version: Literal[1] = 1
    component: Component
    architecture: Literal["amd64", "arm64"]
    source_sha256: RequestHash
    dependency_lock_sha256: RequestHash
    wheel_sha256: RequestHash
    files: Annotated[tuple[FilePin, ...], Field(min_length=1, max_length=5000)]
    schemas: tuple[SchemaPin, ...]
    ui: Literal["compiled_operator", "unavailable", "not_applicable"]
    acceptance: Literal["infrastructure_candidate"] = "infrastructure_candidate"
    runtime: Literal["unavailable"] = "unavailable"

    @model_validator(mode="after")
    def component_ownership(self):
        if tuple(item.store for item in self.schemas) != SCHEMAS[self.component]:
            raise ValueError("Candidate schema ownership mismatch.")
        paths = [(pin.root, pin.path) for pin in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("Duplicate candidate file.")
        if (
            self.ui
            != {
                "admin": "unavailable",
                "operator": "compiled_operator",
                "host_agent": "not_applicable",
            }[self.component]
        ):
            raise ValueError("Candidate UI ownership mismatch.")
        for schema in self.schemas:
            if (schema.state == "implemented") != (schema.revision is not None):
                raise ValueError("Unavailable schemas cannot invent a revision.")
        for pin in self.files:
            validate_path(pin.root, pin.path, self.component)
        _required_package(paths, self.component)
        return self


def _required_package(paths, component):
    entry = "agent" if component == "host_agent" else component
    required = {
        "__init__.py",
        "hosted_candidates/__init__.py",
        "hosted_candidates/runtime.py",
        "hosted_candidates/binding.py",
        "hosted_candidates/startup.py",
        "hosted_candidates/status_page.py",
        f"hosted_candidates/{entry}.py",
        "platform/config.py",
        "platform/hosted_artifacts.py",
    }
    declared = {path for root, path in paths if root == "package"}
    if not required <= declared:
        raise ArtifactInvalid()
    if component == "operator" and (
        "web_build/index.html" not in declared
        or not any(
            path.startswith("web_build/assets/") and path.endswith(".js") for path in declared
        )
    ):
        raise ArtifactInvalid()


ASSET_DEPTH = 3
RESOURCE_DEPTH = 3
REVISION_DEPTH = 4


def validate_path(root, relative, component):
    path = PurePosixPath(relative)
    forbidden = {"tests", "__pycache__", ".git", "node_modules", "workspaces"}
    if not path.parts or any(part in forbidden or part.startswith(".") for part in path.parts):
        raise ArtifactInvalid()
    if root == "package":
        _package_path(path, relative, component)
    else:
        _resource_path(path, relative, component)


def _package_path(path, relative, component):
    if path.parts[0] == "web_build":
        asset = (
            len(path.parts) == ASSET_DEPTH
            and path.parts[1] == "assets"
            and path.suffix in PUBLIC_SUFFIXES
        )
        if component != "operator" or not (relative == "web_build/index.html" or asset):
            raise ArtifactInvalid()
    elif path.suffix != ".py" or path.name in {"quota_actor.py", "project_quota_qualification.py"}:
        raise ArtifactInvalid()


def _resource_path(path, relative, component):
    if relative == "alembic.ini":
        if component != "operator":
            raise ArtifactInvalid()
        return
    if relative == "database/hosted_ddl.py":
        return
    resources = {
        "sqlite-migrations" if name == "business" else name + "-migrations"
        for name in SCHEMAS[component]
    }
    if (
        len(path.parts) < RESOURCE_DEPTH
        or path.parts[0] != "database"
        or path.parts[1] not in resources
    ):
        raise ArtifactInvalid()
    revision = (
        len(path.parts) == REVISION_DEPTH and path.parts[2] == "versions" and path.suffix == ".py"
    )
    environment = len(path.parts) == RESOURCE_DEPTH and path.name in {"alembic.ini", "env.py"}
    if not (revision or environment):
        raise ArtifactInvalid()


def digest(path):
    value = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_content(path):
    if path.stat().st_size > MAX_RUNTIME_FILE:
        raise ArtifactInvalid()
    data = path.read_bytes()
    markers = (b"-----BEGIN " + b"PRIVATE KEY-----", b"-----BEGIN " + b"RSA PRIVATE KEY-----")
    if any(marker in data for marker in markers):
        raise ArtifactInvalid()


def files(root: Path):
    if root.is_symlink() or not root.is_dir():
        raise ArtifactInvalid()
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ArtifactInvalid()
        if path.is_file():
            result.append(path)
        elif not path.is_dir():
            raise ArtifactInvalid()
    return result


def resource_files(root: Path):
    # Installed application_root is the venv lib directory, which also contains
    # site-packages. Only these explicitly owned resource roots belong to this set.
    result = files(root / "database")
    ini = root / "alembic.ini"
    if ini.exists() or ini.is_symlink():
        if ini.is_symlink() or not ini.is_file():
            raise ArtifactInvalid()
        result.append(ini)
    return result


def load_manifest(path):
    if path.is_symlink() or path.stat().st_size > MAX_MANIFEST:
        raise ArtifactInvalid()
    data = path.read_bytes()
    json.loads(data, object_pairs_hook=_unique_object)
    return CandidateManifest.model_validate_json(data)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactInvalid()
        result[key] = value
    return result


def schema_states(root, component):
    # Alembic imports revision modules. Inspection of a sealed artifact must not
    # manufacture __pycache__ files in its declared resource tree.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return _schema_states(root, component)
    finally:
        sys.dont_write_bytecode = previous


def _schema_states(root, component):
    result = []
    for name in SCHEMAS[component]:
        if name == "business":
            config = Config(str(root / "alembic.ini"))
            # Existing business INI resolves relative to config.application_root;
            # inspect the declared installed tree, never the checkout fallback.
            config.set_main_option("script_location", str(root / "database/sqlite-migrations"))
            scripts = ScriptDirectory.from_config(config)
            heads = scripts.get_heads()
            if len(heads) != 1:
                raise ArtifactInvalid()
            result.append(SchemaPin(store=name, state="implemented", revision=heads[0]))
            continue
        store = HostedStore(name)
        if name in {"admin", "host-inventory"}:
            config = resource_config(store, application_directory=root)
            revision = ScriptDirectory.from_config(config).get_current_head()
            result.append(SchemaPin(store=name, state="implemented", revision=revision))
        else:
            scaffold_config(store, application_directory=root)
            result.append(SchemaPin(store=name, state="unavailable", revision=None))
    return tuple(result)


def verify_candidate(
    manifest: CandidateManifest, package: Path, resources: Path, *, component: Component
):
    if manifest.component != component:
        raise ArtifactInvalid()
    actual = []
    for label, root in (("package", package), ("resources", resources)):
        for path in files(root) if label == "package" else resource_files(root):
            relative = path.relative_to(root).as_posix()
            if label == "resources" and relative == "hosted-candidate.json":
                continue
            # Interpreter-generated bytecode is never a declared artifact. Candidate
            # launches use -B; verifier refuses even a newly injected cache/pyc.
            validate_path(label, relative, component)
            check_content(path)
            actual.append(FilePin(root=label, path=relative, sha256=digest(path)))
    expected = {(pin.root, pin.path): pin.sha256 for pin in manifest.files}
    if {(pin.root, pin.path): pin.sha256 for pin in actual} != expected:
        raise ArtifactInvalid()
    if schema_states(resources, component) != manifest.schemas:
        raise ArtifactInvalid()
    return {
        "component": component,
        "acceptance": manifest.acceptance,
        "runtime": manifest.runtime,
        "unavailableSchemas": [
            item.store for item in manifest.schemas if item.state == "unavailable"
        ],
    }


def stage_candidate(source: Path, *, component: Component, package: Path, target: Path):
    """Fresh installed resource staging only; never initialize a destination database."""
    manifest = load_manifest(source / "hosted-candidate.json")
    if {path.name for path in source.iterdir()} - {
        "database",
        "alembic.ini",
        "hosted-candidate.json",
    }:
        raise ArtifactInvalid()
    verify_candidate(manifest, package, source, component=component)
    entries = ("alembic.ini", "database", "hosted-candidate.json")
    if target.is_symlink() or any(
        (target / entry).exists() or (target / entry).is_symlink() for entry in entries
    ):
        raise ArtifactInvalid()
    with TemporaryDirectory(prefix=".epm-candidate-", dir=target) as temporary:
        staging = Path(temporary)
        for entry in entries:
            path = source / entry
            if path.is_dir():
                shutil.copytree(path, staging / entry)
            elif path.is_file():
                shutil.copyfile(path, staging / entry)
        published = []
        try:
            for entry in entries:
                if (staging / entry).exists():
                    (staging / entry).rename(target / entry)
                    published.append(entry)
        except BaseException:
            for entry in reversed(published):
                (target / entry).rename(staging / entry)
            raise
    return manifest
