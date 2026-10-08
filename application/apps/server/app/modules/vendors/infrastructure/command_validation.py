"""Exact Provider command schema and retained profile revision history."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text

from app.modules.parties.application.service import PartyCreateCommand, ContactMethodCommand
from app.modules.vendors.application.commands import (
    ProviderCommand,
    canonical,
    fingerprint,
    receipt_audit,
    CHILD_ACTIONS,
    ASSIGNMENT_ACTIONS,
)
from app.modules.vendors.application.errors import ProviderError
from app.modules.vendors.application.service import (
    ProviderProfileCommand,
    ProviderProfilePatchCommand,
    ServiceCommand,
    ServiceAreaCommand,
    WorkHistoryCommand,
    ReferenceCommand,
)
from app.modules.vendors.domain.models import ProviderProfile
from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderCommandOperationModel,
    ProviderProfileModel,
    PROVIDER_COMMAND_TRIGGERS,
    ProviderCategoryCommandOperationModel,
    CATEGORY_COMMAND_TRIGGERS,
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
        _schema(
            connection, ProviderCategoryCommandOperationModel.__table__, CATEGORY_COMMAND_TRIGGERS
        )
        _data(connection)
    except (ValueError, KeyError, TypeError, ProviderError) as error:
        raise MigrationSchemaError("Provider command history is incompatible.") from error


def _schema(
    connection,
    table=ProviderCommandOperationModel.__table__,
    expected_triggers=PROVIDER_COMMAND_TRIGGERS,
):
    inspector = inspect(connection)
    if not inspector.has_table(table.name):
        raise ValueError("Receipt table is missing.")
    profile_columns = {c["name"]: c for c in inspector.get_columns("provider_profiles")}
    if str(profile_columns["revision"]["default"]).strip("'") != "1":
        raise ValueError("Initial Provider revision differs.")
    category_columns = {c["name"]: c for c in inspector.get_columns("provider_categories")}
    if str(category_columns["revision"]["default"]).strip("'") != "1":
        raise ValueError("Initial category revision differs.")
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
            text("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=:table"),
            {"table": table.name},
        ).all()
    )
    if {name: _sql(sql) for name, sql in triggers.items()} != {
        name: _sql(sql) for name, sql in expected_triggers.items()
    }:
        raise ValueError("Receipt immutability differs.")


def _data(connection):
    profiles = {
        r["party_id"]: ProviderProfile(**r)
        for r in connection.execute(ProviderProfileModel.__table__.select()).mappings()
    }
    operations = (
        connection.execute(ProviderCommandOperationModel.__table__.select().order_by(text("rowid")))
        .mappings()
        .all()
    )
    audits = connection.execute(text("SELECT * FROM audit_events ORDER BY rowid")).mappings().all()
    tips = {}
    from app.modules.vendors.infrastructure.child_command_validation import ChildHistory

    children = ChildHistory(connection, audits)
    from app.modules.vendors.infrastructure.category_command_validation import (
        CategoryHistory,
        AssignmentHistory,
    )

    categories = CategoryHistory(connection, audits)
    categories.validate()
    assignments = AssignmentHistory(connection, audits, categories)
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
        command = ProviderCommand(
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
        assignment_command = command.action in ASSIGNMENT_ACTIONS
        child_command = command.action in CHILD_ACTIONS or assignment_command
        if (
            set(result)
            != (
                {"kind", "item", "category", "profile", "revision", "operationId"}
                if assignment_command
                else (
                    {"kind", "item", "profile", "revision", "operationId"}
                    if child_command
                    else {"party", "profile", "revision", "partyRevision", "operationId"}
                )
            )
            or result["operationId"] != row["id"]
            or type(result["revision"]) is not int
            or result["revision"] != row["resulting_revision"]
            or (
                not child_command
                and (type(result["partyRevision"]) is not int or result["partyRevision"] < 1)
            )
        ):
            raise ValueError("Receipt result differs.")
        state = result["profile"]
        if (
            set(state)
            != {
                "partyId",
                "selectionStatus",
                "selectionReason",
                "notes",
                "createdAt",
                "updatedAt",
                "archivedAt",
                "revision",
            }
            or state["partyId"] != row["party_id"]
            or type(state["revision"]) is not int
            or state["revision"] != result["revision"]
        ):
            raise ValueError("Profile snapshot differs.")
        normalized = ProviderProfileCommand(
            state["selectionStatus"], state["selectionReason"], state["notes"]
        )
        if asdict(normalized) != {
            "selection_status": state["selectionStatus"],
            "selection_reason": state["selectionReason"],
            "notes": state["notes"],
        }:
            raise ValueError("Profile is not normalized.")
        if _utc(state["createdAt"]) > _utc(state["updatedAt"]) or _utc(state["updatedAt"]) > now:
            raise ValueError("Profile timestamps differ.")
        if state["archivedAt"] is not None:
            _utc(state["archivedAt"])
        if child_command:
            changed = (
                assignments.validate(command, row, result, previous)
                if assignment_command
                else children.validate(command, row, result, previous)
            )
            expected = dict(previous)
            if changed:
                expected.update(updatedAt=row["created_at"], revision=previous["revision"] + 1)
            if state != expected:
                raise ValueError("Child command profile transition differs.")
        else:
            _identity(result["party"], row, now)
            _transition(command, state, previous, row["created_at"])
        events = [
            a
            for a in audits
            if a["entity_type"] == "provider_command_operation" and a["entity_id"] == row["id"]
        ]
        _receipt_event(events, row)
        history = [
            a
            for a in audits
            if a["entity_type"] == "provider_profile"
            and a["entity_id"] == row["party_id"]
            and a["correlation_id"] == row["correlation_id"]
        ]
        _profile_event(history, command, row, state, previous, child_command)
        if command.action == "create":
            _creation_audits(command, row, result, audits)
            children.initial(row)
            assignments.initial(row)
        tips[row["party_id"]] = state
    children.finish()
    assignments.finish()
    if set(profiles) != set(tips) or any(p.to_dict() != tips[key] for key, p in profiles.items()):
        raise ValueError("Current Provider differs from its receipt history.")
    allowed = {(row["party_id"], row["correlation_id"]) for row in operations}
    if any(
        a["entity_type"] == "provider_profile"
        and (a["entity_id"], a["correlation_id"]) not in allowed
        for a in audits
    ):
        raise ValueError("Provider mutation lacks its receipt.")
    receipt_ids = {row["id"] for row in operations}
    if any(
        a["entity_type"] == "provider_command_operation" and a["entity_id"] not in receipt_ids
        for a in audits
    ):
        raise ValueError("Receipt audit lacks its operation.")


def _identity(party, row, now):
    if (
        set(party) != {"id", "partyKind", "displayName", "createdAt", "updatedAt", "archivedAt"}
        or party["id"] != row["party_id"]
    ):
        raise ValueError("Identity snapshot differs.")
    if asdict(PartyCreateCommand(party["partyKind"], party["displayName"])) != {
        "party_kind": party["partyKind"],
        "display_name": party["displayName"],
    }:
        raise ValueError("Identity is not normalized.")
    if _utc(party["createdAt"]) > _utc(party["updatedAt"]) or _utc(party["updatedAt"]) > now:
        raise ValueError("Identity timestamps differ.")
    if party["archivedAt"] is not None:
        _utc(party["archivedAt"])


def _receipt_event(events, row):
    if (
        len(events) != 1
        or events[0]["action"] != "recorded"
        or events[0]["correlation_id"] != row["correlation_id"]
        or json.loads(events[0]["after_snapshot"]) != receipt_audit(row)
        or events[0]["before_snapshot"] is not None
    ):
        raise ValueError("Correlated receipt audit differs.")


def _profile_event(history, command, row, state, previous, child_command):
    if state != previous:
        action = (
            "updated"
            if child_command
            else {
                "create": "created",
                "designate": "created",
                "patch": "updated",
                "archive": "archived",
                "restore": "restored",
            }[command.action]
        )
        if (
            len(history) != 1
            or history[0]["action"] != action
            or json.loads(history[0]["after_snapshot"]) != state
            or (
                json.loads(history[0]["before_snapshot"]) if history[0]["before_snapshot"] else None
            )
            != previous
            or row["resulting_revision"] != row["expected_revision"] + 1
        ):
            raise ValueError("Profile transition audit differs.")
    elif (
        history
        or (
            command.action != "patch"
            and not command.action.endswith("_update")
            and command.action not in {"assignment_archive", "assignment_restore"}
        )
        or row["resulting_revision"] != row["expected_revision"]
    ):
        raise ValueError("No-op receipt differs.")


def _transition(command, state, previous, now):
    payload = command.payload
    if command.action in {"create", "designate"}:
        fields = payload["profile"] if command.action == "create" else payload
        if asdict(ProviderProfileCommand(**fields)) != fields:
            raise ValueError("Initial profile command differs.")
        expected = {
            "partyId": state["partyId"],
            "selectionStatus": fields["selection_status"],
            "selectionReason": fields["selection_reason"],
            "notes": fields["notes"],
            "createdAt": now,
            "updatedAt": now,
            "archivedAt": None,
            "revision": 1,
        }
    else:
        if previous is None:
            raise ValueError("Missing initial receipt.")
        expected = dict(previous)
        if command.action == "patch":
            if (
                not payload
                or not set(payload) <= {"selection_status", "selection_reason", "notes"}
                or previous["archivedAt"] is not None
            ):
                raise ValueError("Patch fields or lifecycle differ.")
            normalized = ProviderProfilePatchCommand(**payload)
            if any(getattr(normalized, k) != v for k, v in payload.items()):
                raise ValueError("Patch is not normalized.")
            names = {
                "selection_status": "selectionStatus",
                "selection_reason": "selectionReason",
                "notes": "notes",
            }
            expected.update({names[k]: v for k, v in payload.items()})
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
    if expected != state:
        raise ValueError("Profile does not match its command.")


def _creation_audits(command, row, result, audits):
    payload = command.payload
    if (
        set(payload)
        != {
            "party",
            "profile",
            "contacts",
            "services",
            "areas",
            "work_history",
            "references",
            "category_ids",
            "confirmed_new_party",
        }
        or type(payload["confirmed_new_party"]) is not bool
        or payload["category_ids"] != sorted(set(payload["category_ids"]))
    ):
        raise ValueError("Creation payload differs.")
    for key in payload["category_ids"]:
        _uuid(key)
    if (
        asdict(PartyCreateCommand(**payload["party"])) != payload["party"]
        or result["party"]["partyKind"] != payload["party"]["party_kind"]
        or result["party"]["displayName"] != payload["party"]["display_name"]
        or result["partyRevision"] != 1
    ):
        raise ValueError("Creation identity differs.")
    events = [a for a in audits if a["correlation_id"] == row["correlation_id"]]
    party_events = [
        a for a in events if a["entity_type"] == "party" and a["entity_id"] == row["party_id"]
    ]
    if (
        len(party_events) != 1
        or party_events[0]["action"] != "created"
        or party_events[0]["before_snapshot"] is not None
        or json.loads(party_events[0]["after_snapshot"]) != {**result["party"], "revision": 1}
    ):
        raise ValueError("Creation lacks correlated Party evidence.")
    kinds = {
        "contacts": ("party_contact_method", ContactMethodCommand),
        "services": ("provider_service", ServiceCommand),
        "areas": ("provider_service_area", ServiceAreaCommand),
        "work_history": ("provider_work_history", WorkHistoryCommand),
        "references": ("provider_reference", ReferenceCommand),
    }
    for field, (entity, definition) in kinds.items():
        history = [a for a in events if a["entity_type"] == entity]
        if not isinstance(payload[field], list) or len(history) != len(payload[field]):
            raise ValueError("Initial child history differs.")
        for requested, event in zip(payload[field], history, strict=True):
            normalized = definition(
                **{k: v for k, v in requested.items() if k != "normalized_value"}
            )
            if (
                asdict(normalized) != requested
                or event["action"] != "created"
                or event["before_snapshot"] is not None
            ):
                raise ValueError("Initial child command differs.")
            after = json.loads(event["after_snapshot"])
            names = {
                "method_kind": "methodKind",
                "value": "displayValue",
                "normalized_value": "normalizedValue",
                "display_name": "displayName",
                "country_code": "countryCode",
                "performed_on": "performedOn",
                "property_id": "propertyId",
                "outcome_notes": "outcomeNotes",
                "reference_name": "referenceName",
                "organization_name": "organizationName",
            }
            if (
                after["partyId"] != row["party_id"]
                or after["createdAt"] != row["created_at"]
                or after["updatedAt"] != row["created_at"]
                or after["archivedAt"] is not None
                or any(after[names.get(key, key)] != value for key, value in requested.items())
            ):
                raise ValueError("Initial child attribution differs.")
    assigned = [
        json.loads(a["after_snapshot"])
        for a in events
        if a["entity_type"] == "provider_category_assignment" and a["action"] == "created"
    ]
    if sorted(a["categoryId"] for a in assigned) != payload["category_ids"] or any(
        a["providerPartyId"] != row["party_id"] for a in assigned
    ):
        raise ValueError("Initial category history differs.")
