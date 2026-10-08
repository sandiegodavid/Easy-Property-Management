"""Exact Party receipt schema and portable, correlated command history."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select, text

from app.modules.parties.application.identity_commands import (
    PartyCommandIdentity,
    canonical,
    fingerprint,
)
from app.modules.parties.domain.models import Party, PartyContactMethod
from app.modules.parties.application.command_execution import receipt_audit
from app.modules.parties.application.service import (
    PartyCreateCommand,
    PartyPatchCommand,
    ContactMethodCommand,
    ContactReferenceResolution,
)
from app.modules.parties.infrastructure.sqlalchemy_models import (
    PartyCommandOperationModel,
    PartyModel,
    PartyContactMethodModel,
    PARTY_COMMAND_TRIGGERS,
)
from app.platform.migration_errors import MigrationSchemaError


def normalized(value):
    return "".join(str(value).lower().split())


def validate_party_schema(connection):
    inspector = inspect(connection)
    table = PartyCommandOperationModel.__table__
    try:
        columns = inspector.get_columns(table.name)
        if {c["name"] for c in columns} != set(table.c.keys()) or any(
            str(c["type"]) != str(table.c[c["name"]].type)
            or (not c["primary_key"] and c["nullable"] != table.c[c["name"]].nullable)
            for c in columns
        ):
            raise ValueError("Receipt columns are incompatible.")
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            raise ValueError("Receipt primary key is incompatible.")
        if {normalized(c["sqltext"]) for c in inspector.get_check_constraints(table.name)} != {
            normalized(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
        }:
            raise ValueError("Receipt checks are incompatible.")
        if {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)} != {
            tuple(col.name for col in c.columns)
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        }:
            raise ValueError("Receipt uniqueness is incompatible.")
        if {
            (i["name"], tuple(i["column_names"]), bool(i["unique"]))
            for i in inspector.get_indexes(table.name)
        } != {(i.name, tuple(c.name for c in i.columns), bool(i.unique)) for i in table.indexes}:
            raise ValueError("Receipt indexes are incompatible.")
        if {
            (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
            for f in inspector.get_foreign_keys(table.name)
        } != {
            ((fk.parent.name,), fk.column.table.name, (fk.column.name,))
            for fk in table.foreign_keys
        }:
            raise ValueError("Receipt references are incompatible.")
        triggers = dict(
            connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='party_command_operations'"
                )
            ).all()
        )
        if {name: normalized(sql) for name, sql in triggers.items()} != {
            name: normalized(sql) for name, sql in PARTY_COMMAND_TRIGGERS.items()
        }:
            raise ValueError("Receipt history must be immutable.")
        validate_party_data(connection)
    except (ValueError, KeyError, TypeError) as error:
        raise MigrationSchemaError("Party command history is incompatible.") from error


def _uuid(value):
    if str(UUID(value)) != value:
        raise ValueError("Identity is not a canonical UUID.")


def _utc(value):
    instant = datetime.fromisoformat(value)
    if (
        instant.tzinfo is None
        or instant.utcoffset() != UTC.utcoffset(instant)
        or instant.isoformat() != value
    ):
        raise ValueError("Timestamp is not canonical UTC.")
    return instant


def validate_party_data(connection):
    parties = {
        row["id"]: Party(**row)
        for row in connection.execute(select(PartyModel.__table__)).mappings()
    }
    contacts = {
        row["id"]: PartyContactMethod(**row)
        for row in connection.execute(select(PartyContactMethodModel.__table__)).mappings()
    }
    operations = (
        connection.execute(select(PartyCommandOperationModel.__table__).order_by(text("rowid")))
        .mappings()
        .all()
    )
    audits = connection.execute(text("SELECT * FROM audit_events ORDER BY rowid")).mappings().all()
    revisions = {}
    contact_results = {}
    for row in operations:
        for key in ("id", "party_id", "idempotency_key", "correlation_id"):
            _uuid(row[key])
        created = _utc(row["created_at"])
        request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
        if (
            canonical(request) != row["request_json"]
            or fingerprint(request) != row["request_fingerprint"]
        ):
            raise ValueError("Receipt fingerprint differs.")
        if set(request) != {"action", "partyId", "expectedRevision", "payload"}:
            raise ValueError("Receipt command shape differs.")
        identity = PartyCommandIdentity(
            request["action"],
            request["partyId"],
            request["expectedRevision"],
            row["idempotency_key"],
            request["payload"],
        )
        _payload(identity)
        if (
            identity.action != row["action"]
            or identity.expected_revision != row["expected_revision"]
            or identity.party_id != (None if row["action"] == "create" else row["party_id"])
        ):
            raise ValueError("Receipt command identity differs.")
        contact_command = row["action"].startswith("contact_")
        if contact_command:
            _contact_result(row, identity, result, contacts)
        else:
            if row["contact_method_id"] is not None:
                raise ValueError("Identity command has a contact result.")
            expected_fields = set(parties[row["party_id"]].identity_snapshot()) | {"operationId"}
            if (
                set(result) != expected_fields
                or result["id"] != row["party_id"]
                or result["partyKind"] not in {"individual", "organization"}
                or not isinstance(result["displayName"], str)
                or not 1 <= len(result["displayName"]) <= 240
                or result["displayName"] != result["displayName"].strip()
            ):
                raise ValueError("Identity receipt result shape differs.")
        if (
            canonical(result) != row["result_json"]
            or result["operationId"] != row["id"]
            or type(result["revision"]) is not int
            or result["revision"] != row["resulting_revision"]
        ):
            raise ValueError("Receipt result differs.")
        if (
            _utc(result["createdAt"]) > _utc(result["updatedAt"])
            or _utc(result["updatedAt"]) > created
        ):
            raise ValueError("Receipt timestamp order is invalid.")
        if result["archivedAt"] is not None:
            _utc(result["archivedAt"])
        previous = revisions.get(row["party_id"], 0 if row["action"] == "create" else 1)
        if previous != row["expected_revision"]:
            raise ValueError("Receipt revision history is discontinuous.")
        revisions[row["party_id"]] = row["resulting_revision"]
        events = [
            a
            for a in audits
            if a["entity_type"] == "party_command_operation" and a["entity_id"] == row["id"]
        ]
        expected_audit = receipt_audit(row)
        if (
            len(events) != 1
            or events[0]["action"] != "recorded"
            or events[0]["correlation_id"] != row["correlation_id"]
            or json.loads(events[0]["after_snapshot"]) != expected_audit
        ):
            raise ValueError("Receipt audit evidence differs.")
        if contact_command:
            _contact_audits(row, identity, result, audits)
            contact_results[row["contact_method_id"]] = {
                key: value
                for key, value in result.items()
                if key not in {"revision", "operationId"}
            }
        else:
            _identity_audits(row, identity, result, audits)
    for party_id, revision in revisions.items():
        if parties[party_id].revision != revision:
            raise ValueError("Party revision differs from command history.")
    for contact_id, result in contact_results.items():
        current = contacts[contact_id]
        command = ContactMethodCommand(
            current.method_kind, current.display_value, current.extension, current.label
        )
        if current.to_dict() != result or current.normalized_value != command.normalized_value:
            raise ValueError("Current contact differs from its command history.")
    operation_ids = {row["id"] for row in operations}
    if any(
        a["entity_type"] == "party_command_operation" and a["entity_id"] not in operation_ids
        for a in audits
    ):
        raise ValueError("Receipt audit has no retained operation.")


def _payload(identity):
    payload = identity.payload
    if not isinstance(payload, dict):
        raise ValueError("Party command payload is invalid.")
    if identity.action.startswith("contact_"):
        _contact_payload(identity)
    elif identity.action == "create":
        if (
            set(payload) != {"command", "contacts", "confirmedNewParty"}
            or type(payload["confirmedNewParty"]) is not bool
        ):
            raise ValueError("Party creation payload is invalid.")
        command = PartyCreateCommand(**payload["command"])
        if {"party_kind": command.party_kind, "display_name": command.display_name} != payload[
            "command"
        ] or not isinstance(payload["contacts"], list):
            raise ValueError("Party creation payload is not normalized.")
        for contact in payload["contacts"]:
            normalized_contact = ContactMethodCommand(
                **{key: value for key, value in contact.items() if key != "normalized_value"}
            )
            if asdict(normalized_contact) != contact:
                raise ValueError("Party contact payload is not normalized.")
    elif identity.action == "patch":
        if (
            set(payload) != {"display_name"}
            or PartyPatchCommand(**payload).display_name != payload["display_name"]
        ):
            raise ValueError("Party patch payload is invalid.")
    elif identity.action == "archive":
        if payload != {"confirmed": True} or type(payload.get("confirmed")) is not bool:
            raise ValueError("Party archive confirmation is invalid.")
    elif identity.action != "restore" or payload:
        raise ValueError("Party lifecycle payload is invalid.")


def _identity_audits(row, identity, result, audits):
    events = [
        a
        for a in audits
        if a["entity_type"] == "party"
        and a["entity_id"] == row["party_id"]
        and a["correlation_id"] == row["correlation_id"]
    ]
    if row["resulting_revision"] == row["expected_revision"]:
        if events:
            raise ValueError("Unchanged command has a Party mutation event.")
        return
    action = {
        "create": "created",
        "patch": "updated",
        "archive": "archived",
        "restore": "restored",
    }[row["action"]]
    after = {key: value for key, value in result.items() if key != "operationId"}
    if (
        len(events) != 1
        or events[0]["action"] != action
        or json.loads(events[0]["after_snapshot"]) != after
    ):
        raise ValueError("Party mutation audit evidence differs.")
    before = json.loads(events[0]["before_snapshot"]) if events[0]["before_snapshot"] else None
    if row["action"] == "create":
        if before is not None or result["archivedAt"] is not None:
            raise ValueError("Party creation history differs.")
    elif (
        not isinstance(before, dict)
        or before.get("revision") != row["expected_revision"]
        or before.get("id") != row["party_id"]
    ):
        raise ValueError("Party mutation before-state differs.")
    elif row["action"] == "archive" and (
        before["archivedAt"] is not None or result["archivedAt"] != row["created_at"]
    ):
        raise ValueError("Party archive history differs.")
    elif row["action"] == "restore" and (
        before["archivedAt"] is None or result["archivedAt"] is not None
    ):
        raise ValueError("Party restore history differs.")
    elif row["action"] == "patch" and (
        before["archivedAt"] is not None
        or result["archivedAt"] is not None
        or result["displayName"] != identity.payload["display_name"]
    ):
        raise ValueError("Party patch history differs.")


def _contact_payload(identity):
    payload = identity.payload
    fields = {
        "contact_add": {"command"},
        "contact_update": {"command", "methodId"},
        "contact_archive": {"methodId", "confirmed", "referenceResolutions"},
        "contact_restore": {"methodId"},
    }[identity.action]
    if set(payload) != fields:
        raise ValueError("Contact command payload is invalid.")
    if "methodId" in payload:
        _uuid(payload["methodId"])
    if "command" in payload:
        command = ContactMethodCommand(
            **{key: value for key, value in payload["command"].items() if key != "normalized_value"}
        )
        if asdict(command) != payload["command"]:
            raise ValueError("Contact command is not normalized.")
    if identity.action == "contact_archive":
        if (
            payload["confirmed"] is not True
            or not isinstance(payload["referenceResolutions"], list)
            or len(payload["referenceResolutions"]) > 20
        ):
            raise ValueError("Contact archival is invalid.")
        resolutions = [
            ContactReferenceResolution(**item) for item in payload["referenceResolutions"]
        ]
        keys = [(item.role, item.role_record_id) for item in resolutions]
        if keys != sorted(set(keys)):
            raise ValueError("Contact reference resolutions are not canonical.")
        for item in resolutions:
            _uuid(item.role_record_id)
            if item.replacement_contact_method_id:
                _uuid(item.replacement_contact_method_id)


def _contact_result(row, identity, result, contacts):
    _uuid(row["contact_method_id"])
    contact = contacts[row["contact_method_id"]]
    if (
        contact.party_id != row["party_id"]
        or set(result) != set(contact.to_dict()) | {"revision", "operationId"}
        or result["id"] != contact.id
        or result["partyId"] != row["party_id"]
    ):
        raise ValueError("Contact receipt ownership or shape differs.")
    if identity.action != "contact_add" and identity.payload["methodId"] != contact.id:
        raise ValueError("Contact command targets another method.")
    command = ContactMethodCommand(
        result["methodKind"], result["displayValue"], result["extension"], result["label"]
    )
    if (
        command.value != result["displayValue"]
        or command.extension != result["extension"]
        or command.label != result["label"]
    ):
        raise ValueError("Contact result is not normalized.")
    if result["status"] not in {"active", "archived"} or (result["status"] == "archived") != (
        result["archivedAt"] is not None
    ):
        raise ValueError("Contact result lifecycle is invalid.")
    if (
        identity.action in {"contact_add", "contact_update"}
        and asdict(command) != identity.payload["command"]
    ):
        raise ValueError("Contact result differs from its command.")


def _contact_audits(row, identity, result, audits):
    events = [a for a in audits if a["correlation_id"] == row["correlation_id"]]
    party_events = [
        a for a in events if a["entity_type"] == "party" and a["entity_id"] == row["party_id"]
    ]
    contact_events = [
        a
        for a in events
        if a["entity_type"] == "party_contact_method" and a["entity_id"] == row["contact_method_id"]
    ]
    if row["resulting_revision"] == row["expected_revision"]:
        if party_events or contact_events:
            raise ValueError("Unchanged contact command has mutation events.")
        return
    if len(party_events) != 1 or party_events[0]["action"] != "contact_changed":
        raise ValueError("Contact command lacks its shared revision event.")
    party_before = json.loads(party_events[0]["before_snapshot"])
    party_after = json.loads(party_events[0]["after_snapshot"])
    if party_before["revision"] != row["expected_revision"] or party_after != {
        **party_before,
        "revision": row["resulting_revision"],
        "updatedAt": row["created_at"],
    }:
        raise ValueError("Contact command changed unexpected Party fields.")
    action = {
        "contact_add": "created",
        "contact_update": "updated",
        "contact_archive": "archived",
        "contact_restore": "restored",
    }[identity.action]
    command = ContactMethodCommand(
        result["methodKind"], result["displayValue"], result["extension"], result["label"]
    )
    after = {key: value for key, value in result.items() if key not in {"revision", "operationId"}}
    after["normalizedValue"] = command.normalized_value
    if (
        len(contact_events) != 1
        or contact_events[0]["action"] != action
        or json.loads(contact_events[0]["after_snapshot"]) != after
    ):
        raise ValueError("Contact mutation audit evidence differs.")
    before = (
        json.loads(contact_events[0]["before_snapshot"])
        if contact_events[0]["before_snapshot"]
        else None
    )
    if action == "created":
        if before is not None or after["status"] != "active":
            raise ValueError("Contact creation history differs.")
    elif (
        not isinstance(before, dict)
        or before["id"] != after["id"]
        or before["partyId"] != after["partyId"]
        or before["createdAt"] != after["createdAt"]
    ):
        raise ValueError("Contact mutation before-state differs.")
    elif action == "archived" and (
        before["status"] != "active"
        or after
        != {
            **before,
            "status": "archived",
            "archivedAt": row["created_at"],
            "updatedAt": row["created_at"],
        }
    ):
        raise ValueError("Contact archival history differs.")
    elif action == "restored" and (
        before["status"] != "archived"
        or after
        != {**before, "status": "active", "archivedAt": None, "updatedAt": row["created_at"]}
    ):
        raise ValueError("Contact restore history differs.")
    elif action == "updated" and (before["status"] != "active" or after["status"] != "active"):
        raise ValueError("Contact edit history differs.")
    if identity.action == "contact_archive":
        for resolution in identity.payload["referenceResolutions"]:
            matching = [
                a
                for a in events
                if a["entity_id"] == resolution["role_record_id"]
                and a["action"] == "updated"
                and a["reason"] == "preferred_contact_updated"
            ]
            if len(matching) != 1:
                raise ValueError("Contact resolution lacks correlated owner evidence.")
            prior = json.loads(matching[0]["before_snapshot"])
            revised = json.loads(matching[0]["after_snapshot"])
            if (
                prior["preferredContactMethodId"] != row["contact_method_id"]
                or revised["preferredContactMethodId"]
                != resolution["replacement_contact_method_id"]
            ):
                raise ValueError("Contact reference resolution audit differs.")
            if resolution["role"] == "tenant" and (
                prior["revision"] != resolution["expected_tenant_revision"]
                or revised["revision"] != prior["revision"] + 1
            ):
                raise ValueError("Tenant resolution concurrency evidence differs.")
