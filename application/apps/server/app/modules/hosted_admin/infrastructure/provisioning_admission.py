"""Admin-owned AdmissionPort and verified provisioning receipt transitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from app.modules.host_agent.application.capacity import OperatorBudget
from app.modules.host_agent.application.dispatch import (
    AdmittedEffect,
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
    ResourceInputs,
    ResourcePlan,
)
from app.modules.hosted_admin.application.pilot_contracts import AdminResult
from app.modules.hosted_admin.infrastructure.policy_bootstrap import FREE_V1_USABLE_BYTES
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.sqlite_engine import immediate_transaction

DEFAULT_ADMISSION_TTL_MS = 60_000
ADMITTABLE_STATES = frozenset({"pending", "running", "needs_attention", "unknown"})


@dataclass(frozen=True)
class ProvisioningIntent:
    """Verified, immutable Admin provisioning intent for one operation."""

    operation_id: str
    operation_state: str
    idempotency_key: str
    request_hash: str
    operator_id: str
    workspace_id: str
    component_deployment_id: str
    workspace_slug: str
    public_origin: str
    email_key: str
    issuer: str
    policy_id: str
    release_id: str
    initial_data: str
    seed_bundle: str | None
    access_epoch: int
    deployment_id: str
    plan: ResourcePlan


def _next_event_sequence(connection: Connection, operation_id: str) -> int:
    current = connection.execute(
        text(
            "SELECT COALESCE(MAX(sequence), 0) FROM main.operation_events "
            "WHERE operation_id = :op_id"
        ),
        {"op_id": operation_id},
    ).scalar_one()
    return int(current) + 1


def _append_event(
    connection: Connection,
    *,
    operation_id: str,
    event_code: str,
    safe_summary: str,
    recorded_at: int,
) -> None:
    connection.execute(
        text(
            "INSERT INTO main.operation_events ("
            "operation_id, sequence, event_code, safe_summary, recorded_at"
            ") VALUES (:op_id, :seq, :code, :summary, :now)"
        ),
        {
            "op_id": operation_id,
            "seq": _next_event_sequence(connection, operation_id),
            "code": event_code,
            "summary": safe_summary,
            "now": recorded_at,
        },
    )


@dataclass(frozen=True)
class _AuditRecord:
    action: str
    operator_id: str
    operation_id: str
    recorded_at: int
    safe_facts: dict


def _append_audit(connection: Connection, record: _AuditRecord) -> None:
    connection.execute(
        text(
            "INSERT INTO main.admin_audit ("
            "audit_id, actor_ref, action, operator_id, operation_id, recorded_at, safe_facts_json"
            ") VALUES ("
            ":audit_id, 'host-agent:provision', :action, :op_id_ref, :op_id, :now, :facts)"
        ),
        {
            "audit_id": str(uuid4()),
            "action": record.action,
            "op_id_ref": record.operator_id,
            "op_id": record.operation_id,
            "now": record.recorded_at,
            "facts": json.dumps(record.safe_facts, sort_keys=True, separators=(",", ":")),
        },
    )


class AdminEffectAdmission:
    """Admin-owned AdmissionPort backed by the main Admin store."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], int],
        admission_ttl_ms: int = DEFAULT_ADMISSION_TTL_MS,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.admission_ttl_ms = admission_ttl_ms

    def load_provision_intent(self, operation_id: str) -> ProvisioningIntent:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT "
                        "  op.operation_id, op.state AS op_state, op.kind, op.idempotency_key, "
                        "  op.request_hash, op.request_json, op.access_epoch, "
                        "  o.operator_id, o.workspace_id, o.workspace_slug, o.email_key, "
                        "  o.issuer, o.desired_policy_id, o.desired_access, "
                        "  cd.component_deployment_id, cd.desired_release_id, "
                        "  r.artifact_digest, r.state AS release_state, r.component AS rel_comp, "
                        "  cm.deployment_id, cm.public_base_domain "
                        "FROM main.operations op "
                        "JOIN main.operators o ON o.operator_id = op.operator_id "
                        "JOIN main.component_deployments cd "
                        "  ON cd.component_deployment_id = op.component_deployment_id "
                        "JOIN main.qualified_releases r ON r.release_id = cd.desired_release_id "
                        "JOIN main.control_meta cm ON cm.id = 1 "
                        "WHERE op.operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["kind"] != "provision"
                or row["desired_access"] != "enabled"
                or row["rel_comp"] != "operator"
                or row["release_state"] != "qualified"
            ):
                raise HostAgentDenied()
            snap = (
                connection.execute(
                    text(
                        "SELECT cp.profile_ref, cp.free_budget_json "
                        "FROM main.capacity_snapshots cs "
                        "JOIN main.capacity_profiles cp "
                        "  ON cp.profile_ref = cs.profile_ref "
                        "  AND cp.profile_revision = cs.profile_revision "
                        "WHERE cs.id = 1"
                    )
                )
                .mappings()
                .one_or_none()
            )
            if snap is None:
                raise HostAgentUnavailable()

        budget = OperatorBudget.model_validate_json(snap["free_budget_json"])
        request_data = json.loads(row["request_json"])
        payload_data = request_data.get("payload", {})
        plan = ResourcePlan(
            workspace=budget.trees.workspace,
            control=budget.trees.control,
            scratch=budget.trees.scratch,
            image_id=row["desired_release_id"],
            release_id=row["desired_release_id"],
            image_digest=row["artifact_digest"],
            capacity_profile_ref=snap["profile_ref"],
        )
        return ProvisioningIntent(
            operation_id=row["operation_id"],
            operation_state=row["op_state"],
            idempotency_key=row["idempotency_key"],
            request_hash=row["request_hash"],
            operator_id=row["operator_id"],
            workspace_id=row["workspace_id"],
            component_deployment_id=row["component_deployment_id"],
            workspace_slug=row["workspace_slug"],
            public_origin=f"https://{row['workspace_slug']}.{row['public_base_domain']}",
            email_key=row["email_key"],
            issuer=row["issuer"],
            policy_id=row["desired_policy_id"],
            release_id=row["desired_release_id"],
            initial_data=payload_data.get("initial_data", "empty"),
            seed_bundle=payload_data.get("seed_bundle"),
            access_epoch=row["access_epoch"],
            deployment_id=row["deployment_id"],
            plan=plan,
        )

    def resolve(self, command: HostEffect) -> AdmittedEffect:
        """Authenticate original Admin provisioning intent and return pinned child inputs."""
        parent = command.effect.parent
        intent = self.load_provision_intent(parent.operation_id)
        if (
            intent.operation_state not in ADMITTABLE_STATES
            or parent.deployment_id != intent.deployment_id
            or parent.scope.operator_id != intent.operator_id
            or parent.scope.workspace_id != intent.workspace_id
            or parent.idempotency_key != intent.idempotency_key
            or parent.request_hash != intent.request_hash
            or command.access_epoch != intent.access_epoch
        ):
            raise HostAgentDenied()
        needs_plan = command.payload.action in {
            "prepare_resources",
            "initialize_container",
            "repair_runtime",
            "apply_limits",
        }
        plan = intent.plan if needs_plan else None
        public_origin = (
            intent.public_origin if command.payload.action == "prepare_resources" else None
        )
        if command.inputs_hash is not None:
            expected_inputs = (
                ResourceInputs(plan=plan, public_origin=public_origin) if plan is not None else None
            )
            if expected_inputs is None or semantic_hash(expected_inputs) != command.inputs_hash:
                raise HostAgentDenied()
        now = self.clock()
        return AdmittedEffect(
            command=command,
            admitted_at=now,
            expires_at=now + self.admission_ttl_ms,
            plan=plan,
            public_origin=public_origin,
        )

    def mark_running(self, operation_id: str, *, summary: str = "Provisioning started.") -> None:
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            row = (
                connection.execute(
                    text(
                        "SELECT operator_id, component_deployment_id, state "
                        "FROM main.operations WHERE operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["state"] not in ADMITTABLE_STATES:
                raise HostAgentDenied()
            connection.execute(
                text(
                    "UPDATE main.operations SET state = 'running', error_code = NULL, "
                    "updated_at = :now, revision = revision + 1 WHERE operation_id = :op_id"
                ),
                {"now": now, "op_id": operation_id},
            )
            connection.execute(
                text(
                    "UPDATE main.operators SET setup_state = 'preparing', "
                    "updated_at = :now, revision = revision + 1 WHERE operator_id = :op"
                ),
                {"now": now, "op": row["operator_id"]},
            )
            connection.execute(
                text(
                    "UPDATE main.component_deployments SET state = 'applying', "
                    "revision = revision + 1 WHERE component_deployment_id = :cd"
                ),
                {"cd": row["component_deployment_id"]},
            )
            _append_event(
                connection,
                operation_id=operation_id,
                event_code="provision_running",
                safe_summary=summary,
                recorded_at=now,
            )

    def mark_succeeded(
        self,
        operation_id: str,
        *,
        observation_ref: str,
        observed_usage_bytes: int,
        observed_at: int,
    ) -> None:
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            row = (
                connection.execute(
                    text(
                        "SELECT op.operator_id, op.component_deployment_id, op.state, "
                        "op.access_epoch, o.workspace_id, o.revision AS op_rev, "
                        "cd.desired_release_id "
                        "FROM main.operations op "
                        "JOIN main.operators o ON o.operator_id = op.operator_id "
                        "JOIN main.component_deployments cd "
                        "  ON cd.component_deployment_id = op.component_deployment_id "
                        "WHERE op.operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["state"] not in ADMITTABLE_STATES:
                raise HostAgentDenied()
            next_op_rev = row["op_rev"] + 1
            result = AdminResult(
                resource_id=row["operator_id"], revision=next_op_rev, state="ready"
            )
            connection.execute(
                text(
                    "UPDATE main.component_deployments SET state = 'applied', "
                    "observed_release_id = :rel, observation_ref = :obs_ref, "
                    "observed_at = :obs_at, revision = revision + 1 "
                    "WHERE component_deployment_id = :cd"
                ),
                {
                    "rel": row["desired_release_id"],
                    "obs_ref": observation_ref,
                    "obs_at": observed_at,
                    "cd": row["component_deployment_id"],
                },
            )
            connection.execute(
                text(
                    "UPDATE main.capacity_commitments SET state = 'active', "
                    "updated_at = :now, revision = revision + 1 WHERE operator_id = :op"
                ),
                {"now": now, "op": row["operator_id"]},
            )
            connection.execute(
                text(
                    "UPDATE main.operators SET setup_state = 'ready_for_claim', "
                    "updated_at = :now, revision = :rev WHERE operator_id = :op"
                ),
                {"now": now, "rev": next_op_rev, "op": row["operator_id"]},
            )
            connection.execute(
                text(
                    "UPDATE main.operations SET state = 'succeeded', "
                    "effect_reference = :obs_ref, result_json = :result_json, "
                    "error_code = NULL, updated_at = :now, revision = revision + 1 "
                    "WHERE operation_id = :op_id"
                ),
                {
                    "obs_ref": observation_ref,
                    "result_json": result.model_dump_json(),
                    "now": now,
                    "op_id": operation_id,
                },
            )
            existing_obs = connection.execute(
                text(
                    "SELECT revision FROM main.operator_source_observations WHERE operator_id = :op"
                ),
                {"op": row["operator_id"]},
            ).scalar_one_or_none()
            obs_params = {
                "op": row["operator_id"],
                "ws": row["workspace_id"],
                "epoch": row["access_epoch"],
                "usage": observed_usage_bytes,
                "usable": FREE_V1_USABLE_BYTES,
                "obs_at": observed_at,
                "checked_at": max(now, observed_at),
                "rev": 1 if existing_obs is None else int(existing_obs) + 1,
            }
            if existing_obs is None:
                connection.execute(
                    text(
                        "INSERT INTO main.operator_source_observations ("
                        "operator_id, workspace_id, access_epoch, effective_enabled, "
                        "usage_bytes, usable_bytes, source_revision, observed_at, "
                        "checked_at, freshness_state, revision"
                        ") VALUES ("
                        ":op, :ws, :epoch, 0, :usage, :usable, 1, :obs_at, :checked_at, "
                        "'known', :rev)"
                    ),
                    obs_params,
                )
            else:
                connection.execute(
                    text(
                        "UPDATE main.operator_source_observations SET "
                        "access_epoch = :epoch, effective_enabled = 0, usage_bytes = :usage, "
                        "usable_bytes = :usable, source_revision = 1, observed_at = :obs_at, "
                        "checked_at = :checked_at, freshness_state = 'known', revision = :rev "
                        "WHERE operator_id = :op"
                    ),
                    obs_params,
                )
            _append_event(
                connection,
                operation_id=operation_id,
                event_code="provision_succeeded",
                safe_summary="Workspace provisioned and ready for invitation claim.",
                recorded_at=now,
            )
            _append_audit(
                connection,
                _AuditRecord(
                    action="provision_succeeded",
                    operator_id=row["operator_id"],
                    operation_id=operation_id,
                    recorded_at=now,
                    safe_facts={
                        "observation_ref": observation_ref,
                        "observed_usage_bytes": observed_usage_bytes,
                    },
                ),
            )

    def mark_needs_attention(
        self,
        operation_id: str,
        *,
        error_code: str,
        summary: str,
        unknown: bool = False,
    ) -> None:
        with immediate_transaction(self.engine) as connection:
            now = self.clock()
            row = (
                connection.execute(
                    text(
                        "SELECT operator_id, component_deployment_id, state "
                        "FROM main.operations WHERE operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["state"] not in ADMITTABLE_STATES:
                raise HostAgentDenied()
            op_state = "unknown" if unknown else "needs_attention"
            commit_state = "unknown" if unknown else "pending"
            connection.execute(
                text(
                    "UPDATE main.operations SET state = :state, error_code = :code, "
                    "updated_at = :now, revision = revision + 1 WHERE operation_id = :op_id"
                ),
                {"state": op_state, "code": error_code, "now": now, "op_id": operation_id},
            )
            connection.execute(
                text(
                    "UPDATE main.operators SET setup_state = 'needs_attention', "
                    "updated_at = :now, revision = revision + 1 WHERE operator_id = :op"
                ),
                {"now": now, "op": row["operator_id"]},
            )
            connection.execute(
                text(
                    "UPDATE main.component_deployments SET state = 'needs_attention', "
                    "revision = revision + 1 WHERE component_deployment_id = :cd"
                ),
                {"cd": row["component_deployment_id"]},
            )
            connection.execute(
                text(
                    "UPDATE main.capacity_commitments SET state = :cstate, "
                    "updated_at = :now, revision = revision + 1 WHERE operator_id = :op"
                ),
                {"cstate": commit_state, "now": now, "op": row["operator_id"]},
            )
            _append_event(
                connection,
                operation_id=operation_id,
                event_code="provision_needs_attention",
                safe_summary=summary,
                recorded_at=now,
            )
            _append_audit(
                connection,
                _AuditRecord(
                    action="provision_needs_attention",
                    operator_id=row["operator_id"],
                    operation_id=operation_id,
                    recorded_at=now,
                    safe_facts={"error_code": error_code, "state": op_state},
                ),
            )
