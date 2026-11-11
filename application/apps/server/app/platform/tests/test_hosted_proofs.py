"""H01.5 report/harness contracts, not actual native/cloud qualification."""

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError
import pytest

from app.platform.hosted_proofs import cli
from app.platform.hosted_proofs.models import (
    CaseResult,
    Environment,
    Evidence,
    Invocation,
    Level,
    Pin,
    PinKind,
    Proof,
    ProofReport,
    Result,
    Specification,
    combined_status,
    validate_report,
)

APPLICATION = Path(__file__).resolve().parents[5]
SPECIFICATIONS = APPLICATION.parent / "docs/hosting/qualification/specifications"
SPEC_FILES = tuple(sorted(SPECIFICATIONS.glob("*.json")))


def specification(path=SPECIFICATIONS / "image_schema.json"):
    raw = path.read_bytes()
    return Specification.model_validate_json(raw), sha256(raw).hexdigest()


def report_for(path=SPECIFICATIONS / "image_schema.json", status=Result.PASSED):
    spec, digest = specification(path)
    ran = status in {Result.PASSED, Result.FAILED}
    level = spec.levels[0]
    linux = level in {Level.NATIVE, Level.DOCKER, Level.GCP}
    proof_evidence = (
        (Evidence(evidence_id="fixture-evidence", artifact_ref="synthetic-only", sha256="b" * 64),)
        if ran
        else ()
    )
    pins = tuple(
        Pin(
            reference="fixture-" + kind.value,
            kind=kind,
            state="pinned" if ran else "unavailable",
            sha256="a" * 64 if ran else None,
            reason=None if ran else "Fixture only; executor unavailable.",
        )
        for kind in spec.required_pins
    )
    invocation = (
        Invocation(
            driver_ref="synthetic-test-driver",
            input_manifest_ref="synthetic-input",
            input_manifest_sha256="c" * 64,
            phase="run",
            repetition=1,
        )
        if ran
        else None
    )
    return ProofReport(
        report_id="00000000-0000-4000-8000-000000000001",
        proof=spec.proof,
        owner=spec.owner,
        specification_sha256=digest,
        specification_revision=spec.revision,
        source_commit="1" * 40 if ran else None,
        source_dirty=False if ran else None,
        recorded_at=3,
        started_at=1 if ran else None,
        finished_at=2 if ran else None,
        environment=Environment(
            level=level,
            os="linux" if linux else "darwin",
            architecture="fixture-arm64",
            machine_ref="synthetic-not-a-real-machine",
            kernel="fixture-kernel" if linux else None,
            filesystem="fixture-ext4" if linux else None,
            container_runtime="fixture-docker" if level in {Level.DOCKER, Level.GCP} else None,
            provider_configuration_ref="fixture-provider"
            if level in {Level.GCP, Level.BROWSER}
            else None,
        ),
        invocation=invocation,
        pins=pins,
        evidence=proof_evidence,
        cases=tuple(
            CaseResult(
                case_id=case,
                status=status,
                observation="Synthetic contract fixture only.",
                evidence_ids=("fixture-evidence",) if ran else (),
            )
            for case in spec.cases
        ),
        status=status,
        remaining_limits=("Synthetic contract fixture; no native/provider acceptance.",),
    )


@pytest.mark.parametrize("path", SPEC_FILES, ids=lambda p: p.stem)
@pytest.mark.parametrize("status", tuple(Result))
def test_each_specification_and_scoped_report_round_trip(path, status):
    spec, digest = specification(path)
    report = report_for(path, status)
    decoded = ProofReport.model_validate_json(report.model_dump_json())
    validate_report(spec, digest, decoded)
    assert decoded == report
    assert all(case in path.with_suffix(".md").read_text() for case in spec.cases)


def test_specifications_cover_every_h01_proof_once():
    assert {specification(path)[0].proof for path in SPEC_FILES} == set(Proof)
    assert len(SPEC_FILES) == len(Proof)
    for path in SPEC_FILES:
        spec, _ = specification(path)
        assert set(spec.required_pins) == set(PinKind)


@pytest.mark.parametrize("status", [Result.NOT_RUN, Result.UNAVAILABLE, Result.FAILED])
def test_nonpasses_cannot_be_labelled_passed(status):
    values = report_for(status=status).model_dump()
    values["status"] = Result.PASSED
    with pytest.raises(ValidationError):
        ProofReport(**values)


@pytest.mark.parametrize("case_status", [Result.NOT_RUN, Result.UNAVAILABLE, Result.FAILED])
def test_partial_results_cannot_look_complete(case_status):
    values = report_for().model_dump()
    values["cases"][0]["status"] = case_status
    values["status"] = combined_status({Result.PASSED, case_status})
    assert ProofReport(**values).status != Result.PASSED
    values["status"] = Result.PASSED
    with pytest.raises(ValidationError):
        ProofReport(**values)


@pytest.mark.parametrize(
    "field", ["source_commit", "source_dirty", "invocation", "started_at", "finished_at"]
)
def test_executed_results_need_actual_inputs_and_times(field):
    values = report_for().model_dump()
    values[field] = None
    with pytest.raises(ValidationError):
        ProofReport(**values)


@pytest.mark.parametrize(
    "mutation",
    [
        "case_omitted",
        "extra_case",
        "wrong_spec",
        "wrong_revision",
        "wrong_owner",
        "missing_pin",
        "unavailable_pin",
    ],
)
def test_report_must_pin_exact_spec_and_all_negative_controls(mutation):
    spec, digest = specification()
    values = report_for().model_dump()
    if mutation == "case_omitted":
        values["cases"] = values["cases"][1:]
    elif mutation == "extra_case":
        values["cases"] = (*values["cases"], {**values["cases"][0], "case_id": "not_registered"})
    elif mutation == "wrong_spec":
        values["specification_sha256"] = "0" * 64
    elif mutation == "wrong_revision":
        values["specification_revision"] = 2
    elif mutation == "wrong_owner":
        values["owner"] = "H05"
    elif mutation == "missing_pin":
        values["pins"] = values["pins"][1:]
    else:
        values["pins"][0].update(state="unavailable", sha256=None, reason="Unknown source.")
    with pytest.raises(ValueError):
        validate_report(spec, digest, ProofReport(**values))


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_case",
        "duplicate_pin",
        "duplicate_evidence",
        "unknown_evidence",
        "backwards_time",
        "unrun_metric",
        "unrun_time",
    ],
)
def test_malformed_history_and_fabricated_measurements_rejected(mutation):
    values = report_for().model_dump()
    if mutation == "duplicate_case":
        values["cases"] = (*values["cases"], values["cases"][0])
    elif mutation == "duplicate_pin":
        values["pins"] = (*values["pins"], values["pins"][0])
    elif mutation == "duplicate_evidence":
        values["evidence"] = (*values["evidence"], values["evidence"][0])
    elif mutation == "unknown_evidence":
        values["cases"][0]["evidence_ids"] = ("does-not-exist",)
    elif mutation == "backwards_time":
        values["finished_at"] = 0
    elif mutation == "unrun_time":
        values = report_for(status=Result.NOT_RUN).model_dump()
        values["started_at"] = 1
    else:
        values = report_for(status=Result.NOT_RUN).model_dump()
        values["cases"][0]["metrics"] = ({"name": "invented", "value": 1, "unit": "count"},)
    with pytest.raises(ValidationError):
        ProofReport(**values)


@pytest.mark.parametrize("level", [Level.NATIVE, Level.DOCKER, Level.GCP])
def test_mac_fixture_cannot_claim_executed_linux_result(level):
    values = report_for(SPECIFICATIONS / "runtime_limits.json").model_dump()
    values["environment"].update(level=level, os="darwin")
    with pytest.raises(ValidationError):
        ProofReport(**values)


def test_unavailable_native_report_on_mac_is_explicit_not_a_pass():
    path = SPECIFICATIONS / "runtime_limits.json"
    values = report_for(path, Result.UNAVAILABLE).model_dump()
    values["environment"].update(os="darwin", kernel=None, filesystem=None)
    validate_report(*specification(path), ProofReport(**values))


def test_spec_and_pin_bounds_and_unresolved_images():
    spec, _ = specification()
    with pytest.raises(ValidationError):
        Specification(**{**spec.model_dump(), "cases": (*spec.cases, spec.cases[0])})
    with pytest.raises(ValidationError):
        Pin(reference="image", kind=PinKind.IMAGE, state="pinned", sha256=None, reason=None)
    with pytest.raises(ValidationError):
        ProofReport(**{**report_for().model_dump(), "provider_token": "synthetic-forbidden"})


@pytest.mark.parametrize("status", tuple(Result))
def test_cli_validates_without_promoting_acceptance(status, tmp_path, capsys):
    path = tmp_path / "report.json"
    path.write_text(report_for(status=status).model_dump_json())
    before = path.read_bytes()
    result = cli.main(
        ["validate", "--spec", str(SPECIFICATIONS / "image_schema.json"), "--report", str(path)]
    )
    assert result == (0 if status == Result.PASSED else 2)
    assert "no gate is enabled" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_executor_unavailable_before_input_read_or_output_creation(tmp_path, monkeypatch, capsys):
    def forbidden(*_args):
        pytest.fail("Unavailable executor must not read any supplied document.")

    monkeypatch.setattr(cli, "load_document", forbidden)
    output = tmp_path / "not-created" / "report.json"
    result = cli.main(
        ["execute", "--spec", "/not-read", "--inputs", "/not-read", "--output", str(output)]
    )
    assert result == cli.EXECUTOR_UNAVAILABLE
    assert "proof_executor_unavailable" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "content",
    [b"{unsafe_marker", b"x" * (cli.MAX_DOCUMENT_BYTES + 1), b"[" * 2000 + b"]" * 2000],
)
def test_invalid_oversize_documents_do_not_echo_contents(content, tmp_path, capsys):
    path = tmp_path / "sensitive-file.json"
    path.write_bytes(content)
    assert cli.main(["describe", "--spec", str(path)]) == 1
    out = capsys.readouterr().out
    assert "unsafe_marker" not in out and str(path) not in out


def test_actual_read_only_module_entry_point_from_other_directory(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(APPLICATION / "apps/server")}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.platform.hosted_proofs",
            "describe",
            "--spec",
            str(SPEC_FILES[0]),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "no proof executed" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_package_has_no_executor_cloud_database_or_shell_dependencies():
    package = APPLICATION / "apps/server/app/platform/hosted_proofs"
    forbidden = {"subprocess", "socket", "boto3", "docker", "sqlalchemy", "alembic", "fastapi"}
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & forbidden
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
                assert not (node.module or "").startswith("app.modules.")


def test_duplicate_json_fields_do_not_shadow_result(tmp_path, capsys):
    path = tmp_path / "conflicting.json"
    original = report_for().model_dump_json()
    path.write_text(original[:-1] + ',"status":"passed"}')
    assert (
        cli.main(
            ["validate", "--spec", str(SPECIFICATIONS / "image_schema.json"), "--report", str(path)]
        )
        == 1
    )
    assert "proof_document_invalid" in capsys.readouterr().out


@pytest.mark.parametrize(
    "change", ["component_promotion", "wrong_level", "missing_container", "missing_provider"]
)
def test_proof_scopes_and_environment_prerequisites_cannot_be_promoted(change):
    spec_path = SPECIFICATIONS / "runtime_limits.json"
    values = report_for(spec_path).model_dump()
    if change == "component_promotion":
        values["environment"].update(level=Level.COMPONENT, os="darwin")
    elif change == "wrong_level":
        values["environment"].update(level=Level.BROWSER, provider_configuration_ref="fixture")
    else:
        values["environment"].update(
            level=Level.GCP, container_runtime="fixture", provider_configuration_ref="fixture"
        )
        key = "container_runtime" if change == "missing_container" else "provider_configuration_ref"
        values["environment"][key] = None
    with pytest.raises(ValueError):
        validate_report(*specification(spec_path), ProofReport(**values))


def test_strict_version_and_required_limit_statement():
    values = report_for().model_dump()
    values["version"] = True
    with pytest.raises(ValidationError):
        ProofReport(**values)
    values = json.loads(report_for().model_dump_json())
    values["remaining_limits"] = []
    with pytest.raises(ValidationError):
        ProofReport.model_validate_json(json.dumps(values))
