"""Slice 20: discover existing contracts without opening a workspace or enabling UI."""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.platform.testing_client import LocalApiClient as TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from app.bootstrap.api import create_app
from app.modules.files.api.router import CleanupAttentionResponse
from app.modules.owner_management.api.router import (
    ConcernCreateRequest,
    ConcernFollowUpRequest,
    ConcernFollowUpTaskResponse,
    ConcernPatchRequest,
    TransitionRequest,
)
from app.modules.tasks.domain.models import Task
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.workspace.application.service import WorkspaceService


@pytest.fixture
def contract_app(tmp_path):
    workspace = tmp_path / "never-initialized"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace)}), encoding="utf-8")
    with (
        patch.object(WorkspaceService, "open", side_effect=AssertionError("workspace opened")),
        patch.object(WorkspaceService, "initialize", side_effect=AssertionError("initialized")),
        patch.object(WorkspaceRuntime, "start", side_effect=AssertionError("runtime started")),
        patch.object(Engine, "connect", side_effect=AssertionError("database connected")),
    ):
        app = create_app(config)
        assert app.openapi() == create_app(config).openapi()
        yield app
    assert not workspace.exists()


def operations(schema):
    return {
        operation["operationId"]: operation
        for methods in schema["paths"].values()
        for operation in methods.values()
    }


@pytest.mark.parametrize(
    "operation_id,revision",
    [
        ("updateAiSettings", "expectedRevision"),
        ("createAiConnection", "expectedRevision"),
        ("updateAiConnection", "expectedRevision"),
        ("recordAiDisclosure", "expectedRevision"),
        ("updateAiActionLimit", "expectedRevision"),
        ("editAiDraft", "version"),
        ("approveAiDraft", "version"),
        ("dismissAiDraft", "version"),
    ],
)
def test_slice29_commands_require_concurrency_and_original_operation_result(
    contract_app, operation_id, revision
):
    schema = contract_app.openapi()
    command = operations(schema)[operation_id]
    request = resolve(schema, command["requestBody"]["content"]["application/json"]["schema"])
    assert {revision, "idempotencyKey"} <= set(request["required"])
    success = next(
        response for status, response in command["responses"].items() if status.startswith("2")
    )
    result = resolve(schema, success["content"]["application/json"]["schema"])
    assert "operationId" in result["required"]
    assert "409" in command["responses"]


@pytest.mark.parametrize("operation_id", ["getAiCommandByKey", "getAiCommandOperation"])
def test_slice29_receipt_recovery_has_typed_complete_results(contract_app, operation_id):
    schema = contract_app.openapi()
    operation = operations(schema)[operation_id]
    assert "requestBody" not in operation
    response = resolve(
        schema, operation["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert {"id", "idempotencyKey", "result", "requestFingerprint", "correlationId"} <= set(
        response["required"]
    )
    for result in result_contracts(schema, response["properties"]["result"]):
        assert "operationId" in result["required"]


def resolve(schema, value):
    while "$ref" in value:
        value = schema["components"]["schemas"][value["$ref"].rsplit("/", 1)[1]]
    return value


def result_contracts(schema, value):
    contract = resolve(schema, value)
    variants = contract.get("anyOf", contract.get("oneOf"))
    if variants is None:
        return [contract]
    return [leaf for variant in variants for leaf in result_contracts(schema, variant)]


@pytest.mark.parametrize(
    "operation_id",
    [
        "createExpenseCategory",
        "patchExpenseCategory",
        "archiveExpenseCategory",
        "restoreExpenseCategory",
    ],
)
def test_slice28_category_commands_have_exact_metadata_and_flat_results(contract_app, operation_id):
    schema = contract_app.openapi()
    operation = operations(schema)[operation_id]
    request = resolve(schema, operation["requestBody"]["content"]["application/json"]["schema"])
    assert request["additionalProperties"] is False
    assert {"expectedRevision", "idempotencyKey"} <= set(request["required"])
    revision = request["properties"]["expectedRevision"]
    assert revision["type"] == "integer"
    if operation_id == "createExpenseCategory":
        assert revision["minimum"] == revision["maximum"] == 0
    else:
        assert revision["minimum"] == 1
    assert request["properties"]["idempotencyKey"]["format"] == "uuid"
    if operation_id in {"archiveExpenseCategory", "restoreExpenseCategory"}:
        assert {"confirmed", "reason"} <= set(request["required"])
    response = operation["responses"]["201" if operation_id == "createExpenseCategory" else "200"]
    result = resolve(schema, response["content"]["application/json"]["schema"])
    assert {"id", "displayName", "revision", "operationId"} <= set(result["required"])
    assert "category" not in result["properties"]
    assert result["properties"]["operationId"]["format"] == "uuid"
    conflict = resolve(
        schema, operation["responses"]["409"]["content"]["application/json"]["schema"]
    )
    detail = resolve(schema, conflict["properties"]["detail"])
    current = next(
        v for v in detail["properties"]["currentCategory"]["anyOf"] if v.get("type") != "null"
    )
    assert {"id", "revision", "displayName"} <= set(resolve(schema, current)["required"])


@pytest.mark.parametrize(
    "path,operation_id,parameter",
    [
        (
            "/api/expense-categories/operations/{operation_id}",
            "getExpenseCategoryOperation",
            "operation_id",
        ),
        (
            "/api/expense-categories/operations/by-key/{key}",
            "getExpenseCategoryOperationByKey",
            "key",
        ),
    ],
)
def test_slice28_category_recovery_is_typed_original_read(
    contract_app, path, operation_id, parameter
):
    schema = contract_app.openapi()
    operation = schema["paths"][path]["get"]
    assert operation["operationId"] == operation_id
    assert "requestBody" not in operation
    assert len(operation["parameters"]) == 1
    identifier = operation["parameters"][0]
    assert identifier["name"] == parameter
    assert identifier["schema"]["format"] == "uuid"
    assert (
        operation["responses"]["200"]
        == operations(schema)["patchExpenseCategory"]["responses"]["200"]
    )


def test_slice28_category_read_requires_revision_with_optional_operation(contract_app):
    schema = contract_app.openapi()
    response = operations(schema)["listExpenseCategories"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    category = resolve(schema, response["items"])
    assert "revision" in category["required"]
    assert "operationId" not in category["required"]
    assert category["additionalProperties"] is False


@pytest.mark.parametrize(
    "operation_id",
    [
        "create_owner_concern",
        "update_owner_concern",
        "start_owner_concern",
        "resolve_owner_concern",
        "dismiss_owner_concern",
        "reopen_owner_concern",
        "add_owner_concern_follow_up",
    ],
)
def test_slice27_owner_concern_mutation_contracts(contract_app, operation_id):
    schema = contract_app.openapi()
    operation = operations(schema)[operation_id]
    request = resolve(schema, operation["requestBody"]["content"]["application/json"]["schema"])
    assert request["additionalProperties"] is False
    assert {"expectedRevision", "idempotencyKey"} <= set(request["required"])
    revision = request["properties"]["expectedRevision"]
    assert revision["type"] == "integer"
    if operation_id == "create_owner_concern":
        assert revision["minimum"] == revision["maximum"] == 0
    else:
        assert revision["minimum"] == 1
    assert request["properties"]["idempotencyKey"]["format"] == "uuid"
    assert all(
        parameter["name"] != "idempotencyKey" for parameter in operation.get("parameters", [])
    )
    if operation_id in {
        "start_owner_concern",
        "resolve_owner_concern",
        "dismiss_owner_concern",
        "reopen_owner_concern",
    }:
        assert "confirmed" in request["required"]
    result = resolve(schema, operation["responses"]["200"]["content"]["application/json"]["schema"])
    assert {"id", "summary", "revision", "operationId"} <= set(result["required"])
    assert result["properties"]["revision"]["minimum"] == 1
    assert result["properties"]["operationId"]["format"] == "uuid"
    task = next(
        item
        for item in result_contracts(schema, result["properties"]["followUpTask"])
        if item.get("type") != "null"
    )
    assert task["additionalProperties"] is False
    assert {"id", "revision", "title", "dueAtUtc", "waitingForKind", "deletedAtUtc"} <= set(
        task["required"]
    )
    conflict = resolve(
        schema, operation["responses"]["409"]["content"]["application/json"]["schema"]
    )
    detail = resolve(schema, conflict["properties"]["detail"])
    assert {"code", "message"} <= set(detail["required"])
    current = next(
        item
        for item in result_contracts(schema, detail["properties"]["current"])
        if item.get("type") != "null"
    )
    concern = resolve(
        schema,
        schema["paths"]["/api/owner-concerns/{concern_id}"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"],
    )
    assert current == concern
    assert "revision" in current["required"]
    assert "operationId" not in current["required"]


@pytest.mark.parametrize(
    ("path", "operation_id", "parameter"),
    [
        (
            "/api/owner-concerns/operations/{operation_id}",
            "get_owner_concern_operation",
            "operation_id",
        ),
        (
            "/api/owner-concerns/operations/by-key/{key}",
            "get_owner_concern_operation_by_key",
            "key",
        ),
    ],
)
def test_slice27_owner_concern_recovery_contracts(contract_app, path, operation_id, parameter):
    schema = contract_app.openapi()
    assert set(schema["paths"][path]) == {"get"}
    operation = schema["paths"][path]["get"]
    assert operation["operationId"] == operation_id
    assert "requestBody" not in operation
    assert len(operation["parameters"]) == 1
    identifier = operation["parameters"][0]
    assert identifier["name"] == parameter
    assert identifier["in"] == "path" and identifier["required"]
    assert identifier["schema"]["format"] == "uuid"
    original = operations(schema)["add_owner_concern_follow_up"]["responses"]["200"]
    assert operation["responses"]["200"] == original


@pytest.mark.parametrize(
    ("model", "payload", "revision"),
    [
        (
            ConcernCreateRequest,
            {
                "ownerPartyId": "00000000-0000-4000-8000-000000000001",
                "propertyId": "00000000-0000-4000-8000-000000000002",
                "concernType": "general_rental",
                "summary": "Concern",
                "description": "Description",
                "raisedAtUtc": "2026-01-01T12:00:00Z",
            },
            0,
        ),
        (ConcernPatchRequest, {"summary": "Updated"}, 1),
        (TransitionRequest, {"confirmed": True}, 1),
        (ConcernFollowUpRequest, {"title": "Follow up"}, 1),
    ],
)
def test_slice27_owner_concern_strict_required_metadata(model, payload, revision):
    valid = {**payload, "expectedRevision": revision, "idempotencyKey": str(uuid4())}
    model.model_validate(valid)
    for value in (True, False, "0", "1", 0.0, 1.0, None, -1, 1 if revision == 0 else 0):
        with pytest.raises(ValidationError):
            model.model_validate({**valid, "expectedRevision": value})
    for field in ("expectedRevision", "idempotencyKey"):
        with pytest.raises(ValidationError):
            model.model_validate({key: value for key, value in valid.items() if key != field})
    with pytest.raises(ValidationError):
        model.model_validate({**valid, "idempotencyKey": "not-a-uuid"})


def test_slice27_follow_up_receipt_preserves_complete_task_snapshot():
    stamp = "2026-01-01T12:00:00Z"
    snapshot = Task(
        id=str(uuid4()),
        title="Follow up",
        notes="Original notes",
        status="open",
        priority="normal",
        due_at_utc=stamp,
        due_timezone="UTC",
        is_all_day=False,
        completed_at_utc=None,
        cancelled_at_utc=None,
        outcome_note=None,
        related_entity_type="owner_concern",
        related_entity_id=str(uuid4()),
        related_label="Concern",
        created_at_utc=stamp,
        updated_at_utc=stamp,
    ).to_dict()
    result = ConcernFollowUpTaskResponse.model_validate(snapshot)
    assert result.model_dump(mode="json") == snapshot
    assert set(ConcernFollowUpTaskResponse.model_fields) == set(snapshot)
    with pytest.raises(ValidationError):
        ConcernFollowUpTaskResponse.model_validate({**snapshot, "id": "not-a-uuid"})
    with pytest.raises(ValidationError):
        ConcernFollowUpTaskResponse.model_validate(
            {key: value for key, value in snapshot.items() if key != "waitingForKind"}
        )


def test_deterministic_explicit_ids_and_concrete_success_contracts(contract_app):
    schema = contract_app.openapi()
    ids = []
    excluded = {"/api/workspace", "/api/workspace/initialize"}
    for path, methods in schema["paths"].items():
        for operation in methods.values():
            ids.append(operation["operationId"])
            if not path.startswith("/api/") or path in excluded or path.startswith("/api/audit/"):
                continue
            assert "_api_" not in operation["operationId"], path
            for code, response in operation["responses"].items():
                if not code.startswith("2") or code == "204":
                    continue
                if path.endswith("/content"):
                    assert response["content"]["application/octet-stream"]["schema"] == {
                        "type": "string",
                        "format": "binary",
                    }
                    continue
                result = resolve(schema, response["content"]["application/json"]["schema"])
                assert result.get("properties") or result.get("items") or result.get("anyOf"), path
    assert len(ids) == len(set(ids))
    assert {
        "listTasks",
        "getTask",
        "createCommunication",
        "getCommunicationOperation",
        "getPortfolioSpaceStatus",
        "getPortfolioStatusOperation",
        "getLease",
        "getConditionReport",
        "getMaintenanceIssue",
        "getFinanceCommandOperation",
        "getOwnerRentReport",
        "listOwnerRentReports",
        "getFileIntegrityAttention",
        "listParties",
        "getParty",
        "listCommunications",
    } <= set(ids)


@pytest.mark.parametrize(
    ("operation_id", "required", "revision"),
    [
        ("createTask", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("create_tenant", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("designate_party_as_tenant", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("update_tenant_profile", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("archive_tenant", {"expectedRevision", "idempotencyKey", "confirmed"}, "expectedRevision"),
        ("restore_tenant", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("create_provider", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("designate_party_as_provider", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("update_provider_profile", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        (
            "archive_provider",
            {"expectedRevision", "idempotencyKey", "confirmed"},
            "expectedRevision",
        ),
        ("restore_provider", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        (
            "leaseExecute",
            {"expectedRevision", "expectedLeaseRevision", "idempotencyKey"},
            "expectedRevision",
        ),
        (
            "changePortfolioSpaceOccupancy",
            {"expectedRevision", "idempotencyKey"},
            "expectedRevision",
        ),
        ("recordRentReceipt", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("recordExpense", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        (
            "createSecurityDepositAccount",
            {"expectedRevision", "idempotencyKey"},
            "expectedRevision",
        ),
        ("createPrepaidCheck", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("createMaintenanceIssue", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("createOwnerRentReport", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
        ("patchOwnerRentReport", {"expectedRevision", "idempotencyKey"}, "expectedRevision"),
    ],
)
def test_existing_commands_advertise_required_concurrency_and_conflicts(
    contract_app, operation_id, required, revision
):
    schema = contract_app.openapi()
    operation = operations(schema)[operation_id]
    request = resolve(schema, operation["requestBody"]["content"]["application/json"]["schema"])
    assert request["additionalProperties"] is False
    assert required <= set(request["required"])
    assert request["properties"][revision]["type"] == "integer"
    assert request["properties"][revision]["minimum"] >= 0
    conflict = resolve(
        schema, operation["responses"]["409"]["content"]["application/json"]["schema"]
    )
    assert "detail" in conflict["required"]


def test_provider_children_have_required_concurrency_and_original_results(contract_app):
    schema = contract_app.openapi()
    indexed = operations(schema)
    for suffix in ("service", "area", "work_history", "reference", "reputation_link"):
        for verb in ("add", "update", "archive", "restore"):
            operation = indexed[f"{verb}_provider_{suffix}"]
            request = resolve(
                schema, operation["requestBody"]["content"]["application/json"]["schema"]
            )
            assert request["additionalProperties"] is False
            assert {"expectedRevision", "idempotencyKey"} <= set(request["required"])
            assert request["properties"]["expectedRevision"]["minimum"] == 1
            assert request["properties"]["idempotencyKey"]["format"] == "uuid"
            assert "409" in operation["responses"]
            result = resolve(
                schema,
                operation["responses"]["201" if verb == "add" else "200"]["content"][
                    "application/json"
                ]["schema"],
            )
            assert set(result["required"]) == {"kind", "item", "profile", "revision", "operationId"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/tasks/not-a-uuid", None),
        ("get", "/api/leases/not-a-uuid", None),
        ("get", "/api/files/not-a-uuid", None),
        ("get", "/api/properties/not-a-uuid", None),
        (
            "post",
            "/api/tasks",
            {
                "title": "Task",
                "expectedRevision": True,
                "idempotencyKey": "00000000-0000-4000-8000-000000000000",
            },
        ),
        (
            "post",
            "/api/tasks",
            {
                "title": "Task",
                "expectedRevision": 0,
                "idempotencyKey": "00000000-0000-4000-8000-000000000000",
                "dueAtUtc": "2026-01-01T12:00:00",
                "dueTimezone": "UTC",
            },
        ),
    ],
)
def test_malformed_typed_requests_fail_before_workspace_access(contract_app, method, path, body):
    # No lifespan/startup: validation must reject before runtime/domain access.
    response = TestClient(contract_app).request(method, path, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_cleanup_identity_supports_local_digest_without_provider_locator():
    item = CleanupAttentionResponse(
        publicationId="a" * 64, provider="local", openedAt="2026-01-01T12:00:00+00:00"
    )
    assert item.publicationId == "a" * 64
    assert set(item.model_dump()) == {"publicationId", "provider", "openedAt"}


@pytest.mark.parametrize(
    "operation_id",
    [
        "getTaskCreationOperation",
        "getCommunicationOperation",
        "getPortfolioStatusOperation",
        "getFinanceCommandOperation",
        "getOwnerRentReportOperation",
        "getIntakeCommandReceipt",
        "get_provider_operation",
        "get_provider_operation_by_key",
        "get_provider_category_operation",
        "get_provider_category_operation_by_key",
    ],
)
def test_recovery_is_a_typed_read_only_original_result(contract_app, operation_id):
    schema = contract_app.openapi()
    operation = operations(schema)[operation_id]
    assert "requestBody" not in operation
    result = resolve(schema, operation["responses"]["200"]["content"]["application/json"]["schema"])
    for contract in result_contracts(schema, result):
        assert "operationId" in contract["required"]
        assert contract["properties"]["operationId"]["format"] == "uuid"


@pytest.mark.parametrize(
    "operation_id",
    [
        "create_provider",
        "designate_party_as_provider",
        "update_provider_profile",
        "archive_provider",
        "restore_provider",
        "get_provider_operation",
        "get_provider_operation_by_key",
    ],
)
def test_provider_original_results_have_required_revision_and_no_live_enrichments(
    contract_app, operation_id
):
    schema = contract_app.openapi()
    operation = operations(schema)[operation_id]
    response = next(value for code, value in operation["responses"].items() if code.startswith("2"))
    result = resolve(schema, response["content"]["application/json"]["schema"])
    contracts = result_contracts(schema, result)
    assert len(contracts) == (7 if operation_id.startswith("get_") else 1)
    for contract in contracts:
        expected = {"profile", "revision", "operationId"}
        expected |= (
            {"party", "partyRevision"} if "party" in contract["properties"] else {"kind", "item"}
        )
        if "category" in contract["properties"]:
            expected.add("category")
        assert set(contract["required"]) == expected
        assert set(contract["properties"]) == expected
        assert contract["properties"]["operationId"]["format"] == "uuid"
        profile = resolve(schema, contract["properties"]["profile"])
        assert "revision" in profile["required"]


def test_category_assignment_commands_have_explicit_concurrency_and_original_results(contract_app):
    schema = contract_app.openapi()
    catalog = operations(schema)
    category_ids = (
        "create_provider_category",
        "update_provider_category",
        "archive_provider_category",
        "restore_provider_category",
    )
    assignment_ids = (
        "assign_provider_category",
        "archive_provider_category_assignment",
        "restore_provider_category_assignment",
    )
    for operation_id in (*category_ids, *assignment_ids):
        operation = catalog[operation_id]
        body = resolve(schema, operation["requestBody"]["content"]["application/json"]["schema"])
        assert {"expectedRevision", "idempotencyKey"} <= set(body["required"])
        assert body["additionalProperties"] is False
        if operation_id in {"assign_provider_category", "restore_provider_category_assignment"}:
            assert "expectedCategoryRevision" in body["required"]
        result = resolve(
            schema,
            operation["responses"][
                "201"
                if operation_id in {"create_provider_category", "assign_provider_category"}
                else "200"
            ]["content"]["application/json"]["schema"],
        )
        assert {"category", "revision", "operationId"} <= set(result["required"])
        assert "revision" in resolve(schema, result["properties"]["category"])["required"]
        assert "409" in operation["responses"]
    for operation_id in (
        "get_provider_category_operation",
        "get_provider_category_operation_by_key",
    ):
        assert "requestBody" not in catalog[operation_id]
