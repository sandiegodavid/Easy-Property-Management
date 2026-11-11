"""H01.6 synthetic presentation contracts, not browser/workflow acceptance."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import get_args, get_type_hints

from pydantic import ValidationError
import pytest

from app.bootstrap.hosted_ui_contracts import RULES, validate_fixture_json
from app.modules.hosted_admin.application import pilot_contracts as admin
from app.modules.hosted_admin.application.ui_contracts import (
    AddDraft,
    AdminFilters,
    OperatorSummary,
)
from app.modules.hosted_admin.application.recovery_contracts import AdminRecoveryPort
from app.modules.hosted_access.application.ui_contracts import Recovery
from app.modules.workspace.application.recovery_contracts import WorkspaceRecoveryPort
from app.platform.hosted_contracts.operations import OperationState
from app.platform.hosted_contracts.reads import FreshnessState
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.ui_states import UIAction

APPLICATION = Path(__file__).resolve().parents[5]
FIXTURE_PATH = APPLICATION.parent / "docs/hosting/qualification/fixtures/H01_UI_CONTRACTS.json"
CORPUS = json.loads(FIXTURE_PATH.read_text())
CASES = {item["case_id"]: item for item in CORPUS["cases"]}
FREE_USABLE_BYTES = 50_000_000


def fixture(case_id):
    return deepcopy(CASES[case_id])


def validate_case(case):
    return validate_fixture_json(json.dumps({"version": 1, "cases": [case]})).cases[0].snapshot


def actions_in(value):
    if isinstance(value, dict):
        if "actions" in value:
            yield from value["actions"]
        for child in value.values():
            yield from actions_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from actions_in(child)


@pytest.mark.parametrize("case_id", tuple(CASES))
def test_each_synthetic_surface_round_trips(case_id):
    view = validate_case(fixture(case_id))
    assert validate_fixture_json(json.dumps({"version": 1, "cases": [CASES[case_id]]}))
    assert view.preservation.input_values and view.preservation.focus and view.preservation.scroll
    assert not view.preservation.automatic_command_replay
    assert view.delivery_owner in {"H04", "H05"}


def test_defaults_are_free_empty_and_no_implicit_seed_or_expiry():
    view = validate_case(fixture("admin_add_free_empty_defaults"))
    assert view.draft == AddDraft()
    assert view.draft.initial_data == "empty"
    assert view.draft.seed_bundle == ""
    assert view.draft.plan == "free"
    assert view.draft.usable_bytes == FREE_USABLE_BYTES
    assert admin.CreateAssignment.model_fields["initial_data"].default == view.draft.initial_data
    assert admin.CreateAssignment.model_fields["seed_bundle"].default is None


def test_invalid_form_keeps_raw_input_and_all_field_guidance():
    case = fixture("admin_add_invalid_input_retained")
    view = validate_case(case)
    assert view.draft.email == "not an email"
    assert view.draft.slug == "Invalid Slug"
    assert view.draft.display_name == "  Keep my entered name  "
    assert {issue.field for issue in view.issues} == {"email", "slug"}
    assert view.draft.email != view.draft.email.replace(" ", "")


def test_conflict_retains_edits_and_does_not_adopt_new_revision():
    case = fixture("admin_add_conflict_retains_input")
    view = validate_case(case)
    assert view.expected_revision < view.current_revision
    assert (
        view.draft.model_dump()
        == validate_case(fixture("admin_add_invalid_input_retained")).draft.model_dump()
    )
    case["snapshot"]["current_revision"] = case["snapshot"]["expected_revision"]
    with pytest.raises(ValidationError):
        validate_case(case)


def test_pending_setup_does_not_claim_active_source_access():
    page = validate_case(fixture("admin_list_pending_source_disabled")).directory.data
    row = page.items[0]
    assert (
        row.setup_state == "pending"
        and row.desired_enabled
        and not row.access.data.effective_enabled
    )
    disabled = validate_case(fixture("admin_list_disabled_access")).directory.data.items[0]
    assert disabled.setup_state == "active" and not disabled.desired_enabled
    assert not disabled.access.data.effective_enabled


def test_failed_access_stale_protection_do_not_hide_known_usage():
    row = validate_case(
        fixture("admin_list_independent_failed_access_stale_protection")
    ).directory.data.items[0]
    assert row.access.state == "unavailable" and row.access.data is None
    assert row.usage.state == "ready" and row.usage.data.used_bytes == 0
    assert row.protection.state == "stale" and row.protection.data is not None
    failed = validate_case(fixture("admin_list_unavailable_not_zero"))
    assert failed.directory.state == "failed" and failed.directory.data is None


@pytest.mark.parametrize("state", ["loading", "failed", "unavailable"])
def test_missing_sections_cannot_fabricate_known_zero_rows(state):
    case = fixture("admin_list_pending_source_disabled")
    case["snapshot"]["directory"]["state"] = state
    with pytest.raises(ValidationError):
        validate_case(case)


def test_settings_sections_fail_independently_without_hiding_support():
    view = validate_case(fixture("operator_settings_independent_protection_failure"))
    assert view.usage.state == "ready" and view.protection.state == "failed"
    assert view.support_contact == "support@example.invalid"
    stale = validate_case(fixture("operator_settings_stale_over_allowance_retains_reads"))
    assert stale.usage.data.used_bytes > stale.usage.data.usable_bytes
    assert stale.maintenance.state == "loading"


def test_directory_cursor_keeps_scope_capture_filters_and_bounds():
    first = validate_case(fixture("admin_list_bounded_page_one"))
    second = validate_case(fixture("admin_list_bounded_page_two"))
    assert first.directory.data.continuation == second.query.cursor
    assert first.query.limit == second.query.limit == 1
    assert first.directory.data.items[0].operator_id != second.directory.data.items[0].operator_id
    assert first.directory.data.matching_total == second.directory.data.matching_total
    assert first.directory.data.continuation.context.filter_hash == semantic_hash(AdminFilters())
    reset = validate_case(fixture("admin_list_filter_change_discards_cursor"))
    assert reset.query.cursor is None and reset.filters.search == "new search"


@pytest.mark.parametrize(
    "mutation", ["filter", "capture", "scope", "limit", "over_limit", "polling"]
)
def test_incompatible_continuations_or_unbounded_reads_rejected(mutation):
    case = fixture("admin_list_bounded_page_two")
    view = case["snapshot"]
    if mutation == "filter":
        view["filters"] = {"search": "changed"}
    elif mutation == "capture":
        view["query"]["cursor"]["context"]["as_of"] = 1
    elif mutation == "scope":
        view["query"]["cursor"]["context"]["scope"] = {
            "kind": "workspace",
            "operator_id": CASES["operator_restore_unqualified"]["snapshot"]["scope"][
                "operator_id"
            ],
            "workspace_id": CASES["operator_restore_unqualified"]["snapshot"]["scope"][
                "workspace_id"
            ],
        }
    elif mutation == "limit":
        view["query"]["limit"] = 51
    elif mutation == "over_limit":
        view["directory"]["data"]["items"] *= 2
    else:
        view["source_refresh"] = "poll_every_operator"
    with pytest.raises(ValidationError):
        validate_case(case)


def test_source_refresh_is_an_operation_not_synchronous_per_row_polling():
    view = validate_case(fixture("admin_detail_refresh_is_pending_operation"))
    assert view.refresh_operation.state == OperationState.PENDING
    rule = RULES[UIAction.REFRESH_SOURCE]
    assert rule.port is admin.AdminPort and rule.method == "execute"
    assert rule.payload is admin.RefreshSource and rule.response == "operation"
    assert view.source_refresh == "explicit_async_operation"


@pytest.mark.parametrize(
    "case_id",
    ["admin_add_unknown_requires_original_lookup", "operator_restore_unknown_retains_original"],
)
def test_unknown_response_keeps_original_identity_and_blocks_new_submission(case_id):
    case = fixture(case_id)
    view = validate_case(case)
    assert view.original_outcome.state == OperationState.UNKNOWN
    reference = view.original_outcome.operation
    check = UIAction.CHECK_OPERATION if case_id.startswith("admin_") else UIAction.CHECK_RESTORE
    assert [action.action for action in view.actions if action.enabled] == [check]
    assert RULES[check].identity == "existing_original"
    assert RULES[check].method == "original"
    assert validate_case(case).original_outcome.operation == reference
    for action in case["snapshot"]["actions"]:
        if action["action"] in {UIAction.CREATE_ASSIGNMENT, UIAction.CONFIRM_RESTORE}:
            action.update(enabled=True, reason=None)
    with pytest.raises(ValidationError):
        validate_case(case)


@pytest.mark.parametrize(
    "case_id", ["operator_restore_unqualified", "operator_recovery_mode_auth_unavailable"]
)
def test_unavailable_restore_has_reason_and_no_mutating_controls(case_id):
    view = validate_case(fixture(case_id))
    assert view.state == "unavailable" and view.availability_reason
    assert view.catalog.data is None
    assert not any(action.enabled for action in view.actions)


def test_restore_needs_strong_exact_confirmation_and_cannot_use_admin_approval():
    choose = validate_case(fixture("operator_restore_choose_point_step_up_pending"))
    confirm = validate_case(fixture("operator_restore_exact_confirmation"))
    assert isinstance(confirm, Recovery)
    assert next(g for g in choose.gates if g.name == "strong_step_up").state == "pending"
    assert confirm.selected_point_id and confirm.preview_id and confirm.exact_request_hash
    rule = RULES[UIAction.CONFIRM_RESTORE]
    assert rule.port is WorkspaceRecoveryPort
    assert (
        rule.authority == "operator_strong_step_up" and rule.confirmation == "exact_preview_intent"
    )
    control = RULES[UIAction.CONFIRM_CONTROL_RESTORE]
    assert control.port is AdminRecoveryPort and control.authority == "protected_bootstrap_mfa"
    case = fixture("operator_restore_exact_confirmation")
    case["snapshot"]["gates"][-1].update(state="pending", evidence_ref=None)
    with pytest.raises(ValidationError):
        validate_case(case)


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_deployment",
        "cross_row",
        "control_restore",
        "no_preview",
        "no_identity",
        "no_readiness",
    ],
)
def test_cross_context_and_missing_gates_are_rejected(mutation):
    case = fixture("admin_detail_refresh_is_pending_operation")
    if mutation == "cross_deployment":
        case["snapshot"]["refresh_operation"]["operation"]["deployment_id"] = (
            "00000000-0000-4000-8000-000000000099"
        )
    elif mutation == "cross_row":
        case["snapshot"]["operator"]["operation"]["operation"]["scope"]["operator_id"] = (
            "00000000-0000-4000-8000-000000000099"
        )
    elif mutation == "control_restore":
        case["snapshot"]["actions"] = [{"action": "admin_confirm_control_restore", "enabled": True}]
    elif mutation == "no_readiness":
        case["snapshot"]["readiness"]["data"]["checks"][0].update(
            state="pending", evidence_ref=None
        )
    else:
        case = fixture("operator_restore_exact_confirmation")
        if mutation == "no_preview":
            case["snapshot"]["preview_id"] = None
        else:
            case["snapshot"]["gates"][0].update(state="unavailable", evidence_ref=None)
    with pytest.raises(ValidationError):
        validate_case(case)


def test_all_controls_have_real_owning_ports_and_explicit_delivery_authority():
    assert set(RULES) == set(UIAction)
    for rule in RULES.values():
        assert get_type_hints(getattr(rule.port, rule.method))["return"]
        if rule.payload is not None:
            action_type = get_type_hints(rule.payload)["action"]
            assert len(get_args(action_type)) == 1
        if rule.response == "bounded_read":
            assert rule.method == "observe" and rule.identity == "read_only"
        if rule.method == "original":
            assert rule.identity == "existing_original"
    surfaced = {item["action"] for item in actions_in(CORPUS)}
    assert surfaced == {key.value for key in UIAction} - {
        UIAction.PREVIEW_CONTROL_RESTORE,
        UIAction.CONFIRM_CONTROL_RESTORE,
    }


@pytest.mark.parametrize(
    "mutation", ["paid", "expiry", "scheduler", "idle", "replay", "erase", "duplicate"]
)
def test_pilot_forbidden_controls_or_context_loss_rejected(mutation):
    case = fixture("admin_add_free_empty_defaults")
    view = case["snapshot"]
    if mutation == "paid":
        view["draft"]["plan"] = "paid"
    elif mutation == "expiry":
        view["draft"]["expires_at"] = 123
    elif mutation in {"scheduler", "idle"}:
        view["actions"].append({"action": "operator_" + mutation, "enabled": True})
    elif mutation == "duplicate":
        view["actions"] *= 2
    else:
        view["preservation"] = (
            {"automatic_command_replay": True} if mutation == "replay" else {"input_values": False}
        )
    with pytest.raises(ValidationError):
        validate_case(case)


def test_fixture_composition_is_not_wired_into_current_runtime():
    bootstrap = APPLICATION / "apps/server/app/bootstrap"
    for path in bootstrap.glob("*.py"):
        if path.name == "hosted_ui_contracts.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert "hosted_ui_contracts" not in (node.module or "")
    suite = validate_fixture_json(FIXTURE_PATH.read_bytes())
    assert validate_fixture_json(suite.model_dump_json()) == suite


def test_unknown_usage_is_not_a_known_zero_or_healthy_check():
    view = validate_case(fixture("operator_settings_unknown_usage_not_zero"))
    assert view.usage.data is None
    assert view.usage.freshness.state == FreshnessState.UNKNOWN
    assert view.protection.state == "ready"
    detail = validate_case(fixture("admin_detail_unknown_usage_unavailable_enable"))
    assert detail.operator.usage.freshness.state == FreshnessState.UNKNOWN
    assert detail.operator.usage.data is None


def test_submitting_form_retains_pending_operation_and_disables_another_create():
    view = validate_case(fixture("admin_add_submitting_retains_original"))
    assert view.original_outcome.state == OperationState.PENDING
    assert not next(a for a in view.actions if a.action == UIAction.CREATE_ASSIGNMENT).enabled
    assert view.preservation.input_values and not view.preservation.automatic_command_replay


def test_setup_vocabulary_follows_the_owning_dictionary_not_effective_access():
    dictionary = (APPLICATION.parent / "docs/database/admin-registry.md").read_text()
    row = re.search(r"^\| `setup_state`.*$", dictionary, re.MULTILINE).group(0)
    states = set(re.findall(r"`([a-z_]+)`", row)) - {"setup_state"}
    assert set(get_args(get_type_hints(OperatorSummary)["setup_state"])) == states
    assert set(get_args(get_type_hints(admin.AdminObservation)["setup_state"])) == states
    assert set(get_args(get_type_hints(AdminFilters)["setup_state"])) == states | {"all"}


def test_published_action_map_tracks_typed_bindings():
    table = (FIXTURE_PATH.parent / "ACTION_MAP.md").read_text()
    for key, rule in RULES.items():
        row = next(line for line in table.splitlines() if line.startswith(f"| `{key.value}` |"))
        assert f"`{rule.port.__name__}.{rule.method}`" in row
        assert f"`{rule.authority}`" in row and f"`{rule.confirmation}`" in row
        assert rule.delivery_owner in row


def test_unknown_restore_cannot_substitute_another_intent_hash():
    case = fixture("operator_restore_unknown_retains_original")
    view = validate_case(case)
    assert view.exact_request_hash == view.original_outcome.operation.request_hash
    case["snapshot"]["exact_request_hash"] = "d" * 64
    with pytest.raises(ValidationError):
        validate_case(case)


@pytest.mark.parametrize(
    "case_id", ["admin_list_active_known_usage", "admin_detail_refresh_is_pending_operation"]
)
def test_admin_access_serialization_excludes_private_source_metadata(case_id):
    view = validate_case(fixture(case_id))
    serialized = view.model_dump_json()
    assert '"access_epoch"' not in serialized
    assert '"source_proof_ref"' not in serialized
    row = view.directory.data.items[0] if view.surface == "admin_list" else view.operator
    assert row.access.data.model_dump() == {"effective_enabled": row.access.data.effective_enabled}


@pytest.mark.parametrize("field", ["access_epoch", "source_proof_ref"])
def test_private_access_fields_are_rejected_at_presentation_boundary(field):
    case = fixture("admin_detail_refresh_is_pending_operation")
    case["snapshot"]["operator"]["access"]["data"][field] = (
        7 if field == "access_epoch" else "private-source-evidence"
    )
    with pytest.raises(ValidationError):
        validate_case(case)


@pytest.mark.parametrize("placement", ["actions", "operator_actions"])
@pytest.mark.parametrize("readiness", ["unavailable", "loading", "stale", "refreshing"])
def test_enable_requires_fresh_readiness_in_both_detail_action_groups(placement, readiness):
    case = fixture("admin_detail_refresh_is_pending_operation")
    view = case["snapshot"]
    view["actions"] = [a for a in view["actions"] if a["action"] != UIAction.ENABLE]
    if readiness == "loading":
        view["readiness"] = {"state": "loading"}
    elif readiness == "unavailable":
        view["readiness"] = fixture("admin_detail_unknown_usage_unavailable_enable")["snapshot"][
            "readiness"
        ]
    else:
        view["readiness"]["state"] = readiness
        if readiness == "stale":
            view["readiness"]["freshness"]["state"] = "stale"
    group = view["actions"] if placement == "actions" else view["operator"]["actions"]
    group.append({"action": UIAction.ENABLE, "enabled": True})
    with pytest.raises(ValidationError, match="Enable requires complete fresh readiness"):
        validate_case(case)


@pytest.mark.parametrize("enabled", [False, True])
def test_nested_enable_is_valid_only_with_ready_evidence_or_disabled_control(enabled):
    case_id = (
        "admin_detail_refresh_is_pending_operation"
        if enabled
        else "admin_detail_unknown_usage_unavailable_enable"
    )
    case = fixture(case_id)
    case["snapshot"]["actions"] = [
        a for a in case["snapshot"]["actions"] if a["action"] != UIAction.ENABLE
    ]
    case["snapshot"]["operator"]["actions"].append(
        {
            "action": UIAction.ENABLE,
            "enabled": enabled,
            "reason": None if enabled else "readiness_unavailable",
        }
    )
    assert validate_case(case)


@pytest.mark.parametrize("case_id", ["admin_list_active_known_usage", "admin_list_disabled_access"])
def test_list_row_enable_has_no_readiness_evidence_and_cannot_be_enabled(case_id):
    case = fixture(case_id)
    row = case["snapshot"]["directory"]["data"]["items"][0]
    row["actions"].append({"action": UIAction.ENABLE, "enabled": True})
    with pytest.raises(ValidationError, match="Enable requires complete fresh readiness"):
        validate_case(case)
    row["actions"][-1].update(enabled=False, reason="review_readiness_in_detail")
    assert validate_case(case)


@pytest.mark.parametrize("operation_state", ["pending", "running"])
def test_inflight_add_submission_rejects_a_new_create_identity(operation_state):
    case = fixture("admin_add_submitting_retains_original")
    view = case["snapshot"]
    view["original_outcome"]["state"] = operation_state
    original = deepcopy(view["original_outcome"]["operation"])
    create = next(a for a in view["actions"] if a["action"] == UIAction.CREATE_ASSIGNMENT)
    create.update(enabled=True, reason=None)
    with pytest.raises(ValidationError, match="Unresolved submission"):
        validate_case(case)
    create.update(enabled=False, reason="submission_pending")
    view["actions"].append({"action": UIAction.RETRY_OPERATION, "enabled": True})
    checked = validate_case(case)
    assert checked.original_outcome.operation.model_dump(mode="json") == original
    for action in checked.actions:
        if action.enabled:
            assert RULES[action.action].identity == "existing_original"
