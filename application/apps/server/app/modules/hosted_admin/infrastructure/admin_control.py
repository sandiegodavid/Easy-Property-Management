"""Admin-lite control-plane service implementing AdminPort and set-based projections."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

from app.modules.host_agent.application.capacity import Resources
from app.modules.hosted_admin.application.errors import (
    AdminConflictError,
    AdminDeniedError,
    AdminNotFoundError,
    AdminUnavailableError,
)
from app.modules.hosted_admin.application.pilot_contracts import (
    AdminCommand,
    AdminObservation,
    AdminResult,
    CreateAssignment,
    RefreshSource,
    ReissueInvitation,
    RepairRuntime,
    require_invocation,
)
from app.modules.hosted_admin.application.ui_contracts import (
    Access,
    AdminDetail,
    AdminFilters,
    AdminList,
    OperatorSummary,
    Readiness,
)
from app.modules.hosted_admin.infrastructure.capacity_store import evaluate_admission
from app.modules.hosted_admin.infrastructure.policy_bootstrap import (
    FREE_V1_PLAN_CODE,
    FREE_V1_POLICY_VERSION,
    FREE_V1_USABLE_BYTES,
)
from app.platform.hosted_contracts.authority import (
    AdminAuthority,
    ObservationPage,
    ObservationQuery,
)
from app.platform.hosted_contracts.operations import (
    OperationOutcome,
    OperationReference,
    OperationState,
    SemanticConflict,
)
from app.platform.hosted_contracts.reads import (
    ContinuationCursor,
    CursorContext,
    Freshness,
    FreshnessState,
)
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.ui_states import (
    ActionState,
    FreeUsage,
    Gate,
    Protection,
    Section,
    UIAction,
)
from app.platform.hosted_contracts.values import DeploymentScope, WorkspaceScope
from app.platform.sqlite_engine import immediate_transaction

RECENT_MFA_WINDOW_MS = 900_000
INVITATION_TTL_MS = 7 * 24 * 60 * 60 * 1000
CURSOR_POSITION_PARTS = 2
MAX_SQLITE_INT = (1 << 63) - 1
RESERVED_SLUGS = frozenset(
    {"admin", "login", "api", "www", "mail", "static", "assets", "support", "status"}
)


@dataclass(frozen=True)
class SourceObservationReading:
    """Verified source observation returned by a private relay inspector."""

    effective_enabled: bool
    usage_bytes: int
    usable_bytes: int
    source_revision: int
    observed_at: int


@dataclass(frozen=True)
class IssuedInvitationOutcome:
    """Outcome of explicit invitation issuance, carrying the one-time raw token."""

    outcome: OperationOutcome[AdminResult]
    invitation_id: str | None
    token: SecretStr | None
    expires_at: int | None


@dataclass(frozen=True)
class _AuditEntry:
    actor_ref: str
    action: str
    operator_id: str | None
    operation_id: str | None
    recorded_at: int
    safe_facts: dict


@dataclass(frozen=True)
class _EventEntry:
    operation_id: str
    sequence: int
    event_code: str
    safe_summary: str
    recorded_at: int


@dataclass(frozen=True)
class _AssignmentContext:
    actor: AdminAuthority
    command: AdminCommand
    deployment_id: str
    email_key: str
    reserved: Resources
    snapshot_revision: int
    now: int


SourceInspector = Callable[[str, str, int], SourceObservationReading | None]


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _email_key(issuer: str, email: str) -> str:
    return f"{issuer}:{email.strip().lower()}"


def _op_state_from_setup(setup_state: str) -> str:
    return {
        "pending": "pending",
        "preparing": "pending",
        "ready_for_claim": "ready",
        "active": "active",
        "needs_attention": "pending",
        "retired": "retired",
    }[setup_state]


def _db_kind_for_action(action: str) -> str:
    return "provision" if action == "create_assignment" else action


def _audit(connection: Connection, entry: _AuditEntry) -> None:
    connection.execute(
        text(
            "INSERT INTO main.admin_audit ("
            "audit_id, actor_ref, action, operator_id, operation_id, recorded_at, safe_facts_json"
            ") VALUES ("
            ":audit_id, :actor_ref, :action, :operator_id, :operation_id, :recorded_at, :facts"
            ")"
        ),
        {
            "audit_id": str(uuid4()),
            "actor_ref": entry.actor_ref,
            "action": entry.action,
            "operator_id": entry.operator_id,
            "operation_id": entry.operation_id,
            "recorded_at": entry.recorded_at,
            "facts": json.dumps(entry.safe_facts, sort_keys=True, separators=(",", ":")),
        },
    )


def _event(connection: Connection, entry: _EventEntry) -> None:
    connection.execute(
        text(
            "INSERT INTO main.operation_events ("
            "operation_id, sequence, event_code, safe_summary, recorded_at"
            ") VALUES (:operation_id, :sequence, :event_code, :safe_summary, :recorded_at)"
        ),
        {
            "operation_id": entry.operation_id,
            "sequence": entry.sequence,
            "event_code": entry.event_code,
            "safe_summary": entry.safe_summary,
            "recorded_at": entry.recorded_at,
        },
    )


def _outcome_from_row(row, *, deployment_id: str) -> OperationOutcome[AdminResult]:
    request_data = json.loads(row["request_json"])
    scope_data = request_data.get("scope")
    if isinstance(scope_data, dict) and scope_data.get("kind") == "workspace":
        scope = WorkspaceScope.model_validate(scope_data)
    else:
        scope = DeploymentScope()
    kind = request_data.get("kind") or row["kind"]
    state = OperationState(row["state"])
    result = (
        AdminResult.model_validate_json(row["result_json"])
        if row["result_json"] is not None
        else None
    )
    action_required = (
        "check_original_result"
        if state in {OperationState.UNKNOWN, OperationState.NEEDS_ATTENTION}
        else None
    )
    return OperationOutcome[AdminResult](
        operation=OperationReference(
            deployment_id=deployment_id,
            scope=scope,
            kind=kind,
            operation_id=row["operation_id"],
            idempotency_key=row["idempotency_key"],
            request_hash=row["request_hash"],
        ),
        state=state,
        revision=row["revision"],
        observed_at=row["updated_at"],
        result=result,
        error_code=row["error_code"],
        action_required=action_required,
    )


def _build_list_where(filters: AdminFilters) -> tuple[str, dict[str, object]]:
    clauses = ["1=1"]
    params: dict[str, object] = {}
    if filters.setup_state != "all":
        clauses.append("o.setup_state = :setup_state")
        params["setup_state"] = filters.setup_state
    if filters.access_state == "enabled":
        clauses.append("obs.effective_enabled = 1")
    elif filters.access_state == "disabled":
        clauses.append("obs.effective_enabled = 0")
    elif filters.access_state == "unknown":
        clauses.append("obs.effective_enabled IS NULL")
    if filters.search.strip():
        clauses.append(
            "(lower(o.display_name) LIKE :search OR lower(o.workspace_slug) LIKE :search "
            "OR lower(o.invited_email) LIKE :search)"
        )
        params["search"] = f"%{filters.search.strip().lower()}%"
    return " AND ".join(clauses), params


def _cursor_filter(
    query: ObservationQuery,
    *,
    deployment_id: str,
    filter_hash: str,
    source_revision: str,
    default_as_of: int,
) -> tuple[int, str, dict[str, object]]:
    if query.cursor is None:
        return default_as_of, "", {}
    expected_context = CursorContext(
        deployment_id=deployment_id,
        scope=DeploymentScope(),
        endpoint="admin_operators",
        filter_hash=filter_hash,
        as_of=query.cursor.context.as_of,
        source_revision=source_revision,
        ordering_version=1,
    )
    try:
        query.cursor.require_context(expected_context)
    except ValueError as error:
        raise AdminConflictError("cursor_context_changed", str(error)) from error
    if (
        len(query.cursor.position) != CURSOR_POSITION_PARTS
        or not query.cursor.position[0].isascii()
        or not query.cursor.position[0].isdigit()
    ):
        raise AdminConflictError("cursor_invalid", "Invalid continuation position.")
    cursor_ts = int(query.cursor.position[0])
    if not 0 <= cursor_ts <= MAX_SQLITE_INT:
        raise AdminConflictError("cursor_invalid", "Invalid continuation position.")
    clause = (
        " AND (o.created_at > :cursor_created_at "
        "OR (o.created_at = :cursor_created_at AND o.operator_id > :cursor_operator_id))"
    )
    params = {
        "cursor_created_at": cursor_ts,
        "cursor_operator_id": query.cursor.position[1],
    }
    return query.cursor.context.as_of, clause, params


def _prefixed_operation(
    row, prefix: str, *, deployment_id: str
) -> OperationOutcome[AdminResult] | None:
    if row[f"{prefix}_id"] is None:
        return None
    return _outcome_from_row(
        {
            "operation_id": row[f"{prefix}_id"],
            "operator_id": row["operator_id"],
            "kind": row[f"{prefix}_kind"],
            "idempotency_key": row[f"{prefix}_key"],
            "request_hash": row[f"{prefix}_hash"],
            "request_json": row[f"{prefix}_req_json"],
            "state": row[f"{prefix}_state"],
            "result_json": row[f"{prefix}_res_json"],
            "error_code": row[f"{prefix}_err"],
            "updated_at": row[f"{prefix}_updated"],
            "revision": row[f"{prefix}_rev"],
        },
        deployment_id=deployment_id,
    )


class AdminControlService:
    """Owning Admin-lite control-plane implementation backed by the main Admin DB."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], int],
        issuer: str,
        application_directory: Path,
        source_inspector: SourceInspector | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.issuer = issuer
        self.application_directory = application_directory
        self.source_inspector = source_inspector

    def _verify_actor(
        self, connection: Connection, actor: AdminAuthority, *, now: int, sensitive: bool
    ):
        meta = (
            connection.execute(
                text("SELECT deployment_id, registry_generation FROM main.control_meta WHERE id=1")
            )
            .mappings()
            .one_or_none()
        )
        if meta is None or meta["deployment_id"] != actor.deployment_id:
            raise AdminDeniedError("admin_deployment_mismatch", "Deployment authority mismatch.")
        principal = (
            connection.execute(
                text(
                    "SELECT principal_id, enabled FROM main.admin_principals "
                    "WHERE principal_id = :id"
                ),
                {"id": actor.principal_id},
            )
            .mappings()
            .one_or_none()
        )
        if principal is None or not principal["enabled"]:
            raise AdminDeniedError("admin_principal_disabled", "Admin principal is not enabled.")
        if sensitive and (
            actor.mfa_verified_at > now or now - actor.mfa_verified_at > RECENT_MFA_WINDOW_MS
        ):
            raise AdminDeniedError(
                "admin_recent_mfa_required", "Recent authenticator verification is required."
            )
        return meta

    def _lookup_operation(
        self, connection: Connection, reference: OperationReference
    ) -> OperationOutcome[AdminResult] | None:
        rows = (
            connection.execute(
                text(
                    "SELECT * FROM main.operations "
                    "WHERE operation_id = :op_id OR (kind = :kind AND idempotency_key = :key)"
                ),
                {
                    "op_id": reference.operation_id,
                    "kind": _db_kind_for_action(reference.kind),
                    "key": reference.idempotency_key,
                },
            )
            .mappings()
            .all()
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise SemanticConflict()
        outcome = _outcome_from_row(rows[0], deployment_id=reference.deployment_id)
        if (
            outcome.operation.kind != reference.kind
            or outcome.operation.scope != reference.scope
            or outcome.operation.idempotency_key != reference.idempotency_key
            or outcome.operation.request_hash != reference.request_hash
        ):
            raise SemanticConflict()
        return outcome

    def original(
        self, actor: AdminAuthority, reference: OperationReference
    ) -> OperationOutcome[AdminResult] | None:
        with self.engine.connect() as connection:
            self._verify_actor(connection, actor, now=self.clock(), sensitive=False)
            if actor.deployment_id != reference.deployment_id:
                raise AdminDeniedError("admin_deployment_mismatch", "Deployment mismatch.")
            return self._lookup_operation(connection, reference)

    def execute(
        self, actor: AdminAuthority, command: AdminCommand
    ) -> OperationOutcome[AdminResult]:
        try:
            require_invocation(actor, command)
        except ValueError as error:
            raise AdminDeniedError("admin_invocation_invalid", str(error)) from error
        payload = command.intent.payload
        if isinstance(payload, CreateAssignment):
            return self._create_assignment(actor, command)
        if isinstance(payload, ReissueInvitation):
            return self._reissue_invitation(actor, command).outcome
        if isinstance(payload, RefreshSource):
            return self._refresh_source(actor, command)
        if isinstance(payload, RepairRuntime):
            return self._repair_runtime(actor, command)
        raise AdminDeniedError(
            "admin_action_not_supported", f"Action {payload.action} is not enabled."
        )

    def get_operation_outcome(
        self, actor: AdminAuthority, operation_id: str
    ) -> OperationOutcome[AdminResult] | None:
        """Read an admitted operation's original outcome by operation_id."""
        with self.engine.connect() as connection:
            now = self.clock()
            self._verify_actor(connection, actor, now=now, sensitive=False)
            row = (
                connection.execute(
                    text(
                        "SELECT o.*, op.workspace_id "
                        "FROM main.operations o "
                        "LEFT JOIN main.operators op ON op.operator_id = o.operator_id "
                        "WHERE o.operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return _outcome_from_row(row, deployment_id=actor.deployment_id)

    def _repair_runtime(
        self, actor: AdminAuthority, command: AdminCommand
    ) -> OperationOutcome[AdminResult]:
        payload = command.intent.payload
        assert isinstance(payload, RepairRuntime)
        scope = command.intent.scope
        assert isinstance(scope, WorkspaceScope)
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            self._verify_actor(connection, actor, now=now, sensitive=True)
            retained = self._lookup_operation(connection, command.reference())
            if retained is not None:
                return retained
            operator = (
                connection.execute(
                    text(
                        "SELECT operator_id, workspace_id, setup_state, desired_access, "
                        "access_epoch, revision "
                        "FROM main.operators WHERE operator_id = :op_id"
                    ),
                    {"op_id": scope.operator_id},
                )
                .mappings()
                .one_or_none()
            )
            if operator is None or operator["workspace_id"] != scope.workspace_id:
                raise AdminNotFoundError("operator_not_found", "Operator assignment not found.")
            if operator["setup_state"] == "retired" or operator["desired_access"] == "retired":
                raise AdminConflictError(
                    "operator_retired", "Retired operators cannot be repaired."
                )
            if int(operator["revision"]) != command.intent.expected_revision:
                raise AdminConflictError(
                    "operator_revision_conflict", "Operator revision changed; reload before retry."
                )
            if int(operator["access_epoch"]) != command.intent.access_epoch:
                raise AdminConflictError(
                    "operator_epoch_conflict", "Operator access epoch changed; reload before retry."
                )
            release = (
                connection.execute(
                    text(
                        "SELECT release_id FROM main.qualified_releases "
                        "WHERE release_id = :rel_id AND component = 'operator' "
                        "AND state = 'qualified'"
                    ),
                    {"rel_id": payload.release_id},
                )
                .mappings()
                .one_or_none()
            )
            if release is None:
                raise AdminConflictError(
                    "release_not_qualified",
                    "Requested operator release is not in qualified_releases.",
                )
            active_conflict = (
                connection.execute(
                    text(
                        "SELECT operation_id FROM main.operations "
                        "WHERE operator_id = :op_id "
                        "AND kind IN ('provision', 'repair_runtime', 'retire') "
                        "AND state IN ('pending', 'running', 'unknown') "
                        "LIMIT 1"
                    ),
                    {"op_id": scope.operator_id},
                )
                .scalars()
                .first()
            )
            if active_conflict is not None:
                raise AdminConflictError(
                    "operation_in_progress",
                    "Another lifecycle operation is already active for this operator.",
                )
            cd_row = (
                connection.execute(
                    text(
                        "SELECT component_deployment_id FROM main.component_deployments "
                        "WHERE operator_id = :op_id ORDER BY revision DESC, component_deployment_id DESC LIMIT 1"
                    ),
                    {"op_id": scope.operator_id},
                )
                .mappings()
                .first()
            )
            cd_id = cd_row["component_deployment_id"] if cd_row is not None else None
            request_json = json.dumps(
                command.intent.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            connection.execute(
                text(
                    "INSERT INTO main.operations ("
                    "operation_id, operator_id, component_deployment_id, kind, idempotency_key, "
                    "request_hash, request_json, actor_principal_id, system_actor, "
                    "expected_revision, access_epoch, state, effect_reference, result_json, "
                    "error_code, created_at, updated_at, revision"
                    ") VALUES ("
                    ":op_id, :operator_id, :cd_id, 'repair_runtime', :key, "
                    ":request_hash, :request_json, :principal_id, NULL, "
                    ":expected_revision, :epoch, 'pending', NULL, NULL, "
                    "NULL, :now, :now, 1"
                    ")"
                ),
                {
                    "op_id": command.operation_id,
                    "operator_id": scope.operator_id,
                    "cd_id": cd_id,
                    "key": command.idempotency_key,
                    "request_hash": command.request_hash,
                    "request_json": request_json,
                    "principal_id": actor.principal_id,
                    "expected_revision": command.intent.expected_revision,
                    "epoch": command.intent.access_epoch,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "UPDATE main.operators SET revision = revision + 1, updated_at = :now "
                    "WHERE operator_id = :op_id"
                ),
                {"now": now, "op_id": scope.operator_id},
            )
            _event(
                connection,
                _EventEntry(
                    operation_id=command.operation_id,
                    sequence=1,
                    event_code="repair_runtime_admitted",
                    safe_summary=(
                        "Admitted clean runtime repair preserving operator IDs, data, and stores."
                    ),
                    recorded_at=now,
                ),
            )
            _audit(
                connection,
                _AuditEntry(
                    actor_ref=f"admin:{actor.principal_id}",
                    action="repair_runtime_admitted",
                    operator_id=scope.operator_id,
                    operation_id=command.operation_id,
                    recorded_at=now,
                    safe_facts={
                        "binding_id": payload.binding_id,
                        "release_id": payload.release_id,
                        "expected_resource_generation": payload.expected_resource_generation,
                    },
                ),
            )
            return OperationOutcome[AdminResult](
                operation=command.reference(),
                state=OperationState.PENDING,
                revision=1,
                observed_at=now,
                result=None,
                error_code=None,
            )

    def issue_invitation_with_token(
        self, actor: AdminAuthority, command: AdminCommand
    ) -> IssuedInvitationOutcome:
        try:
            require_invocation(actor, command)
        except ValueError as error:
            raise AdminDeniedError("admin_invocation_invalid", str(error)) from error
        if not isinstance(command.intent.payload, ReissueInvitation):
            raise AdminDeniedError("admin_action_invalid", "Expected a reissue_invitation command.")
        return self._reissue_invitation(actor, command)

    def mark_invitation_sent(
        self,
        actor: AdminAuthority,
        *,
        operator_id: str,
        invitation_id: str,
        expected_revision: int,
    ) -> int:
        """Transition a delivered invitation from pending_delivery to sent."""
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            self._verify_actor(connection, actor, now=now, sensitive=True)
            row = (
                connection.execute(
                    text(
                        "SELECT invitation_id, operator_id, state, expires_at, revision "
                        "FROM main.invitations WHERE invitation_id = :id AND operator_id = :op"
                    ),
                    {"id": invitation_id, "op": operator_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise AdminNotFoundError("invitation_not_found", "Invitation was not found.")
            if row["revision"] != expected_revision:
                raise AdminConflictError("invitation_revision_conflict", "Invitation changed.")
            if row["state"] == "sent":
                return row["revision"]
            if row["state"] != "pending_delivery" or now >= row["expires_at"]:
                raise AdminConflictError(
                    "invitation_state_invalid", "Invitation cannot be marked delivered."
                )
            next_revision = row["revision"] + 1
            connection.execute(
                text(
                    "UPDATE main.invitations SET state = 'sent', "
                    "delivery_attempts = delivery_attempts + 1, "
                    "last_delivery_code = 'manual_delivery_confirmed', "
                    "revision = :rev WHERE invitation_id = :id"
                ),
                {"rev": next_revision, "id": invitation_id},
            )
            _audit(
                connection,
                _AuditEntry(
                    actor_ref=f"admin:{actor.principal_id}",
                    action="invitation_marked_sent",
                    operator_id=operator_id,
                    operation_id=None,
                    recorded_at=now,
                    safe_facts={"invitation_id": invitation_id, "revision": next_revision},
                ),
            )
            return next_revision

    def _validate_create_inputs(self, connection: Connection, payload: CreateAssignment) -> str:
        if payload.slug in RESERVED_SLUGS:
            raise AdminConflictError("operator_slug_reserved", "That workspace slug is reserved.")
        policy = (
            connection.execute(
                text(
                    "SELECT policy_id, plan_code, policy_version, usable_bytes "
                    "FROM main.storage_policies WHERE policy_id = :id"
                ),
                {"id": payload.policy_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            policy is None
            or policy["plan_code"] != FREE_V1_PLAN_CODE
            or policy["policy_version"] != FREE_V1_POLICY_VERSION
            or policy["usable_bytes"] != FREE_V1_USABLE_BYTES
        ):
            raise AdminNotFoundError(
                "policy_not_found", "Pinned Free v1 storage policy is required."
            )
        release = (
            connection.execute(
                text(
                    "SELECT release_id, component, state FROM main.qualified_releases "
                    "WHERE release_id = :id"
                ),
                {"id": payload.release_id},
            )
            .mappings()
            .one_or_none()
        )
        if release is None or release["component"] != "operator" or release["state"] != "qualified":
            raise AdminNotFoundError(
                "release_not_found", "A qualified Operator release is required."
            )
        key = _email_key(self.issuer, payload.email)
        existing = (
            connection.execute(
                text(
                    "SELECT operator_id, workspace_id, workspace_slug, email_key "
                    "FROM main.operators "
                    "WHERE operator_id = :op_id OR workspace_id = :ws_id "
                    "OR workspace_slug = :slug OR email_key = :email_key"
                ),
                {
                    "op_id": payload.operator_id,
                    "ws_id": payload.workspace_id,
                    "slug": payload.slug,
                    "email_key": key,
                },
            )
            .mappings()
            .all()
        )
        if existing:
            row = existing[0]
            if row["workspace_slug"] == payload.slug:
                raise AdminConflictError(
                    "operator_slug_exists", "That workspace slug is already in use."
                )
            if row["email_key"] == key:
                raise AdminConflictError(
                    "operator_email_exists", "That email address is already assigned."
                )
            raise AdminConflictError(
                "operator_id_exists", "Operator or workspace identity already exists."
            )
        return key

    def _create_assignment(
        self,
        actor: AdminAuthority,
        command: AdminCommand,
        *,
        expected_snapshot_revision: int | None = None,
    ) -> OperationOutcome[AdminResult]:
        payload: CreateAssignment = command.intent.payload
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            meta = self._verify_actor(connection, actor, now=now, sensitive=True)
            retained = self._lookup_operation(connection, command.reference())
            if retained is not None:
                return retained
            if command.intent.expected_revision != meta["registry_generation"]:
                raise AdminConflictError(
                    "registry_revision_conflict",
                    "Deployment registry changed; refresh and review before creating.",
                )
            key = self._validate_create_inputs(connection, payload)
            decision, reserved = evaluate_admission(
                connection,
                operator_id=payload.operator_id,
                requested_commitment=payload.admission_commitment,
                now=now,
                expected_snapshot_revision=expected_snapshot_revision,
            )
            if decision.status == "insufficient":
                raise AdminConflictError(
                    "capacity_insufficient",
                    "Insufficient host capacity for another Free operator workspace.",
                    limiting_resources=decision.limiting_resources,
                )
            if decision.status != "within_candidate_envelope":
                raise AdminUnavailableError(
                    decision.code,
                    "Host capacity observation is unavailable or stale.",
                )
            self._persist_assignment(
                connection,
                _AssignmentContext(
                    actor=actor,
                    command=command,
                    deployment_id=meta["deployment_id"],
                    email_key=key,
                    reserved=reserved,
                    snapshot_revision=decision.expected_snapshot_revision,
                    now=now,
                ),
            )
            return OperationOutcome[AdminResult](
                operation=command.reference(),
                state=OperationState.PENDING,
                revision=1,
                observed_at=now,
            )

    def _persist_assignment(self, connection: Connection, ctx: _AssignmentContext) -> None:
        actor, command, now = ctx.actor, ctx.command, ctx.now
        payload: CreateAssignment = command.intent.payload
        deployment_row_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO main.operators ("
                "operator_id, workspace_id, display_name, invited_email, email_key, "
                "workspace_slug, issuer, subject, desired_policy_id, desired_access, "
                "setup_state, support_contact, access_epoch, revision, created_at, updated_at"
                ") VALUES ("
                ":operator_id, :workspace_id, :display_name, :invited_email, :email_key, "
                ":workspace_slug, :issuer, NULL, :policy_id, 'enabled', "
                "'pending', :support_contact, 1, 1, :now, :now"
                ")"
            ),
            {
                "operator_id": payload.operator_id,
                "workspace_id": payload.workspace_id,
                "display_name": payload.display_name,
                "invited_email": payload.email,
                "email_key": ctx.email_key,
                "workspace_slug": payload.slug,
                "issuer": self.issuer,
                "policy_id": payload.policy_id,
                "support_contact": payload.support_contact,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO main.component_deployments ("
                "component_deployment_id, deployment_id, component, scope_kind, "
                "operator_id, workspace_id, desired_release_id, observed_release_id, "
                "operation_id, state, observation_ref, observed_at, revision"
                ") VALUES ("
                ":cd_id, :deployment_id, 'operator', 'workspace', "
                ":operator_id, :workspace_id, :release_id, NULL, "
                "NULL, 'pending', NULL, NULL, 1"
                ")"
            ),
            {
                "cd_id": deployment_row_id,
                "deployment_id": ctx.deployment_id,
                "operator_id": payload.operator_id,
                "workspace_id": payload.workspace_id,
                "release_id": payload.release_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO main.capacity_commitments ("
                "operator_id, workspace_id, state, reserved_json, observed_json, "
                "updated_at, revision"
                ") VALUES ("
                ":operator_id, :workspace_id, 'pending', :reserved_json, :observed_json, "
                ":now, 1"
                ")"
            ),
            {
                "operator_id": payload.operator_id,
                "workspace_id": payload.workspace_id,
                "reserved_json": ctx.reserved.model_dump_json(),
                "observed_json": Resources().model_dump_json(),
                "now": now,
            },
        )
        request_json = json.dumps(
            command.intent.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        connection.execute(
            text(
                "INSERT INTO main.operations ("
                "operation_id, operator_id, component_deployment_id, kind, idempotency_key, "
                "request_hash, request_json, actor_principal_id, system_actor, "
                "expected_revision, access_epoch, state, effect_reference, result_json, "
                "error_code, created_at, updated_at, revision"
                ") VALUES ("
                ":op_id, :operator_id, :cd_id, 'provision', :key, "
                ":request_hash, :request_json, :principal_id, NULL, "
                ":expected_revision, 1, 'pending', NULL, NULL, "
                "NULL, :now, :now, 1"
                ")"
            ),
            {
                "op_id": command.operation_id,
                "operator_id": payload.operator_id,
                "cd_id": deployment_row_id,
                "key": command.idempotency_key,
                "request_hash": command.request_hash,
                "request_json": request_json,
                "principal_id": actor.principal_id,
                "expected_revision": command.intent.expected_revision,
                "now": now,
            },
        )
        connection.execute(
            text(
                "UPDATE main.component_deployments SET operation_id = :op_id "
                "WHERE component_deployment_id = :cd_id"
            ),
            {"op_id": command.operation_id, "cd_id": deployment_row_id},
        )
        connection.execute(
            text(
                "UPDATE main.control_meta SET registry_generation = registry_generation + 1 "
                "WHERE id = 1"
            )
        )
        _event(
            connection,
            _EventEntry(
                operation_id=command.operation_id,
                sequence=1,
                event_code="provision_queued",
                safe_summary="Operator assignment created and queued for manual provisioning.",
                recorded_at=now,
            ),
        )
        _audit(
            connection,
            _AuditEntry(
                actor_ref=f"admin:{actor.principal_id}",
                action="create_assignment",
                operator_id=payload.operator_id,
                operation_id=command.operation_id,
                recorded_at=now,
                safe_facts={
                    "component_deployment_id": deployment_row_id,
                    "initial_data": payload.initial_data,
                    "policy_id": payload.policy_id,
                    "release_id": payload.release_id,
                    "snapshot_revision": ctx.snapshot_revision,
                },
            ),
        )

    def _reissue_invitation(
        self, actor: AdminAuthority, command: AdminCommand
    ) -> IssuedInvitationOutcome:
        payload: ReissueInvitation = command.intent.payload
        scope: WorkspaceScope = command.intent.scope
        raw_token = token_urlsafe(32)
        invitation_id = str(uuid4())
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            self._verify_actor(connection, actor, now=now, sensitive=True)
            retained = self._lookup_operation(connection, command.reference())
            if retained is not None:
                return IssuedInvitationOutcome(
                    outcome=retained, invitation_id=None, token=None, expires_at=None
                )
            operator = (
                connection.execute(
                    text("SELECT * FROM main.operators WHERE operator_id = :id"),
                    {"id": scope.operator_id},
                )
                .mappings()
                .one_or_none()
            )
            if operator is None or operator["workspace_id"] != scope.workspace_id:
                raise AdminNotFoundError("operator_not_found", "Operator was not found.")
            if operator["revision"] != command.intent.expected_revision:
                raise AdminConflictError("operator_revision_conflict", "Operator record changed.")
            if operator["access_epoch"] != command.intent.access_epoch:
                raise AdminConflictError("operator_epoch_conflict", "Access epoch changed.")
            if (
                operator["setup_state"] != "ready_for_claim"
                or operator["subject"] is not None
                or operator["desired_access"] != "enabled"
            ):
                raise AdminConflictError(
                    "operator_not_ready_for_invitation",
                    "Invitations can only be issued for ready, unclaimed, enabled operators.",
                )
            deployment = (
                connection.execute(
                    text(
                        "SELECT component_deployment_id, state FROM main.component_deployments "
                        "WHERE component_deployment_id = :cd_id AND operator_id = :op_id"
                    ),
                    {"cd_id": payload.assignment_id, "op_id": scope.operator_id},
                )
                .mappings()
                .one_or_none()
            )
            if deployment is None or deployment["state"] != "applied":
                raise AdminConflictError(
                    "assignment_not_applied",
                    "Operator deployment must be applied before issuing an invitation.",
                )

            next_revision = operator["revision"] + 1
            expires_at = now + INVITATION_TTL_MS
            connection.execute(
                text(
                    "UPDATE main.operators SET revision = :rev, updated_at = :now "
                    "WHERE operator_id = :id"
                ),
                {"rev": next_revision, "now": now, "id": scope.operator_id},
            )
            connection.execute(
                text(
                    "UPDATE main.invitations SET state = 'revoked', revision = revision + 1 "
                    "WHERE operator_id = :id AND state IN ('pending_delivery', 'sent')"
                ),
                {"id": scope.operator_id},
            )
            connection.execute(
                text(
                    "INSERT INTO main.invitations ("
                    "invitation_id, operator_id, token_hash, email_key, assignment_revision, "
                    "access_epoch, state, expires_at, created_at, revision"
                    ") VALUES ("
                    ":id, :operator_id, :token_hash, :email_key, :assignment_revision, "
                    ":access_epoch, 'pending_delivery', :expires_at, :now, 1"
                    ")"
                ),
                {
                    "id": invitation_id,
                    "operator_id": scope.operator_id,
                    "token_hash": _token_hash(raw_token),
                    "email_key": operator["email_key"],
                    "assignment_revision": next_revision,
                    "access_epoch": operator["access_epoch"],
                    "expires_at": expires_at,
                    "now": now,
                },
            )
            result = AdminResult(
                resource_id=scope.operator_id, revision=next_revision, state="ready"
            )
            request_json = json.dumps(
                command.intent.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            connection.execute(
                text(
                    "INSERT INTO main.operations ("
                    "operation_id, operator_id, component_deployment_id, kind, idempotency_key, "
                    "request_hash, request_json, actor_principal_id, system_actor, "
                    "expected_revision, access_epoch, state, effect_reference, result_json, "
                    "error_code, created_at, updated_at, revision"
                    ") VALUES ("
                    ":op_id, :operator_id, :cd_id, 'reissue_invitation', :key, "
                    ":request_hash, :request_json, :principal_id, NULL, "
                    ":expected_revision, :epoch, 'succeeded', :effect_ref, :result_json, "
                    "NULL, :now, :now, 1"
                    ")"
                ),
                {
                    "op_id": command.operation_id,
                    "operator_id": scope.operator_id,
                    "cd_id": payload.assignment_id,
                    "key": command.idempotency_key,
                    "request_hash": command.request_hash,
                    "request_json": request_json,
                    "principal_id": actor.principal_id,
                    "expected_revision": command.intent.expected_revision,
                    "epoch": operator["access_epoch"],
                    "effect_ref": f"invitation:{invitation_id}",
                    "result_json": result.model_dump_json(),
                    "now": now,
                },
            )
            _event(
                connection,
                _EventEntry(
                    operation_id=command.operation_id,
                    sequence=1,
                    event_code="invitation_issued",
                    safe_summary="Invitation issued and awaiting explicit delivery.",
                    recorded_at=now,
                ),
            )
            _audit(
                connection,
                _AuditEntry(
                    actor_ref=f"admin:{actor.principal_id}",
                    action="reissue_invitation",
                    operator_id=scope.operator_id,
                    operation_id=command.operation_id,
                    recorded_at=now,
                    safe_facts={"invitation_id": invitation_id, "revision": next_revision},
                ),
            )
            outcome = OperationOutcome[AdminResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=now,
                result=result,
            )
            return IssuedInvitationOutcome(
                outcome=outcome,
                invitation_id=invitation_id,
                token=SecretStr(raw_token),
                expires_at=expires_at,
            )

    def _upsert_source_observation(
        self,
        connection: Connection,
        *,
        scope: WorkspaceScope,
        access_epoch: int,
        reading: SourceObservationReading | None,
        now: int,
    ) -> str:
        existing_obs = (
            connection.execute(
                text(
                    "SELECT revision FROM main.operator_source_observations WHERE operator_id = :id"
                ),
                {"id": scope.operator_id},
            )
            .mappings()
            .one_or_none()
        )
        next_obs_rev = 1 if existing_obs is None else existing_obs["revision"] + 1
        valid = reading is not None and reading.observed_at <= now
        params = {
            "operator_id": scope.operator_id,
            "workspace_id": scope.workspace_id,
            "access_epoch": access_epoch,
            "effective_enabled": (1 if reading.effective_enabled else 0) if valid else None,
            "usage_bytes": reading.usage_bytes if valid else None,
            "usable_bytes": reading.usable_bytes if valid else None,
            "source_revision": reading.source_revision if valid else None,
            "observed_at": reading.observed_at if valid else None,
            "checked_at": now,
            "freshness_state": "known" if valid else "unavailable",
            "revision": next_obs_rev,
        }
        if existing_obs is None:
            connection.execute(
                text(
                    "INSERT INTO main.operator_source_observations ("
                    "operator_id, workspace_id, access_epoch, effective_enabled, "
                    "usage_bytes, usable_bytes, source_revision, observed_at, "
                    "checked_at, freshness_state, revision"
                    ") VALUES ("
                    ":operator_id, :workspace_id, :access_epoch, :effective_enabled, "
                    ":usage_bytes, :usable_bytes, :source_revision, :observed_at, "
                    ":checked_at, :freshness_state, :revision"
                    ")"
                ),
                params,
            )
        else:
            connection.execute(
                text(
                    "UPDATE main.operator_source_observations SET "
                    "access_epoch = :access_epoch, "
                    "effective_enabled = :effective_enabled, "
                    "usage_bytes = :usage_bytes, "
                    "usable_bytes = :usable_bytes, "
                    "source_revision = :source_revision, "
                    "observed_at = :observed_at, "
                    "checked_at = :checked_at, "
                    "freshness_state = :freshness_state, "
                    "revision = :revision "
                    "WHERE operator_id = :operator_id"
                ),
                params,
            )
        return str(params["freshness_state"])

    def _load_refresh_target(
        self, connection: Connection, scope: WorkspaceScope, command: AdminCommand
    ):
        payload: RefreshSource = command.intent.payload
        operator = (
            connection.execute(
                text("SELECT * FROM main.operators WHERE operator_id = :id"),
                {"id": scope.operator_id},
            )
            .mappings()
            .one_or_none()
        )
        if operator is None or operator["workspace_id"] != scope.workspace_id:
            raise AdminNotFoundError("operator_not_found", "Operator was not found.")
        if operator["revision"] != command.intent.expected_revision:
            raise AdminConflictError("operator_revision_conflict", "Operator record changed.")
        if operator["access_epoch"] != command.intent.access_epoch:
            raise AdminConflictError("operator_epoch_conflict", "Access epoch changed.")
        deployment = (
            connection.execute(
                text(
                    "SELECT component_deployment_id FROM main.component_deployments "
                    "WHERE component_deployment_id = :cd AND operator_id = :op "
                    "AND component = 'operator'"
                ),
                {"cd": payload.assignment_id, "op": scope.operator_id},
            )
            .mappings()
            .one_or_none()
        )
        if deployment is None:
            raise AdminConflictError(
                "assignment_not_found", "Assignment does not belong to this operator."
            )
        return operator

    def _refresh_source(
        self, actor: AdminAuthority, command: AdminCommand
    ) -> OperationOutcome[AdminResult]:
        payload: RefreshSource = command.intent.payload
        scope: WorkspaceScope = command.intent.scope
        # Phase 1: check authority and scope without holding a write lock.
        with self.engine.connect() as connection:
            self._verify_actor(connection, actor, now=self.clock(), sensitive=False)
            retained = self._lookup_operation(connection, command.reference())
            if retained is not None:
                return retained
            self._load_refresh_target(connection, scope, command)

        # Phase 2: source inspection runs strictly outside any SQLite transaction.
        reading: SourceObservationReading | None = None
        if self.source_inspector is not None:
            try:
                reading = self.source_inspector(
                    scope.operator_id, scope.workspace_id, command.intent.access_epoch
                )
            except Exception:
                reading = None

        # Phase 3: atomically persist projection, operation, event, and audit.
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            self._verify_actor(connection, actor, now=now, sensitive=False)
            retained = self._lookup_operation(connection, command.reference())
            if retained is not None:
                return retained
            operator = self._load_refresh_target(connection, scope, command)

            freshness_state = self._upsert_source_observation(
                connection,
                scope=scope,
                access_epoch=command.intent.access_epoch,
                reading=reading,
                now=now,
            )
            succeeded = freshness_state == "known"
            op_state = OperationState.SUCCEEDED if succeeded else OperationState.NEEDS_ATTENTION
            result = (
                AdminResult(
                    resource_id=scope.operator_id,
                    revision=operator["revision"],
                    state=_op_state_from_setup(operator["setup_state"]),
                )
                if succeeded
                else None
            )
            error_code = None if succeeded else "source_unreachable"
            request_json = json.dumps(
                command.intent.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            connection.execute(
                text(
                    "INSERT INTO main.operations ("
                    "operation_id, operator_id, component_deployment_id, kind, idempotency_key, "
                    "request_hash, request_json, actor_principal_id, system_actor, "
                    "expected_revision, access_epoch, state, effect_reference, result_json, "
                    "error_code, created_at, updated_at, revision"
                    ") VALUES ("
                    ":op_id, :operator_id, :cd_id, 'refresh_source', :key, "
                    ":request_hash, :request_json, :principal_id, NULL, "
                    ":expected_revision, :epoch, :state, NULL, :result_json, "
                    ":error_code, :now, :now, 1"
                    ")"
                ),
                {
                    "op_id": command.operation_id,
                    "operator_id": scope.operator_id,
                    "cd_id": payload.assignment_id,
                    "key": command.idempotency_key,
                    "request_hash": command.request_hash,
                    "request_json": request_json,
                    "principal_id": actor.principal_id,
                    "expected_revision": command.intent.expected_revision,
                    "epoch": command.intent.access_epoch,
                    "state": op_state.value,
                    "result_json": result.model_dump_json() if result is not None else None,
                    "error_code": error_code,
                    "now": now,
                },
            )
            _event(
                connection,
                _EventEntry(
                    operation_id=command.operation_id,
                    sequence=1,
                    event_code="source_refreshed" if succeeded else "source_refresh_unavailable",
                    safe_summary=(
                        "Refreshed cached access and usage observation from operator source."
                        if succeeded
                        else "Operator source could not be reached for refresh."
                    ),
                    recorded_at=now,
                ),
            )
            _audit(
                connection,
                _AuditEntry(
                    actor_ref=f"admin:{actor.principal_id}",
                    action="refresh_source",
                    operator_id=scope.operator_id,
                    operation_id=command.operation_id,
                    recorded_at=now,
                    safe_facts={"freshness_state": freshness_state},
                ),
            )
            return OperationOutcome[AdminResult](
                operation=command.reference(),
                state=op_state,
                revision=1,
                observed_at=now,
                result=result,
                error_code=error_code,
                action_required=None if succeeded else "check_original_result",
            )

    def observe(
        self, actor: AdminAuthority, query: ObservationQuery
    ) -> ObservationPage[AdminObservation]:
        """Set-based bounded observation page satisfying AdminPort.observe."""
        if query.scope.kind != "deployment":
            raise AdminDeniedError(
                "admin_scope_invalid", "Admin observations use deployment scope."
            )
        admin_list, operator_revisions = self._list_operators_with_revisions(
            actor, query, AdminFilters()
        )
        page = admin_list.directory.data
        assert page is not None
        items = tuple(
            AdminObservation(
                resource_id=item.operator_id,
                revision=operator_revisions[item.operator_id],
                freshness=page.freshness,
                display_name=item.display_name,
                setup_state=item.setup_state,
                desired_enabled=item.desired_enabled,
                effective_enabled=(
                    item.access.data.effective_enabled if item.access.data is not None else None
                ),
                usage_bytes=(item.usage.data.used_bytes if item.usage.data is not None else None),
                release_id=item.release_id,
                protection_state=(
                    item.protection.freshness.state.value
                    if item.protection.freshness is not None
                    else "unavailable"
                ),
            )
            for item in page.items
        )
        return ObservationPage[AdminObservation](
            items=items,
            matching_total=page.matching_total,
            freshness=page.freshness,
            continuation=page.continuation,
        )

    def list_operators(
        self,
        actor: AdminAuthority,
        query: ObservationQuery,
        filters: AdminFilters | None = None,
    ) -> AdminList:
        """Strictly set-based Admin directory read with bounded keyset pagination."""
        admin_list, _ = self._list_operators_with_revisions(actor, query, filters)
        return admin_list

    def _list_operators_with_revisions(
        self,
        actor: AdminAuthority,
        query: ObservationQuery,
        filters: AdminFilters | None = None,
    ) -> tuple[AdminList, dict[str, int]]:
        active_filters = filters or AdminFilters()
        if query.scope.kind != "deployment" or query.deployment_id != actor.deployment_id:
            raise AdminDeniedError("admin_scope_invalid", "Admin list requires deployment scope.")
        filter_hash = semantic_hash(active_filters)
        where_sql, filter_params = _build_list_where(active_filters)
        with self.engine.connect() as connection:
            now = self.clock()
            meta = self._verify_actor(connection, actor, now=now, sensitive=False)
            source_revision = f"registry:{meta['registry_generation']}"
            as_of, cursor_clause, cursor_params = _cursor_filter(
                query,
                deployment_id=meta["deployment_id"],
                filter_hash=filter_hash,
                source_revision=source_revision,
                default_as_of=now,
            )
            params: dict[str, object] = {
                **filter_params,
                **cursor_params,
                "limit": query.limit + 1,
            }
            total = connection.execute(
                text(
                    "SELECT count(*) FROM main.operators o "
                    "LEFT JOIN main.operator_source_observations obs "
                    "ON obs.operator_id = o.operator_id "
                    f"WHERE {where_sql}"
                ),
                params,
            ).scalar_one()
            rows = (
                connection.execute(
                    text(
                        "WITH latest_op AS ("
                        "  SELECT *, ROW_NUMBER() OVER ("
                        "    PARTITION BY operator_id ORDER BY created_at DESC, operation_id DESC"
                        "  ) AS rn "
                        "  FROM main.operations WHERE operator_id IS NOT NULL"
                        ") "
                        "SELECT "
                        "  o.operator_id, o.workspace_id, o.display_name, o.workspace_slug, "
                        "  o.setup_state, o.desired_access, o.subject, o.created_at, o.revision, "
                        "  cd.desired_release_id, cd.state AS deployment_state, "
                        "  cd.observation_ref, "
                        "  obs.effective_enabled AS obs_enabled, obs.usage_bytes AS obs_usage, "
                        "  obs.usable_bytes AS obs_usable, obs.source_revision AS obs_src_rev, "
                        "  obs.observed_at AS obs_at, obs.freshness_state AS obs_freshness, "
                        "  rec.protection_state AS rec_state, rec.verified_at AS rec_verified_at, "
                        "  rec.latest_point_ref AS rec_point_ref, rec.observed_at AS rec_obs_at, "
                        "  rec.source_revision AS rec_src_rev, "
                        "  op.operation_id AS op_id, op.kind AS op_kind, "
                        "  op.idempotency_key AS op_key, op.request_hash AS op_hash, "
                        "  op.request_json AS op_req_json, op.state AS op_state, "
                        "  op.result_json AS op_res_json, op.error_code AS op_err, "
                        "  op.updated_at AS op_updated, op.revision AS op_rev "
                        "FROM main.operators o "
                        "JOIN main.component_deployments cd "
                        "  ON cd.operator_id = o.operator_id AND cd.component = 'operator' "
                        "LEFT JOIN main.operator_source_observations obs "
                        "  ON obs.operator_id = o.operator_id "
                        "LEFT JOIN main.workspace_recovery_status rec "
                        "  ON rec.operator_id = o.operator_id "
                        "LEFT JOIN latest_op op "
                        "  ON op.operator_id = o.operator_id AND op.rn = 1 "
                        f"WHERE {where_sql}{cursor_clause} "
                        "ORDER BY o.created_at ASC, o.operator_id ASC "
                        "LIMIT :limit"
                    ),
                    params,
                )
                .mappings()
                .all()
            )

        has_more = len(rows) > query.limit
        page_rows = rows[: query.limit]
        summaries = tuple(
            self._summary_from_row(row, deployment_id=meta["deployment_id"], now=now)
            for row in page_rows
        )
        freshness = Freshness(
            state=FreshnessState.KNOWN,
            as_of=as_of,
            source_revision=source_revision,
        )
        continuation = (
            ContinuationCursor(
                context=CursorContext(
                    deployment_id=meta["deployment_id"],
                    scope=DeploymentScope(),
                    endpoint="admin_operators",
                    filter_hash=filter_hash,
                    as_of=as_of,
                    source_revision=source_revision,
                    ordering_version=1,
                ),
                position=(str(page_rows[-1]["created_at"]), page_rows[-1]["operator_id"]),
                limit=query.limit,
            )
            if has_more and page_rows
            else None
        )
        page = ObservationPage[OperatorSummary](
            items=summaries,
            matching_total=total,
            freshness=freshness,
            continuation=continuation,
        )
        operator_revisions = {str(row["operator_id"]): int(row["revision"]) for row in page_rows}
        return (
            AdminList(
                query=query,
                filters=active_filters,
                directory=Section[ObservationPage[OperatorSummary]](
                    state="ready", data=page, freshness=freshness
                ),
                actions=(ActionState(action=UIAction.CREATE_ASSIGNMENT, enabled=True),),
            ),
            operator_revisions,
        )

    def detail_operator(self, actor: AdminAuthority, operator_id: str) -> AdminDetail:
        """Bounded set-based Admin detail read for one operator."""
        detail, _ = self.detail_operator_with_revision(actor, operator_id)
        return detail

    def detail_operator_with_revision(
        self, actor: AdminAuthority, operator_id: str
    ) -> tuple[AdminDetail, int]:
        """Bounded set-based Admin detail read returning both AdminDetail and operator revision."""
        with self.engine.connect() as connection:
            now = self.clock()
            meta = self._verify_actor(connection, actor, now=now, sensitive=False)
            row = (
                connection.execute(
                    text(
                        "WITH latest_op AS ("
                        "  SELECT *, ROW_NUMBER() OVER ("
                        "    PARTITION BY operator_id ORDER BY created_at DESC, operation_id DESC"
                        "  ) AS rn "
                        "  FROM main.operations WHERE operator_id = :id"
                        "), latest_refresh AS ("
                        "  SELECT *, ROW_NUMBER() OVER ("
                        "    PARTITION BY operator_id ORDER BY created_at DESC, operation_id DESC"
                        "  ) AS rn "
                        "  FROM main.operations "
                        "  WHERE operator_id = :id AND kind = 'refresh_source'"
                        ") "
                        "SELECT "
                        "  o.operator_id, o.workspace_id, o.display_name, o.workspace_slug, "
                        "  o.setup_state, o.desired_access, o.subject, o.created_at, o.revision, "
                        "  cd.desired_release_id, cd.state AS deployment_state, "
                        "  cd.observation_ref, "
                        "  obs.effective_enabled AS obs_enabled, obs.usage_bytes AS obs_usage, "
                        "  obs.usable_bytes AS obs_usable, obs.source_revision AS obs_src_rev, "
                        "  obs.observed_at AS obs_at, obs.freshness_state AS obs_freshness, "
                        "  rec.protection_state AS rec_state, rec.verified_at AS rec_verified_at, "
                        "  rec.latest_point_ref AS rec_point_ref, rec.observed_at AS rec_obs_at, "
                        "  rec.source_revision AS rec_src_rev, "
                        "  op.operation_id AS op_id, op.kind AS op_kind, "
                        "  op.idempotency_key AS op_key, op.request_hash AS op_hash, "
                        "  op.request_json AS op_req_json, op.state AS op_state, "
                        "  op.result_json AS op_res_json, op.error_code AS op_err, "
                        "  op.updated_at AS op_updated, op.revision AS op_rev, "
                        "  rf.operation_id AS rf_id, rf.kind AS rf_kind, "
                        "  rf.idempotency_key AS rf_key, rf.request_hash AS rf_hash, "
                        "  rf.request_json AS rf_req_json, rf.state AS rf_state, "
                        "  rf.result_json AS rf_res_json, rf.error_code AS rf_err, "
                        "  rf.updated_at AS rf_updated, rf.revision AS rf_rev "
                        "FROM main.operators o "
                        "JOIN main.component_deployments cd "
                        "  ON cd.operator_id = o.operator_id AND cd.component = 'operator' "
                        "LEFT JOIN main.operator_source_observations obs "
                        "  ON obs.operator_id = o.operator_id "
                        "LEFT JOIN main.workspace_recovery_status rec "
                        "  ON rec.operator_id = o.operator_id "
                        "LEFT JOIN latest_op op ON op.operator_id = o.operator_id AND op.rn = 1 "
                        "LEFT JOIN latest_refresh rf "
                        "  ON rf.operator_id = o.operator_id AND rf.rn = 1 "
                        "WHERE o.operator_id = :id"
                    ),
                    {"id": operator_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise AdminNotFoundError("operator_not_found", "Operator was not found.")

        summary = self._summary_from_row(row, deployment_id=meta["deployment_id"], now=now)
        readiness = self._readiness_from_row(row)
        readiness_freshness = Freshness(
            state=FreshnessState.KNOWN,
            as_of=now,
            source_revision=f"operator:{row['revision']}",
        )
        refresh_operation = _prefixed_operation(row, "rf", deployment_id=meta["deployment_id"])
        return (
            AdminDetail(
                operator=summary,
                readiness=Section[Readiness](
                    state="ready", data=readiness, freshness=readiness_freshness
                ),
                refresh_operation=refresh_operation,
                actions=summary.actions,
            ),
            int(row["revision"]),
        )

    def _summary_from_row(self, row, *, deployment_id: str, now: int) -> OperatorSummary:
        if row["obs_freshness"] in {"known", "stale"}:
            obs_fresh = Freshness(
                state=FreshnessState(row["obs_freshness"]),
                as_of=row["obs_at"],
                source_revision=f"source:{row['obs_src_rev']}",
                error_code="source_stale" if row["obs_freshness"] == "stale" else None,
            )
            sec_state = "ready" if row["obs_freshness"] == "known" else "stale"
            access_section = Section[Access](
                state=sec_state,
                data=Access(effective_enabled=bool(row["obs_enabled"])),
                freshness=obs_fresh,
            )
            usage_section = Section[FreeUsage](
                state=sec_state,
                data=FreeUsage(used_bytes=row["obs_usage"]),
                freshness=obs_fresh,
            )
        else:
            unavail = Freshness(
                state=FreshnessState.UNAVAILABLE,
                error_code="source_observation_unavailable",
            )
            access_section = Section[Access](state="unavailable", freshness=unavail)
            usage_section = Section[FreeUsage](state="unavailable", freshness=unavail)

        if (
            row["rec_state"] in {"healthy", "unchanged", "overdue"}
            and row["rec_verified_at"] is not None
            and row["rec_point_ref"]
        ):
            rec_fresh = Freshness(
                state=FreshnessState.KNOWN,
                as_of=row["rec_obs_at"],
                source_revision=f"recovery:{row['rec_src_rev']}",
            )
            protection_section = Section[Protection](
                state="ready",
                data=Protection(
                    status=(
                        "protected" if row["rec_state"] in {"healthy", "unchanged"} else "degraded"
                    ),
                    last_verified_at=row["rec_verified_at"],
                    point_age_ms=max(0, now - row["rec_verified_at"]),
                    proof_ref=row["rec_point_ref"],
                ),
                freshness=rec_fresh,
            )
        else:
            protection_section = Section[Protection](
                state="unavailable",
                freshness=Freshness(
                    state=FreshnessState.UNAVAILABLE,
                    error_code="backup_protection_unavailable",
                ),
            )

        operation = _prefixed_operation(row, "op", deployment_id=deployment_id)
        can_invite = (
            row["setup_state"] == "ready_for_claim"
            and row["subject"] is None
            and row["desired_access"] == "enabled"
            and row["deployment_state"] == "applied"
        )
        actions = (
            ActionState(action=UIAction.REFRESH_SOURCE, enabled=True),
            ActionState(
                action=UIAction.REISSUE_INVITATION,
                enabled=can_invite,
                reason=None if can_invite else "operator_not_ready_for_invitation",
            ),
        )
        return OperatorSummary(
            operator_id=row["operator_id"],
            workspace_id=row["workspace_id"],
            display_name=row["display_name"],
            slug=row["workspace_slug"],
            setup_state=row["setup_state"],
            desired_enabled=row["desired_access"] == "enabled",
            access=access_section,
            usage=usage_section,
            protection=protection_section,
            release_id=row["desired_release_id"],
            operation=operation,
            actions=actions,
        )

    @staticmethod
    def _readiness_from_row(row) -> Readiness:
        applied = row["deployment_state"] == "applied" and row["observation_ref"] is not None
        failed = (
            row["deployment_state"] == "needs_attention" or row["setup_state"] == "needs_attention"
        )
        base_state = "passed" if applied else ("failed" if failed else "pending")
        ref = row["observation_ref"] if applied else None
        binding_passed = applied and row["setup_state"] in {"ready_for_claim", "active"}
        protection_passed = (
            row["rec_state"] in {"healthy", "unchanged"}
            and row["rec_verified_at"] is not None
            and row["rec_point_ref"] is not None
        )
        checks = (
            Gate(name="isolation", state=base_state, evidence_ref=ref),
            Gate(name="schema", state=base_state, evidence_ref=ref),
            Gate(name="routing", state=base_state, evidence_ref=ref),
            Gate(
                name="protection",
                state="passed" if protection_passed else "unavailable",
                evidence_ref=row["rec_point_ref"] if protection_passed else None,
            ),
            Gate(
                name="binding",
                state="passed" if binding_passed else ("failed" if failed else "pending"),
                evidence_ref=ref if binding_passed else None,
            ),
        )
        states = {gate.state for gate in checks}
        if states == {"passed"}:
            overall = "ready"
        elif "failed" in states:
            overall = "failed"
        elif "pending" in states:
            overall = "pending"
        else:
            overall = "unavailable"
        return Readiness(state=overall, checks=checks)
