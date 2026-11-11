"""H01.3 pure contracts; no persistence or actual host-effect qualification."""

import ast
from http import HTTPStatus
from pathlib import Path
from typing import Literal
import unicodedata

from pydantic import (
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
import pytest

from app.platform.api_errors import domain_problem, validation_problem
from app.platform.hosted_contracts.operations import (
    CommandEnvelope,
    CommandIntent,
    OperationOutcome,
    OperationState,
    SemanticConflict,
    TransportMetadata,
    original_result,
    transport_timeout,
)
from app.platform.hosted_contracts.reads import (
    ContinuationCursor,
    CursorContext,
    Freshness,
    FreshnessState,
)
from app.platform.hosted_contracts.semantic import SemanticRequest, canonical_bytes, semantic_hash
from app.platform.hosted_contracts.values import (
    AccessEpoch,
    CanonicalId,
    Component,
    Count,
    DeploymentScope,
    EpochMillis,
    IdempotencyKey,
    MAX_INTEGER,
    MAX_RECORD_BYTES,
    Reference,
    RequestHash,
    Revision,
    SafeCode,
    WorkspaceScope,
)

DEPLOYMENT = "00000000-0000-4000-8000-000000000001"
OPERATOR = "00000000-0000-4000-8000-000000000002"
WORKSPACE = "00000000-0000-4000-8000-000000000003"
OPERATION = "00000000-0000-4000-8000-000000000004"
RETRY = "00000000-0000-4000-8000-000000000005"
SCOPE = WorkspaceScope(operator_id=OPERATOR, workspace_id=WORKSPACE)


class HashFixture(SemanticRequest):
    initial_data: Literal["empty", "synthetic"] = "empty"
    note: str | None = None
    periods: tuple[str, ...] = ("oct", "nov")

    @field_validator("note")
    @classmethod
    def normalize(cls, value):
        return unicodedata.normalize("NFC", value.strip()) if value is not None else None


class ProvisionFixture(SemanticRequest):
    release_ref: Reference
    initial_data: Literal["empty", "synthetic"]
    seed_bundle: Reference | None
    capacity_profile: Reference
    reserved_bytes: Count
    ordered_resources: tuple[CanonicalId, ...]

    @model_validator(mode="after")
    def selected_seed(self):
        if (self.initial_data == "synthetic") != (self.seed_bundle is not None):
            raise ValueError("The owning fixture requires a seed only for synthetic data.")
        return self


class ResultFixture(SemanticRequest):
    binding_id: CanonicalId
    revision: Revision


class ValueFixture(SemanticRequest):
    value: object


def command(**changes):
    payload = ProvisionFixture(
        release_ref="operator-v1",
        initial_data="synthetic",
        seed_bundle="synthetic-v1",
        capacity_profile="free-proof-v1",
        reserved_bytes=50_000_000,
        ordered_resources=(OPERATOR, WORKSPACE),
    )
    values = dict(
        deployment_id=DEPLOYMENT,
        scope=SCOPE,
        kind="provision",
        expected_revision=1,
        access_epoch=1,
        payload=payload,
        component=Component.OPERATOR,
    )
    values.update(changes)
    intent = CommandIntent[ProvisionFixture](**values)
    return CommandEnvelope[ProvisionFixture](
        operation_id=OPERATION,
        idempotency_key="original-key",
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def outcome(state=OperationState.SUCCEEDED, **changes):
    values = dict(
        operation=command().reference(),
        state=state,
        revision=1,
        observed_at=1_794_355_200_000,
        result=None,
        error_code=None,
        action_required=None,
    )
    if state == OperationState.SUCCEEDED:
        values["result"] = ResultFixture(binding_id=WORKSPACE, revision=1)
    if state in {OperationState.FAILED, OperationState.NEEDS_ATTENTION}:
        values["error_code"] = "source_unavailable"
    if state in {OperationState.NEEDS_ATTENTION, OperationState.UNKNOWN}:
        values["action_required"] = "check_original_result"
    values.update(changes)
    return OperationOutcome[ResultFixture](**values)


@pytest.mark.parametrize(
    ("value_type", "valid", "invalid"),
    [
        (CanonicalId, DEPLOYMENT, "00000000-0000-4000-8000-00000000000A"),
        (CanonicalId, DEPLOYMENT, "{" + DEPLOYMENT + "}"),
        (CanonicalId, DEPLOYMENT, DEPLOYMENT.replace("-", "")),
        (CanonicalId, DEPLOYMENT, "not-a-uuid"),
        (Revision, 1, 0),
        (Revision, MAX_INTEGER, MAX_INTEGER + 1),
        (AccessEpoch, 1, True),
        (Count, 0, -1),
        (EpochMillis, 1_794_355_200_000, "2026-11-10T00:00:00Z"),
        (EpochMillis, 0, 1.5),
        (RequestHash, "a" * 64, "A" * 64),
        (SafeCode, "source_unavailable", "raw provider response"),
        (SafeCode, "x" * 80, "x" * 81),
        (Reference, "registered:v1", "/arbitrary/path"),
        (Reference, "a" * 1024, "a" * 1025),
        (IdempotencyKey, "k" * 120, "k" * 121),
        (Component, Component.ADMIN, "unknown"),
    ],
)
def test_strict_shared_values(value_type, valid, invalid):
    adapter = TypeAdapter(value_type)
    assert adapter.validate_python(valid) == valid
    with pytest.raises(ValidationError):
        adapter.validate_python(invalid)


@pytest.mark.parametrize(
    ("fixture", "encoded", "digest"),
    [
        (
            HashFixture(),
            b'{"initial_data":"empty","note":null,"periods":["oct","nov"]}',
            "8528da8745278a57d7aec96ef4a599fd1d90baafa890297a98a88f5aa5713ae6",
        ),
        (
            HashFixture(initial_data="synthetic", note=" Cafe\u0301 ", periods=("nov", "oct")),
            '{"initial_data":"synthetic","note":"Café","periods":["nov","oct"]}'.encode(),
            "769c21d8aecad063e26b72d167b1eea232eb7d5370f1a7dc32e9018faee2b9c2",
        ),
    ],
)
def test_fixed_vectors(fixture, encoded, digest):
    assert canonical_bytes(fixture) == encoded
    assert semantic_hash(fixture) == digest


def test_normalized_defaults_null_key_order_and_array_order():
    a = HashFixture.model_validate_json('{"periods":["oct","nov"],"note":null}')
    b = HashFixture.model_validate_json('{"note":null,"initial_data":"empty"}')
    assert semantic_hash(a) == semantic_hash(b) == semantic_hash(HashFixture())
    assert semantic_hash(a) != semantic_hash(HashFixture(note=""))
    assert semantic_hash(a) != semantic_hash(HashFixture(periods=("nov", "oct")))
    with pytest.raises(ValidationError):
        HashFixture(provider_payload={"undeclared": True})
    with pytest.raises(TypeError):
        semantic_hash({"note": None})


@pytest.mark.parametrize(
    "value",
    [
        {"undeclared": "payload"},
        ["mutable"],
        SecretStr("synthetic-secret"),
        b"bytes",
        1.5,
    ],
)
def test_unsafe_semantic_values(value):
    with pytest.raises(ValidationError):
        ValueFixture(value=value)


def test_utf8_size_integer_unicode_and_nesting_bounds():
    overhead = len(canonical_bytes(ValueFixture(value="")))
    body = "a" * (MAX_RECORD_BYTES - overhead)
    assert len(canonical_bytes(ValueFixture(value=body))) == MAX_RECORD_BYTES
    for value in (body + "é", "\ud800", MAX_INTEGER + 1):
        with pytest.raises(ValidationError):
            ValueFixture(value=value)
    nested = "leaf"
    for _ in range(20):
        nested = (nested,)
    with pytest.raises(ValidationError):
        ValueFixture(value=nested)


def test_serializer_exclusions_cannot_hide_intent():
    class Excluded(SemanticRequest):
        consequential: str = Field(exclude=True)

    assert semantic_hash(Excluded(consequential="a")) != semantic_hash(Excluded(consequential="b"))


@pytest.mark.parametrize(
    "field", ["deployment_id", "scope", "kind", "expected_revision", "access_epoch", "payload"]
)
def test_missing_consequential_fields_cannot_acquire_defaults(field):
    values = command().intent.model_dump()
    del values[field]
    with pytest.raises(ValidationError):
        CommandIntent[ProvisionFixture](**values)


def test_owning_validation_and_scope_are_not_bypassed_by_hashing():
    values = command().intent.payload.model_dump()
    values.update(initial_data="empty")
    with pytest.raises(ValidationError):
        ProvisionFixture(**values)
    with pytest.raises(ValidationError):
        DeploymentScope(workspace_id=WORKSPACE)
    with pytest.raises(ValidationError):
        WorkspaceScope(operator_id=OPERATOR)


@pytest.mark.parametrize(
    "changes",
    [
        {"deployment_id": RETRY},
        {"scope": DeploymentScope()},
        {"scope": WorkspaceScope(operator_id=RETRY, workspace_id=WORKSPACE)},
        {"scope": WorkspaceScope(operator_id=OPERATOR, workspace_id=RETRY)},
        {"kind": "repair_runtime"},
        {"expected_revision": 2},
        {"access_epoch": 2},
        {"component": Component.ADMIN},
    ],
)
def test_scope_and_fences_are_hashed(changes):
    assert command(**changes).request_hash != command().request_hash
    with pytest.raises(SemanticConflict):
        original_result(command(**changes), outcome())


@pytest.mark.parametrize(
    "changes",
    [
        {"release_ref": "operator-v2"},
        {"initial_data": "empty", "seed_bundle": None},
        {"seed_bundle": "synthetic-v2"},
        {"capacity_profile": "free-proof-v2"},
        {"reserved_bytes": 50_000_001},
        {"ordered_resources": (WORKSPACE, OPERATOR)},
    ],
)
def test_every_payload_field_is_consequential(changes):
    fields = command().intent.payload.model_dump()
    fields.update(changes)
    changed = command(payload=ProvisionFixture(**fields))
    assert changed.request_hash != command().request_hash
    with pytest.raises(SemanticConflict):
        original_result(changed, outcome())


def test_transport_is_excluded_and_matching_replay_keeps_original_identity():
    values = command().model_dump()
    values.update(operation_id=RETRY, transport=dict(correlation_id=RETRY, sent_at=0))
    retry = CommandEnvelope[ProvisionFixture](**values)
    retained = outcome()
    assert original_result(retry, retained) is retained
    assert retained.operation.operation_id == OPERATION
    assert original_result(retry, None) is None
    values["idempotency_key"] = "different-key"
    with pytest.raises(SemanticConflict):
        original_result(CommandEnvelope[ProvisionFixture](**values), retained)
    values["request_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        CommandEnvelope[ProvisionFixture](**values)
    with pytest.raises(ValidationError):
        TransportMetadata(correlation_id=RETRY, sent_at=0, provider_token="forbidden")


@pytest.mark.parametrize("state", tuple(OperationState))
def test_all_states_round_trip_and_replay(state):
    retained = outcome(state)
    decoded = OperationOutcome[ResultFixture].model_validate_json(retained.model_dump_json())
    assert decoded == retained
    assert original_result(command(), decoded) is decoded


@pytest.mark.parametrize(
    ("state", "changes"),
    [
        (OperationState.SUCCEEDED, {"result": None}),
        (OperationState.SUCCEEDED, {"error_code": "failed"}),
        (OperationState.SUCCEEDED, {"action_required": "retry"}),
        (OperationState.FAILED, {"error_code": None}),
        (OperationState.NEEDS_ATTENTION, {"error_code": None}),
        (OperationState.NEEDS_ATTENTION, {"action_required": None}),
        (OperationState.UNKNOWN, {"action_required": None}),
        (OperationState.PENDING, {"error_code": "failed"}),
        (OperationState.RUNNING, {"action_required": "retry"}),
        (OperationState.UNKNOWN, {"result": ResultFixture(binding_id=WORKSPACE, revision=1)}),
    ],
)
def test_inconsistent_outcomes(state, changes):
    with pytest.raises(ValidationError):
        outcome(state, **changes)


def test_timeout_is_unknown_and_success_immutable():
    observed = transport_timeout(command(), revision=2, observed_at=0)
    assert observed.state == OperationState.UNKNOWN
    assert observed.result is None
    assert observed.action_required == "check_original_result"
    retained = outcome()
    assert original_result(command(), retained) is retained
    assert retained.state == OperationState.SUCCEEDED
    with pytest.raises(ValidationError):
        retained.revision = 3


def test_existing_api_problem_mapping():
    problem = domain_problem(SemanticConflict(), status_code=HTTPStatus.CONFLICT)
    assert problem.status_code == HTTPStatus.CONFLICT
    assert problem.detail["code"] == "hosted_operation_conflict"
    with pytest.raises(ValidationError) as caught:
        outcome(result=None)
    assert validation_problem(caught.value).status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    with pytest.raises(ValidationError) as oversized:
        ValueFixture(value="x" * MAX_RECORD_BYTES)
    assert validation_problem(oversized.value).status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


@pytest.mark.parametrize("state", tuple(FreshnessState))
def test_valid_freshness(state):
    fields = {"state": state}
    if state in {FreshnessState.KNOWN, FreshnessState.STALE}:
        fields.update(as_of=0, source_revision="rev:1")
    else:
        fields["error_code"] = "source_unavailable"
    value = Freshness(**fields)
    assert Freshness.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "fields",
    [
        dict(state=FreshnessState.KNOWN),
        dict(state=FreshnessState.STALE, as_of=0),
        dict(state=FreshnessState.UNKNOWN),
        dict(state=FreshnessState.UNAVAILABLE, error_code="offline", as_of=0),
        dict(state=FreshnessState.KNOWN, as_of=0, source_revision="1", error_code="offline"),
    ],
)
def test_invalid_freshness(fields):
    with pytest.raises(ValidationError):
        Freshness(**fields)


def cursor_context(**changes):
    fields = dict(
        deployment_id=DEPLOYMENT,
        scope=SCOPE,
        endpoint="admin_operators",
        filter_hash="a" * 64,
        as_of=0,
        source_revision="rev:1",
        ordering_version=1,
    )
    fields.update(changes)
    return CursorContext(**fields)


def test_cursor_context_round_trip_and_binding():
    cursor = ContinuationCursor(
        context=cursor_context(), position=("A name with spaces", WORKSPACE)
    )
    decoded = ContinuationCursor.model_validate_json(cursor.model_dump_json())
    assert decoded == cursor
    decoded.require_context(cursor_context())
    for key, value in dict(
        deployment_id=RETRY,
        scope=DeploymentScope(),
        endpoint="other_endpoint",
        filter_hash="b" * 64,
        as_of=1,
        source_revision="rev:2",
        ordering_version=2,
    ).items():
        with pytest.raises(ValueError, match="restart"):
            decoded.require_context(cursor_context(**{key: value}))


@pytest.mark.parametrize(
    "changes",
    [
        {"position": ()},
        {"position": ("x",) * 9},
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"version": True},
        {"version": 2},
        {"position": ("x" * 1025,)},
    ],
)
def test_cursor_bounds(changes):
    fields = dict(context=cursor_context(), position=(WORKSPACE,))
    fields.update(changes)
    with pytest.raises(ValidationError):
        ContinuationCursor(**fields)


def test_contract_import_boundaries():
    directory = Path(__file__).parents[1] / "hosted_contracts"
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic", "boto3", "docker"}
    for path in directory.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
                assert not (node.module or "").startswith("app.modules.")
