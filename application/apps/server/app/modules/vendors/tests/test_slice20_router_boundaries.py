"""Focused boundary checks; domain persistence/lifecycle coverage stays in module tests."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.modules.owner_management.api import router as concerns
from app.modules.tenants.api import router as tenants
from app.modules.tenants.application.service import TenantProfilePatchCommand
from app.modules.vendors.api import router as vendors
from app.modules.vendors.application.service import ProviderNotFoundError


RAW_ID = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
CANONICAL_ID = str(UUID(RAW_ID))
RUNTIME = SimpleNamespace(ready=True, can_write=True, error=None)


@pytest.fixture
def routers():
    service = Mock()
    return [
        vendors.build_router(service, RUNTIME),
        vendors.build_category_router(service, RUNTIME),
        tenants.build_router(service, RUNTIME),
        concerns.build_router(service, RUNTIME),
    ]


def test_every_route_has_unique_explicit_operation_id_and_uuid_paths(routers):
    app = FastAPI()
    routes = [route for router in routers for route in router.routes]
    for router in routers:
        app.include_router(router)
    operation_ids = [route.operation_id for route in routes]
    assert {
        "get_provider_operation",
        "get_provider_operation_by_key",
        "get_tenant_operation",
        "get_tenant_operation_by_key",
    } <= set(operation_ids)
    assert all(operation_ids)
    assert len(set(operation_ids)) == len(operation_ids)
    schema = app.openapi()
    for route in routes:
        for method in route.methods:
            operation = schema["paths"][route.path][method.lower()]
            assert operation["operationId"] == route.operation_id
            for parameter in operation.get("parameters", []):
                if parameter["in"] == "path":
                    assert parameter["schema"]["format"] == "uuid"


@pytest.mark.parametrize(
    ("path", "suffix", "payload"),
    [
        ("services", "service", {"displayName": "Plumbing"}),
        ("service-areas", "area", {"displayName": "Portland", "countryCode": "US"}),
        (
            "work-history",
            "work_history",
            {"performedOn": "2026-09-01", "summary": "Repair", "propertyId": RAW_ID},
        ),
        ("references", "reference", {"referenceName": "Alex"}),
    ],
)
def test_generated_children_validate_and_canonicalize_ids(path, suffix, payload):
    service = Mock()
    for action in ("add", "update", "archive", "restore"):
        getattr(service, f"{action}_{suffix}").side_effect = ProviderNotFoundError("Missing")
    app = FastAPI()
    router = vendors.build_router(service, RUNTIME)
    app.include_router(router)
    operations = [
        ("POST", f"/api/providers/{{party_id}}/{path}", "add", payload),
        ("PATCH", f"/api/providers/{{party_id}}/{path}/{{item_id}}", "update", payload),
        (
            "POST",
            f"/api/providers/{{party_id}}/{path}/{{item_id}}/archive",
            "archive",
            {"confirmed": True},
        ),
        ("POST", f"/api/providers/{{party_id}}/{path}/{{item_id}}/restore", "restore", None),
    ]
    with TestClient(app) as client:
        for method, template, action, body in operations:
            route = next(route for route in router.routes if route.path == template)
            assert route.operation_id == f"{action}_provider_{suffix}"
            operation = getattr(service, f"{action}_{suffix}")
            for parameter in route.dependant.path_params:
                ids = {"party_id": RAW_ID, "item_id": RAW_ID, parameter.name: "invalid"}
                response = client.request(method, template.format(**ids), json=body)
                assert response.status_code == 422
                assert any(
                    error["loc"] == ["path", parameter.name] for error in response.json()["detail"]
                )
                operation.assert_not_called()
            response = client.request(
                method,
                template.format(party_id=RAW_ID, item_id=RAW_ID),
                json={**(body or {}), "expectedRevision": 1, "idempotencyKey": RAW_ID},
            )
            assert response.status_code == 404
            arguments = operation.call_args.args
            assert arguments[0] == CANONICAL_ID
            if action != "add":
                assert arguments[1] == CANONICAL_ID
            if suffix == "work_history" and action in ("add", "update"):
                assert arguments[-1].property_id == CANONICAL_ID


def test_provider_property_query_and_nested_create_use_canonical_strings():
    service = Mock()
    service.page.return_value = {"items": [], "nextCursor": None}
    service.create.side_effect = ProviderNotFoundError("Missing")
    app = FastAPI()
    app.include_router(vendors.build_router(service, RUNTIME))
    with TestClient(app) as client:
        assert client.get("/api/providers", params={"propertyId": "invalid"}).status_code == 422
        service.page.assert_not_called()
        assert client.get("/api/providers", params={"propertyId": RAW_ID}).status_code == 200
        assert service.page.call_args.args[0].property_id == CANONICAL_ID
        payload = {
            "expectedRevision": 0,
            "idempotencyKey": RAW_ID,
            "party": {"partyKind": "organization", "displayName": "Repair Team"},
            "workHistory": [
                {"performedOn": "2026-09-01", "summary": "Repair", "propertyId": RAW_ID}
            ],
        }
        assert client.post("/api/providers", json=payload).status_code == 404
        assert service.create.call_args.kwargs["work_history"][0].property_id == CANONICAL_ID
        service.create.reset_mock()
        payload["workHistory"][0]["propertyId"] = "invalid"
        assert client.post("/api/providers", json=payload).status_code == 422
        service.create.assert_not_called()


def test_tenant_contact_patch_preserves_omission_and_explicit_null():
    metadata = {"expectedRevision": 1, "idempotencyKey": RAW_ID}
    assert (
        tenants.ProfilePatchRequest(notes="Note", **metadata).command().preferred_contact_method_id
        is TenantProfilePatchCommand(notes="Note").preferred_contact_method_id
    )
    assert (
        tenants.ProfilePatchRequest(preferredContactMethodId=None, **metadata)
        .command()
        .preferred_contact_method_id
        is None
    )
    assert (
        tenants.ProfilePatchRequest(preferredContactMethodId=RAW_ID, **metadata)
        .command()
        .preferred_contact_method_id
        == CANONICAL_ID
    )
    with pytest.raises(ValidationError):
        tenants.ProfilePatchRequest(preferredContactMethodId="invalid", **metadata)


@pytest.mark.parametrize("instant", ["2026-09-01T10:00:00Z", "2026-09-01T10:00:00-07:00"])
def test_owner_concern_aware_instants_preserve_offset_and_reject_naive(instant):
    request = {
        "expectedRevision": 0,
        "ownerPartyId": RAW_ID,
        "propertyId": RAW_ID,
        "concernType": "general_rental",
        "summary": "Concern",
        "description": "Details",
        "raisedAtUtc": instant,
        "idempotencyKey": RAW_ID,
    }
    assert concerns.ConcernCreateRequest(**request).raisedAtUtc.utcoffset() is not None
    assert (
        concerns.FollowUpRequest(title="Follow up", dueAtUtc=instant).dueAtUtc.utcoffset()
        is not None
    )
    assert concerns.FollowUpRequest(title="Follow up", dueAtUtc=None).dueAtUtc is None
    request["raisedAtUtc"] = "2026-09-01T10:00:00"
    with pytest.raises(ValidationError) as create_error:
        concerns.ConcernCreateRequest(**request)
    assert [error["loc"] for error in create_error.value.errors()] == [("raisedAtUtc",)]
    with pytest.raises(ValidationError) as follow_up_error:
        concerns.FollowUpRequest(title="Follow up", dueAtUtc="2026-09-01T10:00:00")
    assert [error["loc"] for error in follow_up_error.value.errors()] == [("dueAtUtc",)]
