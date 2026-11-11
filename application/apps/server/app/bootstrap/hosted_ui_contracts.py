"""H01.6 fixture composition only; not imported by API/bootstrap runtime.

Application owners keep their DTOs/ports. This composition maps presentation actions
without routing, executing, authenticating or opening any store.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StrictInt, TypeAdapter, model_validator

from app.modules.hosted_admin.application import pilot_contracts as admin
from app.modules.hosted_admin.application import recovery_contracts as control
from app.modules.hosted_admin.application.ui_contracts import (
    AdminAdd,
    AdminDetail,
    AdminList,
    OperatorSummary,
)
from app.modules.hosted_access.application import login_contracts as login
from app.modules.hosted_access.application.source_contracts import SourcePort
from app.modules.hosted_access.application.ui_contracts import Recovery, Settings
from app.modules.workspace.application import recovery_contracts as recovery
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.ui_states import UIAction
from app.platform.hosted_contracts.values import CanonicalId, Contract, SafeCode


@dataclass(frozen=True)
class ActionRule:
    port: type
    method: Literal["execute", "observe", "original"]
    payload: type[SemanticRequest] | None
    delivery_owner: Literal["H03", "H04", "H05"]
    authority: Literal[
        "admin_recent_mfa",
        "current_operator",
        "managed_recent_auth",
        "operator_strong_step_up",
        "protected_bootstrap_mfa",
    ]
    confirmation: Literal["none", "review_form", "explicit_action", "exact_preview_intent"]
    response: Literal["operation", "bounded_read"]
    identity: Literal["new_original", "existing_original", "read_only"]


A = UIAction
RULES = {
    A.CREATE_ASSIGNMENT: ActionRule(
        admin.AdminPort,
        "execute",
        admin.CreateAssignment,
        "H04",
        "admin_recent_mfa",
        "review_form",
        "operation",
        "new_original",
    ),
    A.PROVISION: ActionRule(
        admin.AdminPort,
        "execute",
        admin.Provision,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.CHECK_OPERATION: ActionRule(
        admin.AdminPort,
        "original",
        None,
        "H04",
        "admin_recent_mfa",
        "none",
        "operation",
        "existing_original",
    ),
    A.RETRY_OPERATION: ActionRule(
        admin.AdminPort,
        "execute",
        None,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "existing_original",
    ),
    A.REFRESH_SOURCE: ActionRule(
        admin.AdminPort,
        "execute",
        admin.RefreshSource,
        "H04",
        "admin_recent_mfa",
        "none",
        "operation",
        "new_original",
    ),
    A.REISSUE_INVITATION: ActionRule(
        admin.AdminPort,
        "execute",
        admin.ReissueInvitation,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.DISABLE: ActionRule(
        admin.AdminPort,
        "execute",
        admin.Disable,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.ENABLE: ActionRule(
        admin.AdminPort,
        "execute",
        admin.Enable,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.REBIND: ActionRule(
        admin.AdminPort,
        "execute",
        admin.Rebind,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.PREPARE_RETIREMENT: ActionRule(
        admin.AdminPort,
        "execute",
        admin.PrepareRetirement,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.CONFIRM_RETIREMENT: ActionRule(
        admin.AdminPort,
        "execute",
        admin.ConfirmRetirement,
        "H04",
        "admin_recent_mfa",
        "exact_preview_intent",
        "operation",
        "new_original",
    ),
    A.REPAIR_RUNTIME: ActionRule(
        admin.AdminPort,
        "execute",
        admin.RepairRuntime,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.ANNOUNCE_MAINTENANCE: ActionRule(
        admin.AdminPort,
        "execute",
        admin.AnnounceMaintenance,
        "H04",
        "admin_recent_mfa",
        "review_form",
        "operation",
        "new_original",
    ),
    A.MAINTENANCE_RELEASE: ActionRule(
        admin.AdminPort,
        "execute",
        admin.MaintenanceRelease,
        "H04",
        "admin_recent_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.PREVIEW_CONTROL_RESTORE: ActionRule(
        control.AdminRecoveryPort,
        "execute",
        control.PreviewControlRestore,
        "H05",
        "protected_bootstrap_mfa",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.CONFIRM_CONTROL_RESTORE: ActionRule(
        control.AdminRecoveryPort,
        "execute",
        control.ConfirmControlRestore,
        "H05",
        "protected_bootstrap_mfa",
        "exact_preview_intent",
        "operation",
        "new_original",
    ),
    A.READ_SETTINGS: ActionRule(
        SourcePort, "observe", None, "H04", "current_operator", "none", "bounded_read", "read_only"
    ),
    A.LIST_POINTS: ActionRule(
        recovery.WorkspaceRecoveryPort,
        "observe",
        None,
        "H05",
        "current_operator",
        "none",
        "bounded_read",
        "read_only",
    ),
    A.PREVIEW_RESTORE: ActionRule(
        recovery.WorkspaceRecoveryPort,
        "execute",
        recovery.PreviewRestore,
        "H05",
        "current_operator",
        "review_form",
        "operation",
        "new_original",
    ),
    A.RECENT_AUTHENTICATE: ActionRule(
        login.LoginPort,
        "execute",
        login.RecentAuthenticate,
        "H03",
        "managed_recent_auth",
        "explicit_action",
        "operation",
        "new_original",
    ),
    A.CONFIRM_RESTORE: ActionRule(
        recovery.WorkspaceRecoveryPort,
        "execute",
        recovery.ConfirmRestore,
        "H05",
        "operator_strong_step_up",
        "exact_preview_intent",
        "operation",
        "new_original",
    ),
    A.CHECK_RESTORE: ActionRule(
        recovery.WorkspaceRecoveryPort,
        "original",
        None,
        "H05",
        "current_operator",
        "none",
        "operation",
        "existing_original",
    ),
}

Snapshot = Annotated[
    AdminList | AdminAdd | AdminDetail | Settings | Recovery, Field(discriminator="surface")
]


class FixtureCase(Contract):
    case_id: SafeCode
    deployment_id: CanonicalId
    snapshot: Snapshot


class FixtureSuite(Contract):
    version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    cases: Annotated[tuple[FixtureCase, ...], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def unique_cases_and_actions(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Fixture case IDs must be unique.")
        for case in self.cases:
            validate_snapshot(case)
        return self


def _validate_action_group(value, actions, allowed):
    if len({action.action for action in actions}) != len(actions):
        raise ValueError("A control must not be duplicated within its action row.")
    for action in actions:
        if action.action not in allowed:
            raise ValueError("Action belongs to a different surface/owning workflow.")
        if action.action not in RULES:
            raise ValueError(
                "Every action needs an owning command/authority/confirmation contract."
            )
    if isinstance(value, (AdminAdd, Recovery)) and value.state == "outcome_unknown":
        checks = (
            {A.CHECK_OPERATION, A.RETRY_OPERATION}
            if isinstance(value, AdminAdd)
            else {A.CHECK_RESTORE}
        )
        if any(action.enabled and action.action not in checks for action in actions):
            raise ValueError("Unknown submission can only check/retry its original identity.")


def _validate_admin_operation(value: AdminAdd | OperatorSummary, deployment_id):
    operation = value.original_outcome if isinstance(value, AdminAdd) else value.operation
    if operation is not None and operation.operation.deployment_id != deployment_id:
        raise ValueError("Original operation belongs to another deployment.")
    if isinstance(value, AdminAdd) and operation is not None:
        if (
            operation.operation.kind != "create_assignment"
            or operation.operation.scope.kind != "deployment"
        ):
            raise ValueError("Add form retains only its own original assignment operation.")
    if isinstance(value, OperatorSummary) and operation is not None:
        scope = operation.operation.scope
        if scope.kind == "workspace" and (
            scope.operator_id != value.operator_id or scope.workspace_id != value.workspace_id
        ):
            raise ValueError("Row operation belongs to another operator/workspace.")
    for action in value.actions:
        if (
            action.enabled
            and action.action in {A.CHECK_OPERATION, A.RETRY_OPERATION}
            and operation is None
        ):
            raise ValueError("Checking/retrying requires the original operation reference.")


ADMIN_ACTIONS = frozenset(key for key, rule in RULES.items() if rule.port is admin.AdminPort)


def _validate_list(case: FixtureCase) -> None:
    view = case.snapshot
    if view.query.deployment_id != case.deployment_id:
        raise ValueError("Directory deployment mismatch.")
    _validate_action_group(view, view.actions, {A.CREATE_ASSIGNMENT})
    if view.directory.data is not None:
        for row in view.directory.data.items:
            _validate_action_group(row, row.actions, ADMIN_ACTIONS - {A.CREATE_ASSIGNMENT})
            _validate_admin_operation(row, case.deployment_id)


def _validate_add(case: FixtureCase) -> None:
    view = case.snapshot
    _validate_action_group(
        view, view.actions, {A.CREATE_ASSIGNMENT, A.CHECK_OPERATION, A.RETRY_OPERATION}
    )
    _validate_admin_operation(view, case.deployment_id)


def _validate_detail(case: FixtureCase) -> None:
    view = case.snapshot
    _validate_action_group(view, view.actions, ADMIN_ACTIONS - {A.CREATE_ASSIGNMENT})
    _validate_admin_operation(view.operator, case.deployment_id)
    _validate_action_group(
        view.operator, view.operator.actions, ADMIN_ACTIONS - {A.CREATE_ASSIGNMENT}
    )
    if view.refresh_operation is not None:
        ref = view.refresh_operation.operation
        if (
            ref.deployment_id != case.deployment_id
            or ref.kind != "refresh_source"
            or ref.scope.kind != "workspace"
            or ref.scope.operator_id != view.operator.operator_id
            or ref.scope.workspace_id != view.operator.workspace_id
        ):
            raise ValueError("Refresh must retain the asynchronous source-refresh operation.")
    if any(a.enabled and a.action == A.ENABLE for a in view.actions):
        if view.readiness.state != "ready" or view.readiness.data.state != "ready":
            raise ValueError("Enable requires complete fresh readiness.")


def _validate_settings(case: FixtureCase) -> None:
    _validate_action_group(case.snapshot, case.snapshot.actions, {A.READ_SETTINGS, A.LIST_POINTS})


def _validate_recovery(case: FixtureCase) -> None:
    view = case.snapshot
    allowed = {
        A.LIST_POINTS,
        A.PREVIEW_RESTORE,
        A.RECENT_AUTHENTICATE,
        A.CONFIRM_RESTORE,
        A.CHECK_RESTORE,
    }
    _validate_action_group(view, view.actions, allowed)
    enabled = {a.action for a in view.actions if a.enabled}
    if A.CONFIRM_RESTORE in enabled and view.state != "confirm":
        raise ValueError(
            "Confirm restore is unavailable before exact strong-auth preview/confirmation."
        )
    if view.state == "unavailable" and A.PREVIEW_RESTORE in enabled:
        raise ValueError("Unqualified/unavailable recovery cannot admit a preview.")
    if view.original_outcome is not None:
        ref = view.original_outcome.operation
        if ref.deployment_id != case.deployment_id or ref.kind != "confirm_restore":
            raise ValueError("Restore must retain its own original scoped restore operation.")
    elif A.CHECK_RESTORE in enabled:
        raise ValueError("Checking restore requires its original operation reference.")


def validate_snapshot(case: FixtureCase) -> None:
    handlers = {
        "admin_list": _validate_list,
        "admin_add": _validate_add,
        "admin_detail": _validate_detail,
        "operator_settings": _validate_settings,
        "operator_recovery": _validate_recovery,
    }
    handlers[case.snapshot.surface](case)


def validate_fixture_json(content: str | bytes) -> FixtureSuite:
    if len(content.encode("utf-8") if isinstance(content, str) else content) > 512 * 1024:
        raise ValueError("Fixture corpus exceeds its bound.")
    return TypeAdapter(FixtureSuite).validate_json(content)
