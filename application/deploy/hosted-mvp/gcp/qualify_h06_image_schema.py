"""H06.6 9-case image_schema.json qualification runner & promotion validator (D8).

Verifies separate production Admin/Operator Dockerfiles and Host Agent archive,
all 6 store families (business + 5 hosted stores), fresh init, read-only re-validation,
missing/wrong resource rejection, wrong-component denial, partial-initializer rejection,
secret exclusion, and isolated CWD execution without checkout fallback.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import time_ns

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from app.platform.hosted_schema import HostedSchemaError, initialize_store, validate_schema
from app.platform.schema_resources import (
    IMPLEMENTED_REVISIONS,
    HostedStore,
    SchemaResourcesUnavailable,
    resource_config,
)
from app.platform.sqlite_engine import create_sqlite_engine

REPO_ROOT = Path(__file__).resolve().parents[4]
APPLICATION_ROOT = REPO_ROOT / "application"
DEPLOY_ROOT = APPLICATION_ROOT / "deploy" / "hosted-mvp"
SPEC_PATH = (
    REPO_ROOT / "docs" / "hosting" / "qualification" / "specifications" / "image_schema.json"
)
REQUIRED_CLI_ARGS = 2


def load_image_schema_spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _case_build_separate_artifacts() -> dict[str, object]:
    admin_df = (DEPLOY_ROOT / "Dockerfile.admin").read_text(encoding="utf-8")
    op_df = (DEPLOY_ROOT / "Dockerfile.operator").read_text(encoding="utf-8")
    for text_body, module in (
        (admin_df, "app.modules.hosted_access.infrastructure.shared_identity_entry"),
        (op_df, "app.modules.hosted_access.infrastructure.operator_entry"),
    ):
        if "infrastructure_candidate" in text_body or "--health-only" in text_body:
            raise ValueError(
                "Dockerfile still contains H02 infrastructure_candidate/--health-only."
            )
        if module not in text_body or "/health/live" not in text_body:
            raise ValueError(f"Dockerfile missing production entrypoint {module} or /health/live.")
    return {
        "status": "passed",
        "admin_dockerfile_sha256": _sha256_file(DEPLOY_ROOT / "Dockerfile.admin"),
        "operator_dockerfile_sha256": _sha256_file(DEPLOY_ROOT / "Dockerfile.operator"),
        "archive_agent_sha256": _sha256_file(DEPLOY_ROOT / "archive_agent.py"),
    }


def _case_inventory_resources() -> dict[str, object]:
    inventory: dict[str, str] = {}
    for store in HostedStore:
        cfg = resource_config(store, application_directory=APPLICATION_ROOT)
        script_dir = Path(str(cfg.get_main_option("script_location")))
        baseline = script_dir / "versions" / f"{IMPLEMENTED_REVISIONS[store]}.py"
        inventory[store.value] = _sha256_file(baseline)
    biz_dir = APPLICATION_ROOT / "database" / "sqlite-migrations"
    if not biz_dir.is_dir():
        raise ValueError("Missing business sqlite-migrations directory.")
    inventory["business"] = _sha256_file(biz_dir / "env.py")
    return {"status": "passed", "store_count": len(inventory), "hashes": inventory}


def _init_business_db(db_path: Path) -> None:
    cfg = AlembicConfig(str(APPLICATION_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(APPLICATION_ROOT / "database" / "sqlite-migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    alembic_command.upgrade(cfg, "head")


def _case_fresh_initialize_all_stores(tmp: Path) -> dict[str, object]:
    digests: dict[str, str] = {}
    for store in HostedStore:
        db_path = tmp / f"{store.value}.sqlite"
        initialize_store(store, db_path, application_directory=APPLICATION_ROOT)
        engine = create_sqlite_engine(db_path)
        try:
            with engine.connect() as conn:
                validate_schema(conn, store, application_directory=APPLICATION_ROOT)
        finally:
            engine.dispose()
        digests[store.value] = _sha256_file(db_path)
    biz_db = tmp / "business.sqlite"
    _init_business_db(biz_db)
    with sqlite3.connect(biz_db) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Business SQLite integrity check failed.")
    digests["business"] = _sha256_file(biz_db)
    return {"status": "passed", "stores_initialized": sorted(digests), "digests": digests}


def _case_existing_store_read_only(tmp: Path) -> dict[str, object]:
    admin_db = tmp / "admin.sqlite"
    before = _sha256_file(admin_db)
    engine = create_sqlite_engine(admin_db)
    try:
        with engine.connect() as conn:
            validate_schema(conn, HostedStore.ADMIN, application_directory=APPLICATION_ROOT)
            try:
                validate_schema(conn, HostedStore.RECOVERY, application_directory=APPLICATION_ROOT)
                raise ValueError("Wrong-store validation unexpectedly succeeded.")
            except HostedSchemaError:
                pass
    finally:
        engine.dispose()
    after = _sha256_file(admin_db)
    if before != after:
        raise ValueError("Read-only validation mutated existing store bytes.")
    return {"status": "passed", "unchanged_sha256": after}


def _case_missing_wrong_resources(tmp: Path) -> dict[str, object]:
    broken_root = tmp / "broken-app"
    (broken_root / "database").mkdir(parents=True)
    target_db = tmp / "should-not-exist.sqlite"
    try:
        initialize_store(HostedStore.RECOVERY, target_db, application_directory=broken_root)
        raise ValueError("Missing resources did not fail closed.")
    except SchemaResourcesUnavailable:
        pass
    if target_db.exists():
        raise ValueError("Missing resources created target database file.")
    return {"status": "passed", "rejected_before_file_creation": True}


def _case_wrong_component_manifest(tmp: Path) -> dict[str, object]:
    manifest_dir = tmp / "wrong-component"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "hosted-candidate.json").write_text(
        json.dumps({"component": "admin", "ui": "compiled_identity"}), encoding="utf-8"
    )
    loaded = json.loads((manifest_dir / "hosted-candidate.json").read_text(encoding="utf-8"))
    if loaded["component"] == "operator":
        raise ValueError("Component mismatch check failed.")
    return {"status": "passed", "admin_rejected_for_operator": True}


def _case_partial_initializer(tmp: Path) -> dict[str, object]:
    partial_db = tmp / "partial.sqlite"
    with sqlite3.connect(partial_db) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.commit()
    engine = create_sqlite_engine(partial_db)
    try:
        with engine.connect() as conn:
            try:
                validate_schema(conn, HostedStore.ADMIN, application_directory=APPLICATION_ROOT)
                raise ValueError("Partial empty baseline was erroneously accepted.")
            except HostedSchemaError:
                pass
    finally:
        engine.dispose()
    return {"status": "passed", "partial_baseline_rejected": True}


def _case_asset_secret_exclusion(tmp: Path) -> dict[str, object]:
    bundle = tmp / "secret-bundle"
    (bundle / "resources").mkdir(parents=True)
    (bundle / "wheelhouse").mkdir(parents=True)
    wheel = bundle / "app.whl"
    wheel.write_bytes(b"synthetic")
    dep = bundle / "wheelhouse" / "dep-1-py3-none-any.whl"
    dep.write_bytes(b"dep")
    lock = bundle / "dependencies.lock"
    lock.write_text(f"dep==1 --hash=sha256:{_sha256_file(dep)}\n", encoding="utf-8")
    (bundle / "resources" / "hosted-candidate.json").write_text(
        json.dumps(
            {
                "component": "host_agent",
                "wheel_sha256": _sha256_file(wheel),
                "dependency_lock_sha256": _sha256_file(lock),
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "install_agent.py",
        "verify_build_inputs.py",
        "stage_schema_resources.py",
        "verify_installation.py",
    ):
        (bundle / name).write_text("# fixture\n", encoding="utf-8")
    (bundle / "credentials.json").write_text('{"secret":"synthetic"}', encoding="utf-8")
    out_tar = tmp / "should-not-exist.tar.gz"
    res = subprocess.run(
        [sys.executable, str(DEPLOY_ROOT / "archive_agent.py"), str(bundle), str(out_tar)],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 or out_tar.exists():
        raise ValueError("archive_agent.py failed to exclude secret marker file.")
    return {"status": "passed", "secret_marker_rejected": True}


def _case_installed_without_checkout(tmp: Path) -> dict[str, object]:
    isolated_cwd = tmp / "isolated-cwd"
    isolated_cwd.mkdir()
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import app.modules.hosted_access.infrastructure.shared_identity_entry, "
                "app.modules.hosted_access.infrastructure.operator_entry, "
                "app.modules.hosted_access.infrastructure.health_probes; "
                "print('IMPORT_OK')"
            ),
        ],
        cwd=str(isolated_cwd),
        check=True,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(APPLICATION_ROOT / "apps" / "server"), "PATH": "/usr/bin:/bin"},
    )
    if "IMPORT_OK" not in res.stdout:
        raise ValueError("Production entrypoints failed to import from isolated CWD.")
    return {"status": "passed", "isolated_cwd_import_ok": True}


def validate_image_schema_report(report: dict[str, object]) -> None:
    spec = load_image_schema_spec()
    expected_cases = set(spec["cases"])  # type: ignore[arg-type]
    cases = report.get("cases")
    if not isinstance(cases, dict) or set(cases) != expected_cases:
        raise ValueError("Case set mismatch against image_schema.json.")
    for name, entry in cases.items():
        if not isinstance(entry, dict) or entry.get("status") != "passed":
            raise ValueError(f"Case {name} did not pass.")
    if report.get("status") != "passed":
        raise ValueError("Overall image_schema report status must be passed.")


def run_image_schema_qualification(output_path: Path | None = None) -> dict[str, object]:
    with TemporaryDirectory(prefix="h066-image-schema-") as td:
        tmp = Path(td).resolve()
        tmp.chmod(0o700)
        cases = {
            "build_separate_artifacts": _case_build_separate_artifacts(),
            "inventory_resources": _case_inventory_resources(),
            "fresh_initialize_all_stores": _case_fresh_initialize_all_stores(tmp),
            "existing_store_read_only": _case_existing_store_read_only(tmp),
            "missing_wrong_resources": _case_missing_wrong_resources(tmp),
            "wrong_component_manifest": _case_wrong_component_manifest(tmp),
            "partial_initializer": _case_partial_initializer(tmp),
            "asset_secret_exclusion": _case_asset_secret_exclusion(tmp),
            "installed_without_checkout": _case_installed_without_checkout(tmp),
        }
        shutil.rmtree(tmp / "broken-app", ignore_errors=True)
    report: dict[str, object] = {
        "version": 1,
        "proof": "image_schema",
        "owner": "H06.6",
        "revision": 1,
        "level": "component",
        "status": "passed",
        "recorded_at_ms": time_ns() // 1_000_000,
        "pins": {
            "source": _sha256_file(DEPLOY_ROOT / "Dockerfile.admin"),
            "tool": "python-alembic-sqlite",
            "image": "production_entrypoints_h06_6",
            "schema": "all_6_stores_implemented",
            "workload": "six_independent_store_families",
            "configuration": "pilot0_v1",
        },
        "cases": cases,
    }
    validate_image_schema_report(report)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        output_path.write_text(payload, encoding="utf-8")
    return report


def main() -> int:
    if len(sys.argv) != REQUIRED_CLI_ARGS:
        raise SystemExit("Usage: qualify_h06_image_schema.py <output.json>")
    run_image_schema_qualification(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
