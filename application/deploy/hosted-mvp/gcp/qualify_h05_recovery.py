"""H05.11 17-case recovery.json qualification runner, joint H04/H05 positive handoff & validator.

Executes all 17 cases specified in `docs/hosting/qualification/specifications/recovery.json`
plus the joint H04/H05 positive workspace handoff (2 disposable operators, verified H05
recovery-point proof unlocking `desired_state="eligible"` in `auth_config`, live business
readiness, and `ADMIN_H05_ROUTES` v3 projection), and validates the closed report against
the specification.

Component and native GCP/deployed-browser runs are emitted as separate reports; component
runs never claim to prove native GCP/Cloudflare/browser custody.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from sqlalchemy import text

from app.modules.host_agent.application.auth_routes import (
    ADMIN_H05_ROUTES,
    SharedIdentityManifest,
    WorkspaceRouteManifest,
    WorkspaceRouteObservation,
)
from app.modules.host_agent.application.ingress import IngressProjection, IngressRecord
from app.modules.host_agent.infrastructure.auth_projection import (
    VerifiedAuthEndpoint,
    auth_config,
)
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.hosted_access.infrastructure.operator_entry import _live_business_readiness
from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
    _capture_cmd,
    _setup_workspace_fixture,
)
from app.platform.hosted_contracts.semantic import semantic_hash

REPO_ROOT = Path(__file__).resolve().parents[4]
APPLICATION_ROOT = REPO_ROOT / "application"
RECOVERY_SPEC_PATH = (
    REPO_ROOT / "docs" / "hosting" / "qualification" / "specifications" / "recovery.json"
)
REQUIRED_LEVELS = frozenset({"component", "docker_linux", "gcp", "deployed_browser"})
REQUIRED_PINS = ("source", "tool", "image", "schema", "workload", "configuration")
CLI_ARGC = 2

# Exact mapping from all 17 recovery.json cases to their owning executable H05 test proofs.
CASE_TEST_MAP: dict[str, tuple[str, str]] = {
    "consistent_scheduled_capture": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_backup_runner_and_alerting.py",
        "test_consistent_scheduled_capture_and_unchanged_file_only_checkpoints",
    ),
    "unchanged_file_only_checkpoints": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_backup_runner_and_alerting.py",
        "test_consistent_scheduled_capture_and_unchanged_file_only_checkpoints",
    ),
    "source_commit_crash": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_backup_runner_and_alerting.py",
        "test_source_commit_crash_reconciliation_and_stale_alerting",
    ),
    "encrypt_key_custody_readback": (
        "apps/server/app/modules/hosted_recovery/tests/test_backup_engine_and_proxy.py",
        "test_chunked_aead_round_trip_dedup_and_readback_verification",
    ),
    "seven_points_incremental_retention": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_backup_runner_and_alerting.py",
        "test_seven_points_incremental_retention_and_failed_readback_protection",
    ),
    "corrupt_missing_object_key": (
        "apps/server/app/modules/hosted_access/tests/test_h05_recovery_security.py",
        "test_tampered_ciphertext_chunk_and_manifest_fail_closed",
    ),
    "admin_outage_independence": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_operator_restore_and_recovery_mode.py",
        "test_admin_outage_independence_and_reconstruct_catalog",
    ),
    "corrupt_business_recovery_mode": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_operator_restore_and_recovery_mode.py",
        "test_corrupt_business_recovery_mode_and_operator_step_up_exact_confirmation",
    ),
    "clean_runtime_repair": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_clean_runtime_repair.py",
        "test_clean_runtime_repair_replaces_only_container_and_retains_state",
    ),
    "operator_step_up_exact_confirmation": (
        "apps/server/app/modules/hosted_access/tests/test_h05_recovery_security.py",
        "test_stolen_or_ordinary_session_cannot_confirm_restore_without_step_up",
    ),
    "cross_workspace_replay_path_key_denial": (
        "apps/server/app/modules/hosted_access/tests/test_h05_recovery_security.py",
        "test_cross_workspace_prefix_key_and_aad_isolation",
    ),
    "crash_safe_locator_switch": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_operator_restore_and_recovery_mode.py",
        "test_crash_safe_locator_switch_rollback_and_healthy_prior_tree",
    ),
    "forensic_prior_tree": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_operator_restore_and_recovery_mode.py",
        "test_corrupt_business_recovery_mode_and_operator_step_up_exact_confirmation",
    ),
    "separate_admin_recovery_loss": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_admin_control_recovery.py",
        "test_separate_admin_recovery_loss_independent_of_main_admin_db",
    ),
    "whole_host_control_loss": (
        "apps/server/app/modules/hosted_recovery/tests/test_h05_admin_control_recovery.py",
        "test_whole_host_control_loss_reconstruction_on_clean_host",
    ),
    "no_offline_workspace_bypass": (
        "apps/server/app/modules/hosted_access/tests/test_h05_recovery_security.py",
        "test_no_offline_workspace_decrypt_or_restore_bypass_and_gateway_negative_gate",
    ),
    "point_age_duration_traffic": (
        "scripts/tests/test_h05_sizing_qualification.py",
        "test_h05_actor_measures_7_captures_and_concurrent_restore",
    ),
}


def load_recovery_spec() -> dict[str, object]:
    return json.loads(RECOVERY_SPEC_PATH.read_text(encoding="utf-8"))


def _run_joint_positive_handoff() -> dict[str, object]:
    """Prove 2 disposable operators unlock desired_state='eligible' once H05 proof passes."""
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="epm-h0511-handoff-") as td:
        root = Path(td).resolve()
        records: list[IngressRecord] = []
        eligible_pairs: list[tuple[WorkspaceRouteObservation, VerifiedAuthEndpoint]] = []
        operators_verified: list[dict[str, object]] = []

        for idx, slug in enumerate(("pilot-alpha", "pilot-beta"), start=1):
            slug_root = root / slug
            slug_root.mkdir(parents=True, exist_ok=True)
            fx = _setup_workspace_fixture(slug_root)
            try:
                with fx["acc_engine"].begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE access_meta SET effective_access = 'enabled', "
                            "subject = :sub WHERE id = 1"
                        ),
                        {"sub": f"sub-{slug}"},
                    )
                # Before capture, live readiness MUST be False.
                assert _live_business_readiness(fx["acc_engine"], fx["service"]) is False
                # Capture verified H05 recovery point.
                actor, cmd = _capture_cmd(f"handoff-{slug}-1")
                fx["service"].execute(actor, cmd)
                snap = fx["service"].read_protection_status()
                assert snap.last_point_id is not None
                assert _live_business_readiness(fx["acc_engine"], fx["service"]) is True

                binding_id = str(uuid4())
                op_id = str(uuid4())
                ws_id = str(uuid4())
                comp_id = str(uuid4())
                ep_id = str(uuid4())
                manifest = WorkspaceRouteManifest(
                    component_id=comp_id,
                    artifact_sha256="a" * 64,
                    private_endpoint_id=ep_id,
                    recovery_proof_ref=f"manifest:{snap.last_point_id}",
                )
                endpoint = VerifiedAuthEndpoint(
                    manifest=manifest,
                    address=f"10.246.0.{10 + idx}",
                    port=8443,
                    tls_name=f"{slug}.internal.invalid",
                )
                obs = WorkspaceRouteObservation(
                    binding_id=binding_id,
                    resource_generation=1,
                    access_epoch=1,
                    workspace_route_state="ready",
                    workspace_manifest_sha256=semantic_hash(manifest),
                    source_identity_proof_ref=f"id-proof:{slug}",
                    resource_readiness_proof_ref=f"manifest:{snap.last_point_id}",
                    verified_recovery_point_id=snap.last_point_id,
                    observed_at=int(time.time() * 1000),
                )
                records.append(
                    IngressRecord(
                        binding_id=binding_id,
                        operator_id=op_id,
                        workspace_id=ws_id,
                        resource_generation=1,
                        public_origin=f"https://{slug}.example.invalid",
                        desired_state="eligible",
                        access_epoch=1,
                        operation_id=str(uuid4()),
                    )
                )
                eligible_pairs.append((obs, endpoint))
                operators_verified.append(
                    {
                        "slug": slug,
                        "protection_state": snap.protection_state,
                        "verified_point_id": snap.last_point_id,
                        "live_readiness": True,
                    }
                )
            finally:
                fx["rec_engine"].dispose()
                fx["acc_engine"].dispose()

        shared_manifest = SharedIdentityManifest(
            component_id=str(uuid4()),
            artifact_sha256="b" * 64,
            private_endpoint_id=str(uuid4()),
            central_origin="https://login.example.invalid",
            admin_origin="https://admin.example.invalid",
            owning_login_origin="https://login.example.invalid",
            route_policy="separate_exact_host_method_allowlists_v3",
            admin_routes=ADMIN_H05_ROUTES,
        )
        shared_ep = VerifiedAuthEndpoint(
            manifest=shared_manifest,
            address="10.246.0.2",
            port=8443,
            tls_name="shared.internal.invalid",
        )
        settings = GatewaySettings(admin_socket=root / "caddy.sock", gateway_uid=1000)
        config = auth_config(
            IngressProjection(records=tuple(records)),
            settings,
            eligible=tuple(eligible_pairs),
            shared=shared_ep,
            login_origin="https://login.example.invalid",
        )
        config_sha = sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    return {
        "status": "passed",
        "operators_verified": operators_verified,
        "admin_route_policy": "separate_exact_host_method_allowlists_v3",
        "eligible_gateway_config_sha256": config_sha,
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def run_component_qualification(*, python_bin: Path | None = None) -> dict[str, object]:
    """Run all 17 recovery.json cases + joint H04/H05 positive handoff at component level."""
    spec = load_recovery_spec()
    py = str(python_bin or (APPLICATION_ROOT / ".venv" / "bin" / "python"))

    # Execute each distinct pytest file once for speed and exact exit-code proof.
    unique_files = sorted({test_file for test_file, _ in CASE_TEST_MAP.values()})
    t0 = time.monotonic()
    proc = subprocess.run(
        [py, "-m", "pytest", *unique_files, "-q"],
        cwd=str(APPLICATION_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    suite_ms = int((time.monotonic() - t0) * 1000)
    passed = proc.returncode == 0
    output_sha = sha256((proc.stdout + proc.stderr).encode("utf-8")).hexdigest()

    cases_report: dict[str, dict[str, object]] = {}
    for case_id in spec["cases"]:
        test_file, test_func = CASE_TEST_MAP[case_id]
        cases_report[case_id] = {
            "status": "passed" if passed else "failed",
            "test_file": test_file,
            "test_function": test_func,
            "evidence_sha256": output_sha,
        }

    handoff = _run_joint_positive_handoff()
    source_sha = sha256(
        (RECOVERY_SPEC_PATH.read_text(encoding="utf-8") + output_sha).encode("utf-8")
    ).hexdigest()

    return {
        "version": 1,
        "proof": "recovery",
        "owner": "H05",
        "revision": spec["revision"],
        "level": "component",
        "platform": platform.system(),
        "status": "passed" if (passed and handoff["status"] == "passed") else "failed",
        "suite_duration_ms": suite_ms,
        "pins": {
            "source": source_sha,
            "tool": f"pytest:{platform.python_version()}",
            "image": "component_local_no_container",
            "schema": "recovery_0001_initial+admin_recovery_0001_initial+access_0001_initial",
            "workload": "two_disposable_operators_plus_admin_control",
            "configuration": "h05_component_recovery_v1",
        },
        "cases": cases_report,
        "joint_h04_h05_positive_handoff": handoff,
    }


def validate_h05_recovery_report(report: dict[str, object]) -> None:
    """Validate an H05 recovery qualification report against docs/.../recovery.json."""
    spec = load_recovery_spec()
    if (
        report.get("version") != spec["version"]
        or report.get("proof") != spec["proof"]
        or report.get("owner") != spec["owner"]
        or report.get("level") not in REQUIRED_LEVELS
    ):
        raise ValueError("Invalid H05 recovery report header or level")
    pins = report.get("pins")
    if not isinstance(pins, dict) or any(not pins.get(k) for k in REQUIRED_PINS):
        raise ValueError("Missing required pins in H05 recovery report")
    cases = report.get("cases")
    if not isinstance(cases, dict):
        raise ValueError("Missing cases map in H05 recovery report")
    expected_cases = list(spec["cases"])
    if set(cases) != set(expected_cases):
        raise ValueError(f"Case set mismatch: missing {set(expected_cases) - set(cases)}")
    for case_id in expected_cases:
        entry = cases[case_id]
        if not isinstance(entry, dict) or entry.get("status") != "passed":
            raise ValueError(f"Recovery case did not pass: {case_id}")
    handoff = report.get("joint_h04_h05_positive_handoff")
    if not isinstance(handoff, dict) or handoff.get("status") != "passed":
        raise ValueError("Joint H04/H05 positive workspace handoff did not pass")
    if report.get("status") != "passed":
        raise ValueError("Overall H05 recovery report status is not passed")


def main() -> None:
    if len(sys.argv) != CLI_ARGC:
        raise SystemExit("Usage: qualify_h05_recovery.py <output-report.json>")
    output_path = Path(sys.argv[1])
    report = run_component_qualification()
    validate_h05_recovery_report(report)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
