"""UI-001 generated-client readiness over real governance persistence."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event

from app.modules.ai_governance.api.responses import DraftDetailResponse, SettingsResponse
from app.modules.ai_governance.api.router import build_router


@pytest.fixture
def ai_http():
    from app.modules.ai_governance.tests.test_governance import AiGovernanceTests

    fixture = AiGovernanceTests()
    fixture.setUp()
    app = FastAPI()
    app.include_router(
        build_router(
            fixture.configuration,
            fixture.generation,
            fixture.drafts,
            SimpleNamespace(ready=True, can_write=True, error=None),
            fixture.service.external,
        )
    )
    with TestClient(app) as client:
        try:
            yield fixture, client
        finally:
            fixture.unit_of_work.engine.dispose()
            fixture.tearDown()


def generate(fixture):
    return fixture.generation.run(
        action_type="synthetic_action",
        source_entity_type="synthetic",
        source_entity_id="source",
        source_revision="1",
        source_fingerprint="a" * 64,
        candidate={"message": "safe", "private": "excluded"},
        idempotency_key=str(uuid4()),
    )["draft"]["id"]


def test_every_ai_json_operation_has_a_named_response_contract(ai_http):
    _, client = ai_http
    schema = client.get("/openapi.json").json()
    identifiers = []
    for path, methods in schema["paths"].items():
        assert path.startswith("/api/ai/")
        for operation in methods.values():
            identifiers.append(operation["operationId"])
            for code, response in operation["responses"].items():
                if not code.startswith("2") or code == "204":
                    continue
                contract = response["content"]["application/json"]["schema"]
                if contract.get("type") == "array":
                    contract = contract["items"]
                assert "$ref" in contract, (path, contract)
    assert len(set(identifiers)) == len(identifiers)
    detail = schema["components"]["schemas"]["DraftDetailResponse"]
    assert {"provenance", "currentSource", "governedInput", "reviewHistory"} <= set(
        detail["required"]
    )


def test_configuration_contracts_use_persisted_results(ai_http):
    fixture, client = ai_http
    settings = client.get("/api/ai/settings")
    assert settings.status_code == 200
    parsed = SettingsResponse.model_validate(settings.json())
    assert not parsed.readiness.ready
    assert parsed.readiness.reason == "explicit_probe_required"
    assert parsed.registeredAdapters[0].executionLocation == "on_device"
    connection = client.get("/api/ai/connections").json()[0]
    assert connection["runtimeId"] == "runtime"
    assert connection["modelArtifactDigest"] == "digest"
    assert "credential" not in connection
    assert client.post(
        f"/api/ai/connections/{connection['id']}/test",
        json={"expectedRevision": connection["revision"], "idempotencyKey": str(uuid4())},
    ).json()["result"] == {
        "status": "completed",
        "ready": True,
        "reason": None,
    }
    key = str(uuid4())
    request = {"killSwitch": True, "idempotencyKey": key, "expectedRevision": parsed.revision}
    first = client.put("/api/ai/settings", json=request)
    retry = client.put("/api/ai/settings", json=request)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert first.json()["killSwitch"]
    limit = client.get("/api/ai/limits").json()[0]
    changed = client.put(
        "/api/ai/limits/synthetic_action",
        json={
            **{
                name: value
                for name, value in limit.items()
                if name not in {"actionType", "updatedAt", "revision"}
            },
            "expectedRevision": limit["revision"],
            "idempotencyKey": str(uuid4()),
        },
    )
    assert changed.status_code == 200
    assert changed.json()["allowedModels"] == limit["allowedModels"]
    profiles = client.get("/api/ai/redaction-profiles").json()
    assert profiles[0]["actionTypes"] == ["synthetic_action"]
    assert fixture.provider.calls == 0


def test_draft_detail_exposes_frozen_provenance_without_extra_reads(ai_http):
    fixture, client = ai_http
    draft_id = generate(fixture)
    statements = []
    event.listen(
        fixture.unit_of_work.engine,
        "before_cursor_execute",
        lambda *args: statements.append(args[2]),
    )
    response = client.get(f"/api/ai/drafts/{draft_id}")
    assert response.status_code == 200
    detail = DraftDetailResponse.model_validate(response.json())
    assert detail.governedInput == {"message": "safe"}
    assert detail.draftPayload == {"summary": "safe"}
    assert detail.provenance.transportProvider == "synthetic"
    assert detail.provenance.modelIdentifier == "synthetic-model"
    assert detail.provenance.executionLocation == "on_device"
    assert detail.provenance.runtimeId == "runtime"
    assert detail.currentSource.comparisonState == "current"
    assert detail.supersedesDraftId is None
    assert detail.terminalAt is None
    assert len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]) <= 2
    connection_id = fixture.configuration.connections()[0]["id"]
    fixture.configuration.update_connection(
        connection_id,
        expected_revision=1,
        data={"runtime_version": "2"},
        idempotency_key=str(uuid4()),
    )
    assert (
        client.get(f"/api/ai/drafts/{draft_id}").json()["provenance"]
        == response.json()["provenance"]
    )


def test_review_mutations_and_history_have_valid_response_contracts(ai_http):
    fixture, client = ai_http
    draft_id = generate(fixture)
    page = client.get("/api/ai/drafts").json()
    assert page["items"][0]["id"] == draft_id
    edited = client.patch(
        f"/api/ai/drafts/{draft_id}",
        json={
            "version": 1,
            "draftPayload": {"summary": "Reviewed"},
            "operatorNote": "Checked",
            "idempotencyKey": str(uuid4()),
        },
    )
    assert edited.status_code == 200
    assert edited.json()["version"] == 2
    dismissed = client.post(
        f"/api/ai/drafts/{draft_id}/dismiss", json={"version": 2, "idempotencyKey": str(uuid4())}
    )
    assert dismissed.status_code == 200
    detail = client.get(f"/api/ai/drafts/{draft_id}").json()
    assert detail["status"] == "dismissed"
    assert [row["decision"] for row in detail["reviewHistory"]] == ["edited", "dismissed"]
    assert detail["terminalAt"] is not None
    approved_id = generate(fixture)
    approved = client.post(
        f"/api/ai/drafts/{approved_id}/approve", json={"version": 1, "idempotencyKey": str(uuid4())}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["resultEntityId"]


def test_invalid_typed_inputs_and_envelopes_fail_closed(ai_http):
    _, client = ai_http
    assert client.get("/api/ai/drafts?status=unknown").status_code == 422
    assert (
        client.post("/api/ai/connections", json={"executionLocation": "other"}).status_code == 422
    )
    response = client.get("/api/ai/settings").json()
    with pytest.raises(ValidationError):
        SettingsResponse.model_validate({**response, "killSwitch": "yes"})
    with pytest.raises(ValidationError):
        SettingsResponse.model_validate({**response, "credential": "secret"})


def test_slice29_recovery_conflicts_and_required_command_metadata(ai_http):
    _, client = ai_http
    settings = client.get("/api/ai/settings").json()
    key = str(uuid4())
    request = {"expectedRevision": settings["revision"], "idempotencyKey": key, "killSwitch": True}
    first = client.put("/api/ai/settings", json=request)
    assert first.status_code == 200
    original = first.json()
    changed = client.put(
        "/api/ai/settings",
        json={
            "expectedRevision": original["revision"],
            "idempotencyKey": str(uuid4()),
            "killSwitch": False,
        },
    )
    assert changed.status_code == 200
    assert client.put("/api/ai/settings", json=request).json() == original
    by_key = client.get(f"/api/ai/command-operations/by-key/{key}")
    assert by_key.status_code == 200
    assert by_key.json()["result"] == original
    assert (
        client.get(f"/api/ai/command-operations/{original['operationId']}").json() == by_key.json()
    )
    conflict = client.put("/api/ai/settings", json={**request, "idempotencyKey": str(uuid4())})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["revision"] == changed.json()["revision"]
    assert conflict.json()["detail"]["current"]["killSwitch"] is False
    assert client.put("/api/ai/settings", json={"killSwitch": True}).status_code == 422
    assert client.get(f"/api/ai/command-operations/{uuid4()}").status_code == 404
    assert client.get("/api/ai/command-operations/by-key/invalid").status_code == 422


def test_slice29_openapi_enforces_command_contracts(ai_http):
    _, client = ai_http
    schema = client.get("/openapi.json").json()
    models = schema["components"]["schemas"]
    for model in (
        "SettingsInput",
        "ConnectionInput",
        "ConnectionPatch",
        "DisclosureInput",
        "LimitInput",
    ):
        assert {"expectedRevision", "idempotencyKey"} <= set(models[model]["required"])
    for model in ("DraftEditInput", "DraftDecisionInput"):
        assert {"version", "idempotencyKey"} <= set(models[model]["required"])
    assert "operationId" in models["DraftApprovalResponse"]["required"]
    assert (
        schema["paths"]["/api/ai/command-operations/by-key/{key}"]["get"]["operationId"]
        == "getAiCommandByKey"
    )
    assert (
        schema["paths"]["/api/ai/command-operations/{operation_id}"]["get"]["operationId"]
        == "getAiCommandOperation"
    )
