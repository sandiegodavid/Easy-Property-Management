"""Identity assertion shape tests. No managed-provider or deployed-browser executions."""

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.modules.hosted_access.application.identity_api import (
    AdminSession,
    CompleteHandoff,
    CurrentSession,
    SessionDevices,
    StartLogin,
)
from app.modules.hosted_access.application.identity_evidence import (
    IdentityCommandResult,
    IdentityCommandState,
)
from app.modules.hosted_access.application.identity_proof import (
    IdentityAssertions,
    IdentityProofInputs,
    IDENTITY_CASES,
    IDENTITY_SPEC_REVISION,
    validate_identity_report,
)
from app.modules.hosted_access.application.identity_setup import IdentityPolicy
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_proofs.models import (
    CaseResult,
    Environment,
    Level,
    Proof,
    ProofReport,
    Result,
)

ID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
HASH = "a" * 64
SOURCE = "b" * 40


def inputs(**changes):
    return IdentityProofInputs(
        **(
            dict(
                setup_sha256=HASH,
                policy_sha256=semantic_hash(IdentityPolicy()),
                source_commit=SOURCE,
                assignments=(ID, OTHER),
                admin_principal_id=ID,
                browser_contexts=("a-1", "a-2", "b-1", "b-2"),
                clock="fixed_component",
                level="component",
                adapter="isolated_development",
                provider_configuration_sha256=None,
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"assignments": (ID, ID)},
        {"browser_contexts": ("a", "b", "c", "a")},
        {"policy_sha256": "c" * 64},
        {"level": "deployed_browser"},
        {"adapter": "managed_provider"},
        {"source_commit": "tag:latest"},
        {"provider_token": "secret"},
    ],
)
def test_incomplete_or_mixed_proof_inputs_reject(changes):
    with pytest.raises(ValidationError):
        inputs(**changes)


def assertions(**changes):
    return IdentityAssertions(
        **(
            dict(
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
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"methods": ("google", "password")},
        {"completed_mfa_proven": False},
        {"bearer_replays": 1},
        {"maximum_live_sessions": 33},
        {"freshness_ms": 300001},
        {"provider_cookie_ms": 1209600001},
        {"remembered_lineage_ms": 2592000001},
        {"admin_session_ms": 28800001},
        {"retained_unknown_results": False},
        {"business_export_contains_auth": True},
        {"secrets_in_retained_urls_logs": True},
    ],
)
def test_unqualified_observations_cannot_claim_an_identity_pass(changes):
    with pytest.raises(ValidationError):
        assertions(**changes)


def unavailable():
    return ProofReport(
        report_id=ID,
        proof=Proof.IDENTITY,
        specification_sha256=HASH,
        specification_revision=2,
        owner="H03",
        source_commit=None,
        source_dirty=None,
        recorded_at=1,
        started_at=None,
        finished_at=None,
        environment=Environment(
            level=Level.COMPONENT,
            os="darwin",
            architecture="arm64",
            machine_ref="component-only",
            kernel=None,
            filesystem=None,
            container_runtime=None,
            provider_configuration_ref=None,
        ),
        invocation=None,
        pins=(),
        evidence=(),
        cases=tuple(
            CaseResult(
                case_id=case,
                status=Result.UNAVAILABLE,
                observation="Owning driver/provider not executed.",
                evidence_ids=(),
            )
            for case in IDENTITY_CASES
        ),
        status=Result.UNAVAILABLE,
        remaining_limits=("Not actual provider, browser, persistence or native qualification.",),
    )


def test_unavailable_report_is_explicit_and_specification_matches_assertions():
    report = unavailable()
    validate_identity_report(inputs(), report, None)
    with pytest.raises(ValueError, match="cannot invent"):
        validate_identity_report(inputs(), report, assertions())
    with pytest.raises(ValueError, match="proof level"):
        validate_identity_report(
            inputs(
                level="deployed_browser",
                clock="actual_provider",
                adapter="managed_provider",
                provider_configuration_sha256=HASH,
            ),
            report,
            None,
        )
    path = (
        Path(__file__).resolve().parents[7]
        / "docs/hosting/qualification/specifications/identity_handoff.json"
    )
    spec = json.loads(path.read_text())
    assert spec["revision"] == IDENTITY_SPEC_REVISION
    assert tuple(spec["cases"]) == IDENTITY_CASES


def command_state(**changes):
    return IdentityCommandState(
        **(
            dict(
                operation_id=ID,
                kind="issue_handoff",
                idempotency_key="original",
                request_hash=HASH,
                operator_id=ID,
                managed_session_id=ID,
                attempt_id=ID,
                access_epoch=1,
                state="pending",
                result=None,
                source_receipt_ref=None,
                created_at=100,
                updated_at=100,
                revision=1,
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"access_epoch": None},
        {"attempt_id": None},
        {"state": "succeeded"},
        {"updated_at": 99},
        {"kind": "provision"},
        {"provider_cookie": "secret"},
    ],
)
def test_identity_receipt_state_and_scope(changes):
    with pytest.raises(ValidationError):
        command_state(**changes)


def test_identity_original_result_is_typed_and_never_appears_while_unknown():
    result = IdentityCommandResult(kind="issue_handoff", result_id=ID, source_receipt_ref=None)
    assert command_state(state="succeeded", result=result).result == result
    with pytest.raises(ValidationError):
        command_state(state="unknown", result=result)
    with pytest.raises(ValidationError):
        command_state(
            state="succeeded",
            result=IdentityCommandResult(kind="claim", result_id=ID, source_receipt_ref=None),
        )


def test_browser_contracts_do_not_accept_authority_or_display_internal_fences():
    start = StartLogin(return_path="/properties", remembered=True)
    with pytest.raises(ValidationError):
        StartLogin(**(start.model_dump() | {"operator_id": ID}))
    complete = CompleteHandoff(attempt_id=ID, handoff_code="s" * 32)
    assert "s" * 32 not in repr(complete)
    assert "s" * 32 not in complete.model_dump_json()
    session = CurrentSession(
        state="workspace_not_ready",
        display_name="Operator",
        expires_at=200,
        renewal_required_at=150,
        remembered_until=300,
        can_use_workspace=False,
        support_contact="help@example.invalid",
    )
    for changes in ({"access_epoch": 1}, {"can_use_workspace": True}, {"renewal_required_at": 201}):
        with pytest.raises(ValidationError):
            CurrentSession(**(session.model_dump() | changes))
    device = dict(
        session_id=ID, current=True, display_label="Browser", last_seen_at=100, expires_at=200
    )
    with pytest.raises(ValidationError):
        SessionDevices(items=(device, device), continuation=None)
    with pytest.raises(ValidationError):
        AdminSession(
            display_name="Admin",
            expires_at=200,
            recent_auth_required=False,
            support_contact="help@example.invalid",
            business_access=True,
        )
