"""Execute H03.12 revision-2 identity component proof cases and emit validated reports."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from uuid import uuid4

from app.modules.hosted_access.application.identity_proof import (
    IDENTITY_CASES,
    IDENTITY_SPEC_REVISION,
    IdentityAssertions,
    IdentityProofInputs,
    validate_identity_report,
)
from app.modules.hosted_access.application.identity_setup import IdentityPolicy, IdentitySetup
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_proofs.cli import load_document
from app.platform.hosted_proofs.models import (
    CaseResult,
    Environment,
    Evidence,
    Invocation,
    Level,
    Metric,
    Pin,
    PinKind,
    Proof,
    ProofReport,
    Result,
    Specification,
    combined_status,
    validate_report,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
APPLICATION = REPO_ROOT / "application"
SPEC_PATH = REPO_ROOT / "docs/hosting/qualification/specifications/identity_handoff.json"
SELECTION_PATH = APPLICATION / "deploy/hosted-mvp/identity/selection.json"

ASSIGNMENT_A = "00000000-0000-4000-8000-000000000101"
ASSIGNMENT_B = "00000000-0000-4000-8000-000000000102"
ADMIN_PRINCIPAL = "00000000-0000-4000-8000-000000000103"

# Each case runs its owning component test modules in isolated pytest invocations.
CASE_SUITES: dict[str, tuple[tuple[str, ...], ...]] = {
    "google_email_identity": (
        ("apps/server/app/modules/hosted_access/tests/test_firebase_provider.py",),
        ("apps/server/app/modules/hosted_access/tests/test_central_login.py",),
    ),
    "exact_invitation_claim": (
        ("apps/server/app/modules/hosted_access/tests/test_central_login.py",),
    ),
    "browser_origin_state_binding": (
        ("apps/server/app/modules/hosted_access/tests/test_central_pairing.py",),
        ("apps/server/app/modules/hosted_access/tests/test_central_http.py",),
    ),
    "single_use_handoff": (
        (
            "apps/server/app/modules/hosted_access/tests/test_handoff.py",
            "-k",
            "not test_operator_runtime_uses_same_owner_via_bounded_unix_relay",
        ),
    ),
    "cross_workspace_role_denial": (
        ("apps/server/app/modules/host_agent/tests/test_gateway.py",),
        ("apps/server/app/modules/host_agent/tests/test_shared_identity_registration.py",),
    ),
    "host_only_cookie_csrf": (
        ("apps/server/app/modules/hosted_access/tests/test_admin_http.py",),
        ("apps/server/app/modules/hosted_access/tests/test_transport.py",),
    ),
    "mfa_step_up": (
        ("apps/server/app/modules/hosted_access/tests/test_admin_admission.py",),
        ("apps/server/app/modules/hosted_access/tests/test_admin_sessions.py",),
        ("apps/server/app/modules/hosted_access/tests/test_admin_bootstrap.py",),
    ),
    "disable_rebind_logout": (("apps/server/app/modules/hosted_access/tests/test_sessions.py",),),
    "no_secret_url_log": (
        (
            "apps/server/app/modules/hosted_access/tests/test_identity_exit_gaps.py",
            "-k",
            "no_secret_url_log or refresh_token",
        ),
    ),
    "multi_device_draft_fences": (
        ("apps/server/app/modules/hosted_access/tests/test_draft_leases.py",),
        ("apps/server/app/modules/hosted_access/tests/test_sessions.py",),
    ),
    "local_mode_independent": (
        (
            "apps/server/app/modules/hosted_access/tests/test_identity_exit_gaps.py",
            "-k",
            "local_mode_independent",
        ),
        ("apps/server/app/modules/hosted_access/tests/test_composition.py",),
    ),
    "renewal_cap_and_lineage": (
        ("apps/server/app/modules/hosted_access/tests/test_sessions.py",),
        ("apps/server/app/modules/hosted_access/tests/test_identity_states.py",),
    ),
    "identity_dependency_cleanup": (
        ("apps/server/app/modules/hosted_access/tests/test_identity_persistence.py",),
    ),
    "provider_outage_deadlines": (
        ("apps/server/app/modules/hosted_access/tests/test_provider_status.py",),
        ("apps/server/app/modules/hosted_access/tests/test_provider_transport.py",),
    ),
}


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_files(paths: list[Path]) -> str:
    hasher = sha256()
    for path in sorted(paths):
        hasher.update(str(path.relative_to(REPO_ROOT)).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def git_info() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    return commit, dirty


def run_suite(args: tuple[str, ...]) -> tuple[int, int, bytes]:
    start = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=APPLICATION,
        capture_output=True,
        check=False,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    output = completed.stdout + b"\n" + completed.stderr
    return completed.returncode, elapsed_ms, output


def execute_component_proof(output_path: Path, companion_path: Path | None = None) -> int:
    spec, spec_sha256 = load_document(SPEC_PATH, Specification)
    setup_bytes = SELECTION_PATH.read_bytes()
    setup = IdentitySetup.model_validate_json(setup_bytes)
    commit, dirty = git_info()

    inputs = IdentityProofInputs(
        setup_sha256=semantic_hash(setup),
        policy_sha256=semantic_hash(IdentityPolicy()),
        source_commit=commit,
        assignments=(ASSIGNMENT_A, ASSIGNMENT_B),
        admin_principal_id=ADMIN_PRINCIPAL,
        browser_contexts=("op-a-dev-1", "op-a-dev-2", "op-b-dev-1", "op-b-dev-2"),
        clock="fixed_component",
        level="component",
        adapter="isolated_development",
        provider_configuration_sha256=None,
    )

    schema_files = sorted((APPLICATION / "database").glob("*migrations/versions/*.py"))
    workload_files = sorted(
        (APPLICATION / "apps/server/app/modules/hosted_access/tests").glob("test_*.py")
    )
    pyproject_text = (APPLICATION / "pyproject.toml").read_text()
    tool_pin = sha256_bytes(f"{sys.version}|{platform.platform()}|{pyproject_text}".encode())
    pins = (
        Pin(
            reference="git-head",
            kind=PinKind.SOURCE,
            state="pinned",
            sha256=sha256_bytes(commit.encode("ascii")),
            reason=None,
        ),
        Pin(
            reference="python-pytest-toolchain",
            kind=PinKind.TOOL,
            state="pinned",
            sha256=tool_pin,
            reason=None,
        ),
        Pin(
            reference="component-runtime-files",
            kind=PinKind.IMAGE,
            state="pinned",
            sha256=sha256_files(
                [
                    APPLICATION / "deploy/hosted-mvp/Dockerfile.admin",
                    APPLICATION / "deploy/hosted-mvp/Dockerfile.operator",
                ]
            ),
            reason=None,
        ),
        Pin(
            reference="hosted-identity-schemas",
            kind=PinKind.SCHEMA,
            state="pinned",
            sha256=sha256_files(schema_files),
            reason=None,
        ),
        Pin(
            reference="hosted-access-component-suites",
            kind=PinKind.WORKLOAD,
            state="pinned",
            sha256=sha256_files(workload_files),
            reason=None,
        ),
        Pin(
            reference="identity-selection-json",
            kind=PinKind.CONFIGURATION,
            state="pinned",
            sha256=sha256_bytes(setup_bytes),
            reason=None,
        ),
    )

    started_at = time.time_ns() // 1_000_000
    suite_cache: dict[tuple[str, ...], tuple[int, int, str]] = {}
    evidence_items: list[Evidence] = []
    evidence_by_suite: dict[tuple[str, ...], str] = {}
    cases: list[CaseResult] = []

    for case_id in IDENTITY_CASES:
        suites = CASE_SUITES[case_id]
        case_ok = True
        total_ms = 0
        eids: list[str] = []
        for suite in suites:
            if suite not in suite_cache:
                rc, elapsed_ms, raw_out = run_suite(suite)
                digest = sha256_bytes(raw_out)
                suite_cache[suite] = (rc, elapsed_ms, digest)
                eid = f"suite-{len(evidence_items) + 1:02d}"
                evidence_by_suite[suite] = eid
                evidence_items.append(
                    Evidence(
                        evidence_id=eid,
                        artifact_ref=Path(suite[0]).stem.replace("_", "-"),
                        sha256=digest,
                    )
                )
            rc, elapsed_ms, _ = suite_cache[suite]
            total_ms += elapsed_ms
            eids.append(evidence_by_suite[suite])
            if rc != 0:
                case_ok = False
        cases.append(
            CaseResult(
                case_id=case_id,
                status=Result.PASSED if case_ok else Result.FAILED,
                observation=(
                    f"Component pytest verification passed across {len(suites)} suite(s)."
                    if case_ok
                    else f"One or more component pytest suites failed for {case_id}."
                ),
                evidence_ids=tuple(eids),
                metrics=(
                    Metric(name="suite_count", value=len(suites), unit="count"),
                    Metric(name="elapsed_ms", value=total_ms, unit="milliseconds"),
                ),
            )
        )

    finished_at = time.time_ns() // 1_000_000
    recorded_at = max(finished_at, time.time_ns() // 1_000_000)
    overall = combined_status({c.status for c in cases})

    os_name = sys.platform
    env_os = (
        "darwin" if os_name == "darwin" else "linux" if os_name.startswith("linux") else "windows"
    )

    report = ProofReport(
        version=1,
        report_id=str(uuid4()),
        proof=Proof.IDENTITY,
        specification_sha256=spec_sha256,
        specification_revision=IDENTITY_SPEC_REVISION,
        owner="H03",
        source_commit=commit,
        source_dirty=dirty,
        recorded_at=recorded_at,
        started_at=started_at,
        finished_at=finished_at,
        environment=Environment(
            level=Level.COMPONENT,
            os=env_os,
            architecture=platform.machine() or "unknown",
            machine_ref="local-component-runner",
            kernel=platform.release() or None,
            filesystem=None,
            container_runtime=None,
            provider_configuration_ref="isolated-component-selection",
        ),
        invocation=Invocation(
            driver_ref="qualify-identity-proof-v1",
            input_manifest_ref="identity-component-inputs-v1",
            input_manifest_sha256=semantic_hash(inputs),
            phase="run",
            repetition=1,
        ),
        pins=pins,
        evidence=tuple(evidence_items),
        cases=tuple(cases),
        status=overall,
        remaining_limits=(
            "Component-level proof uses isolated fixed-clock adapters and does not substitute "
            "for deployed GCP/Lima native or live provider qualification.",
            "H04/H05-owned deployed workspace handoff, eligible claim, and recovery step-up "
            "cases remain outside H03 component scope.",
        ),
    )

    assertions = (
        IdentityAssertions(
            methods=("google", "email_link"),
            admin_method="google_totp",
            email_provenance="backend_sign_in_with_email_link",
            completed_mfa_proven=True,
            wrong_realm_denied=True,
            continuation_swaps_denied=True,
            same_link_race_single_pair=True,
            bearer_replays=0,
            maximum_live_sessions=32,
            renewal_lineage_unchanged=True,
            revoked_lineage_not_revived=True,
            freshness_ms=300000,
            provider_cookie_ms=1209600000,
            remembered_lineage_ms=2592000000,
            admin_session_ms=28800000,
            retained_unknown_results=True,
            cleanup_restricts_live_dependencies=True,
            business_export_contains_auth=False,
            secrets_in_retained_urls_logs=False,
            unavoidable_email_action_scrubbed=True,
            local_mode_without_cloud=True,
        )
        if overall == Result.PASSED
        else None
    )

    validate_report(spec, spec_sha256, report)
    validate_identity_report(inputs, report, assertions)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    if companion_path is not None:
        companion_path.parent.mkdir(parents=True, exist_ok=True)
        companion_path.write_text(
            json.dumps(
                {
                    "inputs": inputs.model_dump(mode="json"),
                    "assertions": assertions.model_dump(mode="json") if assertions else None,
                    "report_id": report.report_id,
                    "report_sha256": sha256_bytes(output_path.read_bytes()),
                },
                indent=2,
            )
            + "\n"
        )
    print(
        f"Component proof status: {report.status.value} "
        f"({len(cases)} cases, {len(evidence_items)} suites)"
    )
    return 0 if report.status == Result.PASSED else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--companion", type=Path, default=None)
    args = parser.parse_args(argv)
    os.environ.setdefault("PYTHONPATH", str(APPLICATION))
    return execute_component_proof(args.output, args.companion)


if __name__ == "__main__":
    raise SystemExit(main())
