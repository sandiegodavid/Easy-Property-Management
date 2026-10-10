"""Slice 25 original child results, aggregate concurrency and portability proofs."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, text

from app.bootstrap.api import create_app
from app.modules.vendors.application.service import (
    ProviderError,
    ProviderLifecycleConflict,
    ProviderProfilePatchCommand,
    ServiceCommand,
    ServiceAreaCommand,
    WorkHistoryCommand,
    ReferenceCommand,
    ReputationLinkCommand,
    ReputationLinkPatchCommand,
)
from app.modules.vendors.infrastructure.sqlalchemy_models import PROVIDER_COMMAND_TRIGGERS
from app.modules.vendors.tests.test_command_readiness import (
    provider_services as provider_services,
    create,
)
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError

FAMILIES = [
    ("service", "services", ServiceCommand("Plumbing"), ServiceCommand("Electrical")),
    (
        "area",
        "service-areas",
        ServiceAreaCommand("Portland", "US"),
        ServiceAreaCommand("Salem", "US"),
    ),
    (
        "work_history",
        "work-history",
        WorkHistoryCommand("2025-01-01", "Before"),
        WorkHistoryCommand("2025-01-02", "After"),
    ),
    (
        "reference",
        "references",
        ReferenceCommand(reference_name="Before"),
        ReferenceCommand(reference_name="After"),
    ),
    (
        "reputation_link",
        "reputation-links",
        ReputationLinkCommand("google", "https://example.test/reviews"),
        ReputationLinkPatchCommand(notes="After"),
    ),
]


def invoke(service, action, party, *args, revision, key=None, **kwargs):
    return getattr(service, action)(
        party, *args, expected_revision=revision, idempotency_key=key or str(uuid4()), **kwargs
    )


@pytest.mark.parametrize("suffix,path,initial,changed", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_lifecycle_original_replay_and_noop(provider_services, suffix, path, initial, changed):
    workspace, service, audit = provider_services
    party = create(service)["party"]["id"]
    key = str(uuid4())
    with patch.object(
        service.unit_of_work, "detail", side_effect=AssertionError("post-commit read")
    ):
        first = invoke(service, f"add_{suffix}", party, initial, revision=1, key=key)
    item = first["item"]["id"]
    assert first["revision"] == 2 and first["profile"]["updatedAt"] == first["item"]["updatedAt"]
    changed_result = invoke(service, f"update_{suffix}", party, item, changed, revision=2)
    assert changed_result["revision"] == 3
    same = changed if suffix != "reputation_link" else ReputationLinkPatchCommand(notes="After")
    noop = invoke(service, f"update_{suffix}", party, item, same, revision=3)
    assert noop["revision"] == 3 and noop["item"] == changed_result["item"]
    assert noop["profile"] == changed_result["profile"]
    archived = invoke(service, f"archive_{suffix}", party, item, confirmed=True, revision=3)
    assert archived["revision"] == 4 and archived["item"]["archivedAt"] is not None
    restored = invoke(service, f"restore_{suffix}", party, item, revision=4)
    assert restored["revision"] == 5 and restored["item"]["archivedAt"] is None
    assert invoke(service, f"add_{suffix}", party, initial, revision=1, key=key) == first
    assert service.recover(operation_id=first["operationId"]) == first
    assert service.recover(key=key) == first
    assert audit.history("provider_command_operation", noop["operationId"])
    validate_latest_schema(workspace.paths.database)
    service.archive(party, confirmed=True, expected_revision=5, idempotency_key=str(uuid4()))
    assert invoke(service, f"add_{suffix}", party, initial, revision=1, key=key) == first
    with pytest.raises(ProviderLifecycleConflict):
        invoke(service, f"add_{suffix}", party, initial, revision=6)


@pytest.mark.parametrize(
    "revision,key", [(True, "valid"), (0, "valid"), ("1", "valid"), (1, "bad")]
)
def test_direct_contract_rejects_invalid_metadata(provider_services, revision, key):
    _, service, _ = provider_services
    party = create(service)["party"]["id"]
    with pytest.raises(ProviderError):
        service.add_service(
            party,
            ServiceCommand("Work"),
            expected_revision=revision,
            idempotency_key=str(uuid4()) if key == "valid" else key,
        )
    with pytest.raises(TypeError):
        service.add_service(party, ServiceCommand("Work"))


def test_changed_reuse_and_cross_family_conflict(provider_services):
    _, service, _ = provider_services
    party = create(service)["party"]["id"]
    key = str(uuid4())
    invoke(service, "add_service", party, ServiceCommand("Work"), revision=1, key=key)
    for action, command in [
        ("add_service", ServiceCommand("Other")),
        ("add_area", ServiceAreaCommand("Work")),
    ]:
        with pytest.raises(ProviderLifecycleConflict) as conflict:
            invoke(service, action, party, command, revision=1, key=key)
        assert conflict.value.code == "provider_idempotency_conflict"


def test_stale_child_and_profile_commands_share_one_revision(provider_services):
    _, service, _ = provider_services
    party = create(service)["party"]["id"]
    child = invoke(service, "add_service", party, ServiceCommand("Work"), revision=1)
    with pytest.raises(ProviderLifecycleConflict) as conflict:
        service.update_profile(
            party,
            ProviderProfilePatchCommand(notes="stale"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert conflict.value.code == "provider_revision_conflict"
    assert conflict.value.current == child["profile"]


@pytest.mark.parametrize("duplicate", [True, False])
def test_concurrent_children(provider_services, duplicate):
    _, service, _ = provider_services
    party = create(service)["party"]["id"]
    barrier, key = Barrier(2), str(uuid4())

    def run(index):
        barrier.wait(timeout=10)
        try:
            return invoke(
                service,
                "add_reference",
                party,
                ReferenceCommand(reference_name="Same" if duplicate else str(index)),
                revision=1,
                key=key if duplicate else str(uuid4()),
            )
        except ProviderLifecycleConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    if duplicate:
        assert results[0] == results[1]
    else:
        assert sum(isinstance(r, ProviderLifecycleConflict) for r in results) == 1
    assert service.detail(party)["profile"]["revision"] == 2
    assert len(service.detail(party)["references"]) == 1


@pytest.mark.parametrize("suffix,path,initial,changed", FAMILIES, ids=[f[0] for f in FAMILIES])
@pytest.mark.parametrize("verb", ["create", "update", "archive", "restore"])
def test_receipt_audit_failure_rolls_back_child_profile_and_receipt(
    provider_services, suffix, path, initial, changed, verb
):
    workspace, service, _ = provider_services
    party = create(service)["party"]["id"]
    revision, arguments, kwargs = 1, (initial,), {}
    if verb != "create":
        first = invoke(service, f"add_{suffix}", party, initial, revision=1)
        item, revision = first["item"]["id"], 2
        arguments = (item, changed) if verb == "update" else (item,)
        if verb == "archive":
            kwargs["confirmed"] = True
        if verb == "restore":
            invoke(service, f"archive_{suffix}", party, item, revision=2, confirmed=True)
            revision = 3
    before = service.detail(party, include_archived=True)
    original = service.unit_of_work.recorder.record_change

    def fail(connection, **fields):
        if fields["entity_type"] == "provider_command_operation":
            raise RuntimeError("receipt audit unavailable")
        return original(connection, **fields)

    with patch.object(service.unit_of_work.recorder, "record_change", side_effect=fail):
        with pytest.raises(RuntimeError):
            action = "add" if verb == "create" else verb
            invoke(service, f"{action}_{suffix}", party, *arguments, revision=revision, **kwargs)
    assert service.detail(party, include_archived=True) == before
    with service.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM provider_command_operations")
            ).scalar_one()
            == revision
        )
        validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize("tamper", ["child", "audit", "request", "result"])
def test_retained_tampering_rejected(provider_services, tamper):
    workspace, service, _ = provider_services
    party = create(service)["party"]["id"]
    first = invoke(service, "add_service", party, ServiceCommand("Work"), revision=1)
    with service.unit_of_work.engine.begin() as connection:
        if tamper == "child":
            connection.execute(
                text(
                    "UPDATE provider_services SET display_name='Changed', normalized_name='changed'"
                )
            )
        elif tamper == "audit":
            connection.execute(text("DROP TRIGGER audit_events_no_delete"))
            connection.execute(
                text("DELETE FROM audit_events WHERE entity_type='provider_service'")
            )
        else:
            connection.execute(text("DROP TRIGGER provider_command_operations_no_update"))
            column = "request_json" if tamper == "request" else "result_json"
            row = connection.execute(
                text(f"SELECT {column} FROM provider_command_operations WHERE id=:id"),
                {"id": first["operationId"]},
            ).scalar_one()
            value = json.loads(row)
            if tamper == "request":
                value["payload"]["fields"]["display_name"] = "Changed"
            else:
                value["item"]["displayName"] = "Changed"
            connection.execute(
                text(f"UPDATE provider_command_operations SET {column}=:value WHERE id=:id"),
                {
                    "value": json.dumps(value, sort_keys=True, separators=(",", ":")),
                    "id": first["operationId"],
                },
            )
            connection.execute(
                text(PROVIDER_COMMAND_TRIGGERS["provider_command_operations_no_update"])
            )
    with service.unit_of_work.engine.connect() as connection:
        with pytest.raises(MigrationSchemaError):
            validate_latest_schema(workspace.paths.database)


def test_child_recovery_is_single_indexed_read(provider_services):
    _, service, _ = provider_services
    party = create(service)["party"]["id"]
    key = str(uuid4())
    first = invoke(service, "add_service", party, ServiceCommand("Work"), revision=1, key=key)
    reads = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert service.recover(operation_id=first["operationId"]) == first
        assert len(reads) == 1 and "WHERE provider_command_operations.id" in reads[0]
        reads.clear()
        assert service.recover(key=key) == first
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", capture)
    assert len(reads) == 1 and "WHERE provider_command_operations.idempotency_key" in reads[0]


def test_api_child_contract_replay_conflict_and_required_metadata(provider_services):
    workspace, _, _ = provider_services
    workspace.config.config_path.write_text(
        json.dumps({"localWorkspacePath": str(workspace.paths.root)})
    )
    with TestClient(create_app(workspace.config.config_path)) as client:
        first = client.post(
            "/api/providers",
            json={
                "party": {"partyKind": "organization", "displayName": "HTTP"},
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        ).json()
        path = f"/api/providers/{first['party']['id']}/services"
        assert client.post(path, json={"displayName": "Work"}).status_code == 422
        payload = {"displayName": "Work", "expectedRevision": 1, "idempotencyKey": str(uuid4())}
        response = client.post(path, json=payload)
        assert response.status_code == 201
        result = response.json()
        assert client.post(path, json=payload).json() == result
        assert client.get(f"/api/providers/operations/{result['operationId']}").json() == result
        conflict = client.post(
            path, json={**payload, "displayName": "Changed", "idempotencyKey": str(uuid4())}
        )
        assert (
            conflict.status_code == 409
            and conflict.json()["detail"]["current"] == result["profile"]
        )
