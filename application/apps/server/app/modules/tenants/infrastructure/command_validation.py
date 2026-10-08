"""Exact Tenant command schema and retained, correlated revision history."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text

from app.modules.parties.application.identity_commands import canonical, fingerprint
from app.modules.tenants.application.commands import TenantCommand, receipt_audit
from app.modules.tenants.application.errors import TenantError
from app.modules.tenants.application.service import TenantCreateCommand, TenantProfilePatchCommand
from app.modules.parties.application.service import ContactMethodCommand
from dataclasses import asdict
from app.modules.tenants.domain.models import TenantProfile
from app.modules.tenants.infrastructure.sqlalchemy_models import (
    TENANT_COMMAND_TRIGGERS,
    TenantCommandOperationModel,
    TenantProfileModel,
)
from app.platform.migration_errors import MigrationSchemaError


def _sql(value):
    return "".join(str(value).lower().split())


def _uuid(value):
    if str(UUID(value)) != value:
        raise ValueError("Noncanonical UUID.")


def _utc(value):
    instant = datetime.fromisoformat(value)
    if (
        instant.tzinfo is None
        or instant.utcoffset() != UTC.utcoffset(instant)
        or instant.isoformat() != value
    ):
        raise ValueError("Noncanonical UTC timestamp.")
    return instant


def validate_commands(connection):
    try:
        _schema(connection)
        _data(connection)
    except (ValueError, KeyError, TypeError, TenantError) as error:
        raise MigrationSchemaError("Tenant command history is incompatible.") from error


def _schema(connection):
    inspector, table = inspect(connection), TenantCommandOperationModel.__table__
    columns = inspector.get_columns(table.name)
    if {c["name"] for c in columns} != set(table.c.keys()) or any(
        str(c["type"]) != str(table.c[c["name"]].type)
        or (not c["primary_key"] and c["nullable"] != table.c[c["name"]].nullable)
        for c in columns
    ):
        raise ValueError("Receipt columns differ.")
    if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
        raise ValueError("Receipt primary key differs.")
    if {_sql(c["sqltext"]) for c in inspector.get_check_constraints(table.name)} != {
        _sql(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    }:
        raise ValueError("Receipt checks differ.")
    if {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)} != {
        tuple(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }:
        raise ValueError("Receipt uniqueness differs.")
    if {
        (i["name"], tuple(i["column_names"]), bool(i["unique"]))
        for i in inspector.get_indexes(table.name)
    } != {(i.name, tuple(c.name for c in i.columns), bool(i.unique)) for i in table.indexes}:
        raise ValueError("Receipt indexes differ.")
    if {
        (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
        for f in inspector.get_foreign_keys(table.name)
    } != {
        ((fk.parent.name,), fk.column.table.name, (fk.column.name,)) for fk in table.foreign_keys
    }:
        raise ValueError("Receipt references differ.")
    triggers = dict(
        connection.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='tenant_command_operations'"
            )
        ).all()
    )
    if {name: _sql(sql) for name, sql in triggers.items()} != {
        name: _sql(sql) for name, sql in TENANT_COMMAND_TRIGGERS.items()
    }:
        raise ValueError("Receipt immutability differs.")


def _data(connection):
    profiles = {
        r["party_id"]: TenantProfile(**{**r, "do_not_contact": bool(r["do_not_contact"])})
        for r in connection.execute(TenantProfileModel.__table__.select()).mappings()
    }
    operations = (
        connection.execute(TenantCommandOperationModel.__table__.select().order_by(text("rowid")))
        .mappings()
        .all()
    )
    audits = connection.execute(text("SELECT * FROM audit_events ORDER BY rowid")).mappings().all()
    tips = {}
    for row in operations:
        for field in ("id", "party_id", "idempotency_key", "correlation_id"):
            _uuid(row[field])
        now = _utc(row["created_at"])
        request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
        if (
            set(request) != {"action", "partyId", "expectedRevision", "payload"}
            or canonical(request) != row["request_json"]
            or fingerprint(request) != row["request_fingerprint"]
            or canonical(result) != row["result_json"]
        ):
            raise ValueError("Receipt payload differs.")
        command = TenantCommand(
            request["action"],
            request["partyId"],
            request["expectedRevision"],
            row["idempotency_key"],
            request["payload"],
        )
        if (
            command.action != row["action"]
            or command.expected_revision != row["expected_revision"]
            or command.party_id != (None if command.action == "create" else row["party_id"])
        ):
            raise ValueError("Receipt identity differs.")
        previous = tips.get(row["party_id"])
        if command.expected_revision != (previous["revision"] if previous else 0):
            raise ValueError("Revision lineage differs.")
        if (
            result["operationId"] != row["id"]
            or result["revision"] != row["resulting_revision"]
            or type(result["revision"]) is not int
        ):
            raise ValueError("Receipt result differs.")
        state = result if command.action == "resolve_contact" else result["profile"]
        if (
            set(state) - {"operationId"}
            != {
                "partyId",
                "preferredContactMethodId",
                "doNotContact",
                "notes",
                "createdAt",
                "updatedAt",
                "archivedAt",
                "revision",
            }
            or state["partyId"] != row["party_id"]
            or state["revision"] != result["revision"]
            or type(state["revision"]) is not int
            or type(state["doNotContact"]) is not bool
        ):
            raise ValueError("Profile snapshot differs.")
        _uuid(state["partyId"])
        if state["preferredContactMethodId"] is not None:
            _uuid(state["preferredContactMethodId"])
        if state["notes"] is not None and (
            not isinstance(state["notes"], str)
            or not state["notes"].strip()
            or state["notes"] != state["notes"].strip()
            or len(state["notes"]) > 4000
        ):
            raise ValueError("Notes differ.")
        if _utc(state["createdAt"]) > _utc(state["updatedAt"]) or _utc(state["updatedAt"]) > now:
            raise ValueError("Profile timestamps differ.")
        if state["archivedAt"] is not None:
            _utc(state["archivedAt"])
        events = [
            a
            for a in audits
            if a["entity_type"] == "tenant_command_operation" and a["entity_id"] == row["id"]
        ]
        if (
            len(events) != 1
            or events[0]["action"] != "recorded"
            or events[0]["correlation_id"] != row["correlation_id"]
            or json.loads(events[0]["after_snapshot"]) != receipt_audit(row)
        ):
            raise ValueError("Correlated receipt audit differs.")
        profile_state = {k: v for k, v in state.items() if k != "operationId"}
        _transition(command, result, profile_state, previous, row["created_at"])
        changed = previous != profile_state
        history = [
            a
            for a in audits
            if a["entity_type"] == "tenant_profile"
            and a["entity_id"] == row["party_id"]
            and a["correlation_id"] == row["correlation_id"]
        ]
        if changed:
            action = (
                "created"
                if command.action in {"create", "designate"}
                else "status_changed"
                if command.action in {"archive", "restore"}
                else "updated"
            )
            if (
                len(history) != 1
                or history[0]["action"] != action
                or json.loads(history[0]["after_snapshot"]) != profile_state
                or (
                    json.loads(history[0]["before_snapshot"])
                    if history[0]["before_snapshot"]
                    else None
                )
                != previous
            ):
                raise ValueError("Profile transition audit differs.")
            if row["resulting_revision"] != row["expected_revision"] + 1:
                raise ValueError("Effective mutation revision differs.")
            if command.action == "create":
                _creation_audits(row, result, audits)
        elif (
            history
            or command.action != "patch"
            or row["resulting_revision"] != row["expected_revision"]
        ):
            raise ValueError("No-op receipt differs.")
        tips[row["party_id"]] = profile_state
    if set(profiles) != set(tips) or any(
        profile.to_dict() != tips[party_id] for party_id, profile in profiles.items()
    ):
        raise ValueError("Current Tenant differs from its receipt history.")
    allowed = {(row["party_id"], row["correlation_id"]) for row in operations}
    if any(
        a["entity_type"] == "tenant_profile"
        and (a["entity_id"], a["correlation_id"]) not in allowed
        for a in audits
    ):
        raise ValueError("Tenant profile audit lacks its command receipt.")


def _creation_audits(row, result, audits):
    events = [a for a in audits if a["correlation_id"] == row["correlation_id"]]
    parties = [
        a for a in events if a["entity_type"] == "party" and a["entity_id"] == row["party_id"]
    ]
    identity = {
        k: result[k]
        for k in ("id", "partyKind", "displayName", "createdAt", "updatedAt", "archivedAt")
    }
    identity["revision"] = result["partyRevision"]
    if (
        len(parties) != 1
        or parties[0]["action"] != "created"
        or parties[0]["before_snapshot"] is not None
        or json.loads(parties[0]["after_snapshot"]) != identity
    ):
        raise ValueError("Tenant creation lacks correlated Party evidence.")
    contact_events = [a for a in events if a["entity_type"] == "party_contact_method"]
    if len(contact_events) != len(result["contactMethods"]):
        raise ValueError("Initial contact audit count differs.")
    for contact in result["contactMethods"]:
        matching = [a for a in contact_events if a["entity_id"] == contact["id"]]
        normalized = ContactMethodCommand(
            contact["methodKind"], contact["displayValue"], contact["extension"], contact["label"]
        )
        if (
            len(matching) != 1
            or matching[0]["action"] != "created"
            or matching[0]["before_snapshot"] is not None
            or json.loads(matching[0]["after_snapshot"])
            != {**contact, "normalizedValue": normalized.normalized_value}
        ):
            raise ValueError("Initial contact evidence differs.")


def _transition(command, result, state, previous, now):
    payload = command.payload
    if command.action == "create":
        fields = dict(payload)
        fields["contacts"] = tuple(
            ContactMethodCommand(**{k: v for k, v in item.items() if k != "normalized_value"})
            for item in fields["contacts"]
        )
        normalized = asdict(TenantCreateCommand(**fields))
        # JSON canonicalization turns the command's immutable contact tuple into an array.
        if canonical(normalized) != canonical(payload):
            raise ValueError("Creation command is not normalized.")
        expected = {
            "partyId": state["partyId"],
            "preferredContactMethodId": None,
            "notes": payload["notes"],
            "doNotContact": payload["do_not_contact"],
            "createdAt": now,
            "updatedAt": now,
            "archivedAt": None,
            "revision": 1,
        }
        if (
            result["displayName"] != payload["display_name"]
            or result["partyKind"] != payload["party_kind"]
            or result["partyRevision"] != 1
        ):
            raise ValueError("Creation identity differs.")
        contacts = result["contactMethods"]
        if len(contacts) != len(payload["contacts"]) or any(
            c["displayValue"] != request["value"]
            or c["methodKind"] != request["method_kind"]
            or c["extension"] != request["extension"]
            or c["label"] != request["label"]
            or c["partyId"] != state["partyId"]
            or c["status"] != "active"
            or c["archivedAt"] is not None
            or c["createdAt"] != now
            or c["updatedAt"] != now
            for c, request in zip(contacts, payload["contacts"], strict=True)
        ):
            raise ValueError("Initial contacts differ.")
    elif command.action == "designate":
        if set(payload) != {"notes"}:
            raise ValueError("Designation command differs.")
        expected = {
            "partyId": state["partyId"],
            "preferredContactMethodId": None,
            "notes": payload["notes"],
            "doNotContact": False,
            "createdAt": now,
            "updatedAt": now,
            "archivedAt": None,
            "revision": 1,
        }
    else:
        if previous is None:
            raise ValueError("Missing initial receipt.")
        expected = dict(previous)
        if command.action in {"patch", "resolve_contact"}:
            if (
                not set(payload) <= {"notes", "do_not_contact", "preferred_contact_method_id"}
                or not payload
            ):
                raise ValueError("Profile command fields differ.")
            TenantProfilePatchCommand(**payload)
            if previous["archivedAt"] is not None:
                raise ValueError("Archived Tenant was edited.")
            names = {
                "notes": "notes",
                "do_not_contact": "doNotContact",
                "preferred_contact_method_id": "preferredContactMethodId",
            }
            expected.update({names[k]: v for k, v in payload.items()})
            if command.action == "resolve_contact" and set(payload) != {
                "preferred_contact_method_id"
            }:
                raise ValueError("Resolution fields differ.")
        elif command.action == "archive":
            if payload != {"confirmed": True} or previous["archivedAt"] is not None:
                raise ValueError("Archival command differs.")
            expected["archivedAt"] = now
        else:
            if payload or previous["archivedAt"] is None:
                raise ValueError("Restore command differs.")
            expected["archivedAt"] = None
        if expected != previous:
            expected.update(updatedAt=now, revision=previous["revision"] + 1)
    if state != expected:
        raise ValueError("Profile does not match the requested transition.")
    if command.action != "resolve_contact":
        if (
            set(result)
            != {
                "id",
                "partyKind",
                "displayName",
                "createdAt",
                "updatedAt",
                "archivedAt",
                "revision",
                "partyRevision",
                "profile",
                "contactMethods",
                "operationId",
            }
            or result["id"] != state["partyId"]
            or type(result["partyRevision"]) is not int
            or result["partyRevision"] < 1
        ):
            raise ValueError("Tenant result fields differ.")
        for field in ("createdAt", "updatedAt"):
            _utc(result[field])
        if result["archivedAt"] is not None:
            _utc(result["archivedAt"])
        for contact in result["contactMethods"]:
            _uuid(contact["id"])
            _uuid(contact["partyId"])
