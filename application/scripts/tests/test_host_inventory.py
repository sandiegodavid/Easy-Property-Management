"""Host inventory tests use isolated directories and never touch live services."""

from dataclasses import replace
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from scripts.host_inventory import (
    HostInventory,
    Instance,
    InventoryError,
    MaintenanceRequest,
    discrepancies,
    new_identity,
)


@pytest.fixture
def inventory(tmp_path):
    root = tmp_path / "control"
    root.mkdir(mode=0o700)
    store = HostInventory(root / "inventory.sqlite", owner_uid=os.getuid())
    store.initialize()
    return store


def instance(key):
    instance_id, allocation_id = new_identity()
    return Instance(
        key=key,
        instance_id=instance_id,
        allocation_id=allocation_id,
        operator_id=str(uuid4()),
        workspace_id=str(uuid4()),
        email=f"{key}@example.com",
        hostname=f"demo-{key}.example.com",
        port={"a": 8001, "b": 8002, "c": 8012}[key],
        user=f"epm-{key}",
        mount=f"/var/lib/epm-{key}/volume",
        image=f"/var/lib/epm-{key}/volume.img",
        release="release-20261026-02",
        profile="demo-profile",
        template="synthetic-v1",
        config_digest="a" * 64,
        baseline_digest="b" * 64,
        local_config=f"/var/lib/epm-{key}/hosted-local.json",
        access_database=f"/var/lib/epm-{key}/access/access.sqlite",
        workspace=f"/var/lib/epm-{key}/volume/workspace",
    )


def test_three_independent_allocations_survive_reopen(inventory):
    items = [instance(key) for key in ("a", "b", "c")]
    for item in items:
        inventory.register(item)
    assert inventory.list() == items
    assert HostInventory(inventory.path, owner_uid=os.getuid()).list() == items


@pytest.mark.parametrize(
    "field",
    [
        "key",
        "instance_id",
        "allocation_id",
        "operator_id",
        "workspace_id",
        "email",
        "hostname",
        "port",
        "mount",
        "image",
        "local_config",
        "access_database",
    ],
)
def test_duplicate_allocations_are_atomic(inventory, field):
    first, second = instance("a"), instance("c")
    inventory.register(first)
    if field == "mount":
        second = replace(second, workspace=first.mount + "/other")
    if field == "key":
        second = replace(second, user=first.user)
    with pytest.raises(InventoryError, match="already registered"):
        inventory.register(replace(second, **{field: getattr(first, field)}))
    assert inventory.list() == [first]


def test_changed_observations_are_explicit(inventory):
    item = instance("a")
    inventory.register(item)
    assert discrepancies(item, replace(item, port=8010, config_digest="c" * 64)) == (
        "port",
        "config_digest",
    )
    assert inventory.list() == [item]


def test_mount_and_image_cannot_share_a_path_across_allocations(inventory):
    first = instance("a")
    inventory.register(first)
    with pytest.raises(InventoryError, match="already registered"):
        inventory.register(replace(instance("c"), image=first.mount))
    assert inventory.list() == [first]


def test_inventory_rejects_symlinks_and_insecure_files(inventory, tmp_path):
    alias = inventory.path.parent / "alias.sqlite"
    alias.symlink_to(inventory.path)
    with pytest.raises(InventoryError, match="regular file"):
        HostInventory(alias, owner_uid=os.getuid()).list()
    inventory.path.chmod(0o644)
    with pytest.raises(InventoryError, match="owner-private"):
        inventory.list()


def test_invalid_retained_timestamp_is_rejected(inventory):
    inventory.register(instance("a"))
    with sqlite3.connect(inventory.path) as connection:
        connection.execute("UPDATE instances SET registered_at = '2026-01-01T00:00:00'")
    with pytest.raises(InventoryError, match="retained inventory"):
        inventory.list()


def test_missing_inventory_is_not_treated_as_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        HostInventory(Path(tmp_path) / "missing.sqlite", owner_uid=os.getuid()).list()


def test_changed_append_only_trigger_is_not_accepted(inventory):
    with sqlite3.connect(inventory.path) as connection:
        connection.execute("DROP TRIGGER inventory_audit_no_update")
        connection.execute(
            "CREATE TRIGGER inventory_audit_no_update "
            "BEFORE UPDATE ON inventory_audit BEGIN SELECT 1; END"
        )
    with pytest.raises(InventoryError, match="invalid or unreadable"):
        inventory.list()


def test_instance_allocations_cannot_be_deleted(inventory):
    item = instance("a")
    inventory.register(item)
    with (
        sqlite3.connect(inventory.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="must be retained"),
    ):
        connection.execute("DELETE FROM instances")
    assert inventory.list() == [item]


def test_reconciliation_conflict_rolls_back_all_rows_and_keeps_operation_pending(inventory):
    first, second = instance("a"), instance("c")
    inventory.register(first)
    inventory.register(second)
    identifier = inventory.begin_maintenance(
        "reconciliation",
        "breakglass",
        "a" * 64,
        request=MaintenanceRequest(incident="test-atomic-update"),
    )
    inventory.finish_maintenance(identifier, 0)
    updated_first = replace(first, config_digest="c" * 64, revision=2)
    stale_second = replace(second, revision=2)
    with pytest.raises(InventoryError, match="changed during reconciliation"):
        inventory.reconcile(
            identifier,
            [(first, updated_first), (stale_second, replace(stale_second, revision=3))],
            "b" * 64,
        )
    assert inventory.list() == [first, second]
    assert inventory.maintenance(identifier)["state"] == "needs_reconciliation"


def test_resume_retains_operation_identity_and_clears_only_current_attempt_outcome(inventory):
    inventory.register(instance("a"))
    identifier = inventory.begin_maintenance(
        "release", "deploy", "a" * 64, MaintenanceRequest(key="a", release="release-20261027-01")
    )
    inventory.finish_maintenance(identifier, 1)
    assert (
        inventory.begin_maintenance(
            "release", "resume", "b" * 64, request=MaintenanceRequest(resume=identifier)
        )
        == identifier
    )
    row = inventory.maintenance(identifier)
    assert row["state"] == "running"
    assert row["exit_code"] is None
    assert row["finished_at"] is None
    with inventory.connection() as connection:
        events = [
            row[0]
            for row in connection.execute(
                "SELECT action FROM inventory_audit WHERE reference = ? ORDER BY sequence",
                (identifier,),
            )
        ]
    assert events == ["maintenance_started", "maintenance_observed_exit", "maintenance_resumed"]


@pytest.mark.parametrize(
    "kind,action", [("cleanup", "deploy"), ("release", "cleanup"), ("shell", "exec")]
)
def test_unknown_or_mismatched_maintenance_actions_never_create_records(inventory, kind, action):
    with pytest.raises(InventoryError, match="Unknown maintenance action"):
        inventory.begin_maintenance(kind, action, "a" * 64)
    assert inventory.maintenance_history() == []


@pytest.mark.parametrize(
    "hostname", ["a..example.com", "a.-example.com", "EXAMPLE.com", "127.0.0.1"]
)
def test_noncanonical_hostnames_are_rejected(inventory, hostname):
    with pytest.raises(InventoryError, match="address or port"):
        inventory.register(replace(instance("a"), hostname=hostname))
    assert inventory.list() == []


def test_instance_cannot_claim_another_service_user(inventory):
    with pytest.raises(InventoryError, match="Invalid instance key or user"):
        inventory.register(replace(instance("c"), user="epm-a"))
    assert inventory.list() == []


@pytest.mark.parametrize("changed", ["key", "release"])
def test_resume_cannot_change_original_intent(inventory, changed):
    for key in ("a", "b"):
        inventory.register(instance(key))
    identifier = inventory.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        request=MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    original = inventory.maintenance_intent(identifier)
    inventory.finish_maintenance(identifier, 1)
    arguments = {"key": "a", "release": "release-20261027-01"}
    arguments[changed] = "b" if changed == "key" else "release-20261028-01"
    with pytest.raises(InventoryError, match="original instance and release"):
        inventory.begin_maintenance(
            "release",
            "resume",
            "b" * 64,
            request=MaintenanceRequest(resume=identifier, **arguments),
        )
    assert inventory.maintenance(identifier)["state"] == "needs_reconciliation"
    assert inventory.maintenance_intent(identifier) == original
    assert (
        inventory.begin_maintenance(
            "release", "resume", "b" * 64, request=MaintenanceRequest(resume=identifier)
        )
        == identifier
    )
    assert inventory.maintenance_intent(identifier) == original


def test_targeted_reconciliation_cannot_accept_another_allocation(inventory):
    first, second = instance("a"), instance("b")
    inventory.register(first)
    inventory.register(second)
    identifier = inventory.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        request=MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    inventory.finish_maintenance(identifier, 0)
    with pytest.raises(InventoryError, match="outside the maintenance target"):
        inventory.reconcile(
            identifier,
            [
                (first, replace(first, release="release-20261027-01", revision=2)),
                (second, replace(second, release="release-20261027-01", revision=2)),
            ],
            "b" * 64,
        )
    assert inventory.list() == [first, second]
    assert inventory.maintenance(identifier)["state"] == "needs_reconciliation"
    inventory.reconcile(
        identifier, [(first, replace(first, release="release-20261027-01", revision=2))], "b" * 64
    )
    assert inventory.get("b") == second


def test_saved_intent_is_immutable_and_source_revisions_must_match(inventory):
    item = instance("a")
    inventory.register(item)
    identifier = inventory.begin_maintenance(
        "release",
        "deploy",
        "a" * 64,
        request=MaintenanceRequest(key="a", release="release-20261027-01"),
    )
    intent = inventory.maintenance_intent(identifier)
    assert intent["sources"]["a"]["allocation_id"] == item.allocation_id
    assert intent["sources"]["a"]["revision"] == item.revision
    assert identifier.replace("-", "") in intent["checkpoint"]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with inventory.connection(writable=True) as connection:
            connection.execute(
                "UPDATE maintenance SET intent_json = '{}' WHERE id = ?", (identifier,)
            )
    inventory.finish_maintenance(identifier, 1)
    with inventory.connection(writable=True) as connection:
        connection.execute("UPDATE instances SET revision = revision + 1")
    with pytest.raises(InventoryError, match="source revisions changed"):
        inventory.begin_maintenance(
            "release", "resume", "b" * 64, request=MaintenanceRequest(resume=identifier)
        )
    with pytest.raises(InventoryError, match="source revisions changed"):
        inventory.reconcile(identifier, [], "b" * 64)


@pytest.mark.parametrize(
    "kind,action,selection",
    [
        ("release", "deploy", MaintenanceRequest()),
        ("release", "install", MaintenanceRequest(release="release-20261027-01")),
        ("cleanup", "cleanup", MaintenanceRequest()),
    ],
)
def test_unbound_mutating_operations_fail_before_creating_a_journal(
    inventory, kind, action, selection
):
    with pytest.raises(InventoryError, match="before maintenance"):
        inventory.begin_maintenance(kind, action, "a" * 64, selection)
    assert inventory.maintenance_history() == []


@pytest.mark.parametrize("kind,action", [("release", "install"), ("cleanup", "cleanup")])
def test_host_wide_release_work_cannot_reconcile_instance_changes(inventory, kind, action):
    item = instance("a")
    inventory.register(item)
    identifier = inventory.begin_maintenance(
        kind,
        action,
        "a" * 64,
        MaintenanceRequest(key="a" if action == "install" else None, release="release-20261027-01"),
    )
    assert inventory.maintenance_intent(identifier)["scope"] == "host"
    inventory.finish_maintenance(identifier, 0)
    with pytest.raises(InventoryError, match="outside the maintenance target"):
        inventory.reconcile(identifier, [(item, replace(item, revision=2))], "b" * 64)
    assert inventory.get("a") == item
