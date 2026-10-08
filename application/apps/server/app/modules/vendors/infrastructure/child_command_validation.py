"""Reconstruct child commands and bind immutable receipts to retained child tips."""

import json
from dataclasses import asdict, replace

from app.modules.vendors.application.service import (
    ServiceCommand,
    ServiceAreaCommand,
    WorkHistoryCommand,
    ReferenceCommand,
    ReputationLinkCommand,
    ReputationLinkPatchCommand,
    _new_child,
    _new_reputation_link,
    _update_child,
    _update_reputation,
)
from app.modules.vendors.domain.models import (
    ProviderService,
    ProviderServiceArea,
    ProviderWorkHistory,
    ProviderReference,
    ProviderReputationLink,
)
from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderServiceModel,
    ProviderServiceAreaModel,
    ProviderWorkHistoryModel,
    ProviderReferenceModel,
    ProviderReputationLinkModel,
)
from app.modules.vendors.infrastructure.command_validation import _uuid, _utc

SPECS = {
    "service": ("provider_service", ProviderService, ProviderServiceModel, ServiceCommand),
    "area": (
        "provider_service_area",
        ProviderServiceArea,
        ProviderServiceAreaModel,
        ServiceAreaCommand,
    ),
    "work": (
        "provider_work_history",
        ProviderWorkHistory,
        ProviderWorkHistoryModel,
        WorkHistoryCommand,
    ),
    "reference": (
        "provider_reference",
        ProviderReference,
        ProviderReferenceModel,
        ReferenceCommand,
    ),
    "reputation": (
        "provider_reputation_link",
        ProviderReputationLink,
        ProviderReputationLinkModel,
        ReputationLinkCommand,
    ),
}


class _RetainedProperties:
    def property_exists(self, property_id):
        # Current table/FK and owning retained validators establish target existence;
        # historical commands may reference a property archived since the command.
        _uuid(property_id)
        return True


class ChildHistory:
    def __init__(self, connection, audits):
        self.audits = audits
        self.tips = {}
        self.seen = set()
        self.current = {}
        for kind, (_, definition, model, _) in SPECS.items():
            for row in connection.execute(model.__table__.select()).mappings():
                self.current[kind, row["id"]] = definition(**row).to_dict()

    def initial(self, operation):
        for event in self.audits:
            if event["correlation_id"] != operation["correlation_id"]:
                continue
            for kind, (entity, _, _, _) in SPECS.items():
                if event["entity_type"] == entity:
                    key = kind, event["entity_id"]
                    if (
                        kind == "reputation"
                        or key in self.tips
                        or event["action"] != "created"
                        or event["before_snapshot"]
                    ):
                        raise ValueError("Invalid initial child history.")
                    self.tips[key] = json.loads(event["after_snapshot"])
                    self.seen.add(event["id"])

    def validate(self, command, row, result, profile):
        kind, verb = command.action.rsplit("_", 1)
        entity, definition, _, command_type = SPECS[kind]
        if profile is None or profile["archivedAt"] is not None:
            raise ValueError("Child command requires an active Provider.")
        payload, state = command.payload, result["item"]
        if set(payload) != {"item_id", "fields"} or result["kind"] != kind:
            raise ValueError("Child request shape differs.")
        _uuid(state["id"])
        _utc(state["createdAt"])
        _utc(state["updatedAt"])
        if state["partyId"] != row["party_id"]:
            raise ValueError("Child attribution differs.")
        key = kind, state["id"]
        previous = self.tips.get(key)
        if (verb == "create" and (payload["item_id"] is not None or previous is not None)) or (
            verb != "create" and (payload["item_id"] != state["id"] or previous is None)
        ):
            raise ValueError("Child identity/lineage differs.")
        # Rehydrate the exact portable snapshot without relying on current mutable rows.
        names = {field: _camel(field) for field in definition.__dataclass_fields__}
        if kind == "area":
            names["country_code"] = "countryCode"
        current = (
            definition(
                **{
                    field: previous[name] if field != "country_code" else previous[name] or ""
                    for field, name in names.items()
                }
            )
            if previous
            else None
        )
        fields = payload["fields"]
        now, facts = row["created_at"], _RetainedProperties()
        if verb in {"create", "update"}:
            if current and current.archived_at is not None:
                raise ValueError("Cannot edit archived child.")
            requested = (
                ReputationLinkPatchCommand
                if verb == "update" and kind == "reputation"
                else command_type
            )(
                **{
                    k: v
                    for k, v in fields.items()
                    if k not in {"normalized_url", "normalized_source_key"}
                }
            )
            normalized = {k: v for k, v in requested.__dict__.items() if k in fields}
            if normalized != fields or (verb == "create" and asdict(requested) != fields):
                raise ValueError("Child fields are not canonical.")
            if kind == "reputation":
                expected = (
                    _new_reputation_link(row["party_id"], requested, now)
                    if verb == "create"
                    else _update_reputation(current, requested, now)
                )
            else:
                expected = (
                    _new_child(kind, row["party_id"], requested, now, facts)
                    if verb == "create"
                    else _update_child(current, requested, now, facts)
                )
            expected = replace(expected, id=state["id"])
            if current and replace(expected, updated_at=current.updated_at) == current:
                expected = current
        else:
            if verb == "archive":
                if fields != {"confirmed": True} or current.archived_at is not None:
                    raise ValueError("Invalid child archival.")
            elif fields or current.archived_at is None:
                raise ValueError("Invalid child restore.")
            expected = replace(
                current, updated_at=now, archived_at=now if verb == "archive" else None
            )
        if expected.to_dict() != state:
            raise ValueError("Child result does not match its command.")
        events = [
            a
            for a in self.audits
            if a["entity_type"] == entity
            and a["entity_id"] == state["id"]
            and a["correlation_id"] == row["correlation_id"]
        ]
        changed = previous != state
        if changed:
            action = {
                "create": "created",
                "update": "updated",
                "archive": "archived",
                "restore": "restored",
            }[verb]
            if (
                len(events) != 1
                or events[0]["action"] != action
                or json.loads(events[0]["after_snapshot"]) != state
                or (
                    json.loads(events[0]["before_snapshot"])
                    if events[0]["before_snapshot"]
                    else None
                )
                != previous
            ):
                raise ValueError("Child transition audit differs.")
            self.seen.add(events[0]["id"])
        elif events or verb != "update":
            raise ValueError("No-op child audit differs.")
        self.tips[key] = state
        return changed

    def finish(self):
        entities = {spec[0] for spec in SPECS.values()}
        if self.current != self.tips or any(
            a["entity_type"] in entities and a["id"] not in self.seen for a in self.audits
        ):
            raise ValueError("Retained child differs from command history.")


def _camel(name):
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)
