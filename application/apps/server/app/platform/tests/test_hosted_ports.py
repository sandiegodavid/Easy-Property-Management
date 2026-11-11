"""Deterministic private-port fixtures, never native/provider or persistence proof."""

from importlib import import_module
from typing import Annotated, Literal, get_args, get_origin, get_type_hints
from types import UnionType

from pydantic import BaseModel, ValidationError
import pytest

from app.platform.hosted_contracts.authority import (
    ObservationPage,
    ObservationQuery,
    AdminAuthority,
    AdminRecoveryAuthority,
    IdentityAuthority,
    LocalRestoreAuthority,
    OperatorAuthority,
    OperatorRestoreAuthority,
    ServiceAuthority,
)
from app.platform.hosted_contracts.compatibility import (
    CompatibilityManifest,
    CompatibilityUnavailable,
    ComponentAssignment,
    QualificationEvidence,
    RuntimeCompatibility,
    SchemaRevision,
    SchemaStore,
    require_compatible,
)
from app.platform.hosted_contracts.operations import (
    CommandIntent,
    OperationOutcome,
    OperationState,
    original_result,
)
from app.platform.hosted_contracts.reads import Freshness, FreshnessState
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import Component, DeploymentScope, WorkspaceScope

ID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
SCOPE = WorkspaceScope(operator_id=ID, workspace_id=ID)
OWNERS = [
    ("hosted_admin.application.pilot_contracts", "Admin"),
    ("host_agent.application.contracts", "Host"),
    ("hosted_access.application.source_contracts", "Source"),
    ("hosted_access.application.login_contracts", "Login"),
    ("workspace.application.recovery_contracts", "WorkspaceRecovery"),
    ("hosted_admin.application.recovery_contracts", "AdminRecovery"),
]
MODULES = [(import_module("app.modules." + path), name) for path, name in OWNERS]
ACTIONS = [
    (module, name, action)
    for module, name in MODULES
    for action in get_args(get_args(module.Action)[0])
]


def sample(annotation, name):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return sample(args[0], name)
    if origin is Literal:
        return args[0]
    if origin is UnionType:
        return None if type(None) in args else sample(args[0], name)
    if origin is tuple:
        return (sample(args[0], name),)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return record(annotation)
    return primitive_sample(annotation, name)


def primitive_sample(annotation, name):
    if annotation is bool:
        return True
    if annotation is int:
        return 2 if name == "ends_at" else 1
    if name.endswith("_id") or name in {"binding_ids", "operator_id", "workspace_id"}:
        return ID
    if "hash" in name or "sha256" in name:
        return "a" * 64
    if name in {"email", "support_contact"}:
        return "fixture@example.invalid"
    return "fixture-v1"


def record(model):
    return model(
        **{
            name: sample(field.annotation, name)
            for name, field in model.model_fields.items()
            if field.is_required()
        }
    )


def make_command(module, name, action):
    payload = record(action)
    deployment = name == "AdminRecovery" or payload.action in {
        "create_assignment",
        "announce_maintenance",
    }
    intent = CommandIntent[module.Action](
        deployment_id=ID,
        scope=DeploymentScope() if deployment else SCOPE,
        kind=payload.action,
        expected_revision=1,
        access_epoch=1,
        component=Component.OPERATOR if payload.action == "maintenance_release" else None,
        payload=payload,
    )
    return getattr(module, name + "Command")(
        operation_id=ID,
        idempotency_key="fixture",
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def actor_for(name, command):
    if name == "Admin":
        return AdminAuthority(
            deployment_id=ID, principal_id=ID, identity_proof_ref="managed-proof", mfa_verified_at=1
        )
    if name == "Login":
        return IdentityAuthority(
            deployment_id=ID,
            scope=SCOPE,
            verified_identity_ref="identity",
            assignment_id=ID,
            registered_origin_id=ID,
            browser_binding_hash="a" * 64,
        )
    action = command.intent.payload.action
    if name in {"Host", "Source"}:
        service = (
            "operator_recovery"
            if action in {"stage_restore", "switch_binding", "verify_restore_binding"}
            else "admin"
        )
        return ServiceAuthority(
            deployment_id=ID,
            scope=command.intent.scope,
            service=service,
            authenticated_channel_ref="qualified-channel",
        )
    if action in {"capture", "capture_control", "reconcile_checkpoint"}:
        service = "admin_backup" if name == "AdminRecovery" else "operator_backup"
        return ServiceAuthority(
            deployment_id=ID,
            scope=command.intent.scope,
            service=service,
            authenticated_channel_ref="qualified-channel",
        )
    if name == "AdminRecovery":
        return AdminRecoveryAuthority(
            deployment_id=ID,
            bootstrap_principal_ref="protected-bootstrap",
            current_mfa_proof_ref="current-mfa",
            step_up_at=1,
            confirmed_request_hash=command.request_hash,
        )
    return operator_actor(command)


def operator_actor(command):
    if command.intent.payload.action == "confirm_restore":
        return OperatorRestoreAuthority(
            deployment_id=ID,
            scope=SCOPE,
            identity_proof_ref="current-operator",
            step_up_ref="strong-step-up",
            step_up_at=1,
            confirmed_request_hash=command.request_hash,
        )
    return OperatorAuthority(deployment_id=ID, scope=SCOPE, identity_proof_ref="current-operator")


class MemoryPort:
    """Preflight plus original-receipt comparison only; no durability claim."""

    def __init__(self, module, name):
        self.module, self.name, self.receipts, self.effects = module, name, {}, 0

    def execute(self, actor, command):
        self.module.require_invocation(actor, command)
        key = (command.intent.kind, command.idempotency_key)
        prior = original_result(command, self.receipts.get(key))
        if prior is not None:
            return prior
        result = record(getattr(self.module, self.name + "Result"))
        receipt = OperationOutcome[type(result)](
            operation=command.reference(),
            state=OperationState.SUCCEEDED,
            revision=1,
            observed_at=1,
            result=result,
        )
        self.receipts[key] = receipt
        self.effects += 1
        return receipt

    def original(self, actor, reference):
        if actor.deployment_id != reference.deployment_id:
            raise ValueError("Wrong deployment.")
        if hasattr(actor, "scope") and actor.scope != reference.scope:
            raise ValueError("Wrong scope.")
        return self.receipts.get((reference.kind, reference.idempotency_key))


@pytest.mark.parametrize(
    ("module", "name", "action"),
    ACTIONS,
    ids=[name + "." + action.__name__ for _, name, action in ACTIONS],
)
def test_all_owning_actions_validate_replay_and_lookup(module, name, action):
    command = make_command(module, name, action)
    actor = actor_for(name, command)
    port = MemoryPort(module, name)
    receipt = port.execute(actor, command)
    retry = type(command).model_validate({**command.model_dump(), "operation_id": OTHER})
    assert port.execute(actor, retry) is receipt
    assert port.original(actor, command.reference()) is receipt
    assert port.effects == 1
    assert receipt.operation.operation_id == ID
    for method in ("execute", "observe", "original"):
        assert get_type_hints(getattr(getattr(module, name + "Port"), method))["return"]


@pytest.mark.parametrize(("module", "name", "action"), ACTIONS)
def test_wrong_actor_denied_before_effect(module, name, action):
    command = make_command(module, name, action)
    port = MemoryPort(module, name)
    with pytest.raises((ValueError, ValidationError)):
        port.execute(object(), command)
    assert port.effects == 0 and not port.receipts


def manifest(component=Component.OPERATOR, state="passed"):
    stores = {
        Component.ADMIN: (SchemaStore.ADMIN, SchemaStore.ADMIN_RECOVERY),
        Component.OPERATOR: (SchemaStore.BUSINESS, SchemaStore.ACCESS, SchemaStore.RECOVERY),
        Component.TENANT: (),
        Component.OWNER: (),
    }[component]
    versions = tuple(SchemaRevision(store=store, revision="schema-v1") for store in stores)
    portal = component in {Component.TENANT, Component.OWNER}
    proof = QualificationEvidence(
        state=state,
        artifact_digest="a" * 64,
        evidence_ref="synthetic-proof" if state == "passed" else None,
    )
    return CompatibilityManifest(
        release_id=ID,
        component=component,
        artifact_kind="web_bundle" if portal else "oci_image",
        artifact_ref="registered-artifact",
        artifact_digest="a" * 64,
        oci_manifest_digest=None if portal else "b" * 64,
        api_contract="api-v1",
        source_contract="source-v1",
        agent_contract="agent-v1",
        inventory_revision="inventory-v1",
        owned_schemas=versions,
        readable_schemas=(SchemaRevision(store=SchemaStore.BUSINESS, revision="schema-v1"),)
        if portal
        else versions,
        native_qualification=proof,
        provider_qualification=proof,
    )


def pairing(value):
    assignment = ComponentAssignment(
        deployment_id=ID,
        component=value.component,
        scope=SCOPE if value.component == Component.OPERATOR else DeploymentScope(),
        release_id=ID,
    )
    runtime = RuntimeCompatibility(
        api_contract=value.api_contract,
        source_contract=value.source_contract,
        agent_contract=value.agent_contract,
        inventory_revision=value.inventory_revision,
        schemas=value.owned_schemas or value.readable_schemas,
    )
    return assignment, runtime


@pytest.mark.parametrize("component", tuple(Component))
def test_separate_artifacts_and_assignment_scopes(component):
    value = manifest(component)
    assignment, runtime = pairing(value)
    require_compatible(value, assignment, runtime)
    assert CompatibilityManifest.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        ComponentAssignment(
            deployment_id=ID,
            component=component,
            scope=DeploymentScope() if component == Component.OPERATOR else SCOPE,
            release_id=ID,
        )


@pytest.mark.parametrize("state", ["unavailable", "failed"])
def test_unresolved_qualification_never_admits_dispatch(state):
    value = manifest(state=state)
    assignment, runtime = pairing(value)
    effects = []
    with pytest.raises(CompatibilityUnavailable):
        require_compatible(value, assignment, runtime)
        effects.append("dispatch")
    assert not effects


@pytest.mark.parametrize(
    "field", ["api_contract", "source_contract", "agent_contract", "inventory_revision"]
)
def test_exact_peer_compatibility(field):
    value = manifest()
    assignment, runtime = pairing(value)
    mismatch = RuntimeCompatibility(**{**runtime.model_dump(), field: "unsupported-v2"})
    with pytest.raises(CompatibilityUnavailable):
        require_compatible(value, assignment, mismatch)


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_ref": "/path/to/image"},
        {"artifact_ref": "image:latest/tag"},
        {"oci_manifest_digest": None},
        {"owned_schemas": ()},
        {"version": True},
        {"version": 2},
        {"artifact_kind": "web_bundle"},
    ],
)
def test_wrong_or_incomplete_manifests(changes):
    with pytest.raises(ValidationError):
        CompatibilityManifest(**{**manifest().model_dump(), **changes})


def test_wrong_schema_release_or_evidence_digest():
    value = manifest()
    assignment, runtime = pairing(value)
    for fields in ({"schemas": ()}, {"schemas": runtime.schemas + runtime.schemas}):
        with pytest.raises((ValueError, ValidationError)):
            require_compatible(
                value, assignment, RuntimeCompatibility(**{**runtime.model_dump(), **fields})
            )
    with pytest.raises(CompatibilityUnavailable):
        require_compatible(
            value, ComponentAssignment(**{**assignment.model_dump(), "release_id": OTHER}), runtime
        )
    bad = value.native_qualification.model_dump()
    bad["artifact_digest"] = "c" * 64
    with pytest.raises(ValidationError):
        CompatibilityManifest(**{**value.model_dump(), "native_qualification": bad})
    with pytest.raises(ValidationError):
        QualificationEvidence(state="passed", artifact_digest="a" * 64, evidence_ref=None)


def test_restore_roles_confirmation_and_source_selected_destinations():
    module = MODULES[4][0]
    cmd = make_command(module, "WorkspaceRecovery", module.ConfirmRestore)
    admin = actor_for("Admin", cmd)
    with pytest.raises(ValueError):
        module.require_invocation(admin, cmd)
    weak = OperatorAuthority(deployment_id=ID, scope=SCOPE, identity_proof_ref="operator")
    with pytest.raises(ValueError):
        module.require_invocation(weak, cmd)
    wrong = OperatorRestoreAuthority(
        deployment_id=ID,
        scope=SCOPE,
        identity_proof_ref="operator",
        step_up_ref="step-up",
        step_up_at=1,
        confirmed_request_hash="b" * 64,
    )
    with pytest.raises(ValueError):
        module.require_invocation(wrong, cmd)
    local = LocalRestoreAuthority(
        deployment_id=ID,
        scope=SCOPE,
        os_owner_proof_ref="os-owner",
        confirmed_request_hash=cmd.request_hash,
    )
    module.require_invocation(local, cmd)
    with pytest.raises(ValidationError):
        module.ConfirmRestore(
            point_id=ID, preview_id=ID, confirmation_id=ID, destination="/tmp/custom"
        )
    control = MODULES[5][0]
    controlcmd = make_command(control, "AdminRecovery", control.ConfirmControlRestore)
    with pytest.raises(ValueError):
        control.require_invocation(admin, controlcmd)
    host = MODULES[1][0]
    hostcmd = make_command(host, "Host", host.SwitchBinding)
    service = ServiceAuthority(
        deployment_id=ID, scope=SCOPE, service="admin", authenticated_channel_ref="channel"
    )
    with pytest.raises(ValueError):
        host.require_invocation(service, hostcmd)
    with pytest.raises(ValidationError):
        host.InitializeContainer(binding_id=ID, image_id="latest", release_id=ID)


def test_unavailable_observations_are_not_zero_or_unbounded_pages():

    freshness = Freshness(state=FreshnessState.UNAVAILABLE, error_code="source_unavailable")
    assert (
        ObservationPage(items=(), matching_total=None, freshness=freshness).matching_total is None
    )
    with pytest.raises(ValidationError):
        ObservationPage(items=(), matching_total=0, freshness=freshness)
    with pytest.raises(ValidationError):
        ObservationQuery(deployment_id=ID, scope=SCOPE, limit=51)
