"""Category and assignment receipts reconstructed against immutable audit history."""

import json
from dataclasses import asdict

from sqlalchemy import text

from app.modules.vendors.application.category_commands import (
    CategoryCommand,
    category_receipt_audit,
)
from app.modules.vendors.application.commands import canonical, fingerprint
from app.modules.vendors.application.service import (
    ProviderCategoryCommand,
    ProviderCategoryPatchCommand,
    UNSET,
)
from app.modules.vendors.domain.category_normalization import normalize_provider_category_name
from app.modules.vendors.domain.category_seeds import PROVIDER_CATEGORY_SEEDS
from app.modules.vendors.domain.models import ProviderCategory, ProviderCategoryAssignment
from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderCategoryModel,
    ProviderCategoryCommandOperationModel,
    ProviderCategoryAssignmentModel,
)
from app.modules.vendors.infrastructure.command_validation import _uuid, _utc


class CategoryHistory:
    def __init__(self, connection, audits):
        self.audits = audits
        self.current = {
            r["id"]: ProviderCategory(**r)
            for r in connection.execute(ProviderCategoryModel.__table__.select()).mappings()
        }
        self.operations = (
            connection.execute(
                ProviderCategoryCommandOperationModel.__table__.select().order_by(text("rowid"))
            )
            .mappings()
            .all()
        )
        self.origins = {}
        for seed in PROVIDER_CATEGORY_SEEDS:
            row = self.current[seed.id]
            self.origins[seed.id] = {
                "id": seed.id,
                "displayName": seed.display_name,
                "normalizedName": seed.normalized_name,
                "description": None,
                "displayOrder": seed.display_order,
                "createdAt": row.created_at,
                "updatedAt": row.created_at,
                "archivedAt": None,
                "archiveReason": None,
                "revision": 1,
            }
        self.tips = dict(self.origins)
        self.seen = set()

    def validate(self):
        for row in self.operations:
            for field in ("id", "category_id", "idempotency_key", "correlation_id"):
                _uuid(row[field])
            _utc(row["created_at"])
            request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
            if (
                set(request) != {"action", "categoryId", "expectedRevision", "payload"}
                or canonical(request) != row["request_json"]
                or fingerprint(request) != row["request_fingerprint"]
                or canonical(result) != row["result_json"]
            ):
                raise ValueError("Category receipt request differs.")
            command = CategoryCommand(
                request["action"],
                request["categoryId"],
                request["expectedRevision"],
                row["idempotency_key"],
                request["payload"],
            )
            previous = self.tips.get(row["category_id"])
            if (
                command.action != row["action"]
                or command.expected_revision != row["expected_revision"]
                or command.category_id
                != (None if command.action == "create" else row["category_id"])
                or command.expected_revision != (previous["revision"] if previous else 0)
            ):
                raise ValueError("Category receipt lineage differs.")
            if (
                set(result) != {"category", "revision", "operationId"}
                or result["operationId"] != row["id"]
                or type(result["revision"]) is not int
                or result["revision"] != row["resulting_revision"]
            ):
                raise ValueError("Category receipt result differs.")
            state = dict(result["category"])
            count = state.pop("effectiveProviderCount")
            expected = category_transition(command, previous, row["category_id"], row["created_at"])
            if state != expected or state["revision"] != result["revision"]:
                raise ValueError("Category command transition differs.")
            events = [
                a
                for a in self.audits
                if a["entity_type"] == "provider_category_command_operation"
                and a["entity_id"] == row["id"]
            ]
            if (
                len(events) != 1
                or events[0]["action"] != "recorded"
                or events[0]["correlation_id"] != row["correlation_id"]
                or events[0]["before_snapshot"] is not None
                or json.loads(events[0]["after_snapshot"]) != category_receipt_audit(row)
            ):
                raise ValueError("Category receipt audit differs.")
            position = self.audits.index(events[0])
            if type(count) is not int or count != self.count_at(state, position):
                raise ValueError("Category original effective count differs.")
            history = [
                a
                for a in self.audits
                if a["entity_type"] == "provider_category"
                and a["entity_id"] == state["id"]
                and a["correlation_id"] == row["correlation_id"]
            ]
            changed = previous != state
            if changed:
                action = {
                    "create": "created",
                    "patch": "updated",
                    "archive": "archived",
                    "restore": "restored",
                }[command.action]
                if (
                    len(history) != 1
                    or history[0]["action"] != action
                    or json.loads(history[0]["after_snapshot"]) != state
                    or (
                        json.loads(history[0]["before_snapshot"])
                        if history[0]["before_snapshot"]
                        else None
                    )
                    != previous
                    or self.audits.index(history[0]) >= position
                ):
                    raise ValueError("Category transition audit differs.")
                self.seen.add(history[0]["id"])
            elif history:
                raise ValueError("Category no-op has mutation audit.")
            if (
                command.action == "create"
                and self.current[state["id"]].create_idempotency_key != row["idempotency_key"]
            ):
                raise ValueError("Category creation key differs.")
            self.tips[state["id"]] = state
        if {key: item.to_dict() for key, item in self.current.items()} != self.tips or any(
            a["entity_type"] == "provider_category" and a["id"] not in self.seen
            for a in self.audits
        ):
            raise ValueError("Category history does not match retained rows.")
        ids = {r["id"] for r in self.operations}
        if any(
            a["entity_type"] == "provider_category_command_operation" and a["entity_id"] not in ids
            for a in self.audits
        ):
            raise ValueError("Category audit lacks its operation.")

    def at(self, category_id, correlation):
        receipt = next(
            a
            for a in self.audits
            if a["entity_type"] == "provider_command_operation"
            and a["correlation_id"] == correlation
        )
        state = self.origins.get(category_id)
        for event in self.audits[: self.audits.index(receipt)]:
            if event["entity_type"] == "provider_category" and event["entity_id"] == category_id:
                state = json.loads(event["after_snapshot"])
        if state is None:
            raise ValueError("Assignment lacks category history.")
        return state

    def count_at(self, category, position):
        if category["archivedAt"] is not None:
            return 0
        profiles, assignments = {}, {}
        for event in self.audits[:position]:
            if event["entity_type"] == "provider_profile":
                profiles[event["entity_id"]] = json.loads(event["after_snapshot"])
            elif event["entity_type"] == "provider_category_assignment":
                assignments[event["entity_id"]] = json.loads(event["after_snapshot"])
        return sum(
            item["categoryId"] == category["id"]
            and item["archivedAt"] is None
            and profiles[item["providerPartyId"]]["archivedAt"] is None
            for item in assignments.values()
        )


def category_transition(command, previous, category_id, now):
    fields = command.payload
    if command.action == "create":
        normalized = ProviderCategoryCommand(idempotency_key=command.idempotency_key, **fields)
        if {k: v for k, v in asdict(normalized).items() if k != "idempotency_key"} != fields:
            raise ValueError("Category creation is not normalized.")
        return {
            "id": category_id,
            "displayName": normalized.display_name,
            "normalizedName": normalize_provider_category_name(normalized.display_name),
            "description": normalized.description,
            "displayOrder": normalized.display_order,
            "createdAt": now,
            "updatedAt": now,
            "archivedAt": None,
            "archiveReason": None,
            "revision": 1,
        }
    expected = dict(previous)
    if command.action == "patch":
        if previous["archivedAt"] is not None:
            raise ValueError("Archived category patch.")
        normalized = ProviderCategoryPatchCommand(**fields)
        if {k: v for k, v in normalized.__dict__.items() if v is not UNSET} != fields:
            raise ValueError("Category patch is not normalized.")
        names = {
            "display_name": "displayName",
            "description": "description",
            "display_order": "displayOrder",
        }
        expected.update({names[k]: v for k, v in fields.items()})
        expected["normalizedName"] = normalize_provider_category_name(expected["displayName"])
    elif command.action == "archive":
        reason = fields.get("reason")
        if (
            set(fields) != {"confirmed", "reason"}
            or fields["confirmed"] is not True
            or not isinstance(reason, str)
            or not 1 <= len(reason) <= 1000
            or reason.strip() != reason
        ):
            raise ValueError("Invalid category archive command.")
        if previous["archivedAt"] is not None:
            if reason != previous["archiveReason"]:
                raise ValueError("Changed archive retry.")
        else:
            expected.update(archivedAt=now, archiveReason=reason)
    else:
        if fields != {"confirmed": True}:
            raise ValueError("Invalid category restore command.")
        expected.update(archivedAt=None, archiveReason=None)
    if expected != previous:
        expected.update(updatedAt=now, revision=previous["revision"] + 1)
    return expected


class AssignmentHistory:
    def __init__(self, connection, audits, categories):
        self.audits, self.categories = audits, categories
        self.tips, self.seen = {}, set()
        self.current = {
            r["id"]: ProviderCategoryAssignment(**r).to_dict()
            for r in connection.execute(
                ProviderCategoryAssignmentModel.__table__.select()
            ).mappings()
        }
        self.creation_keys = {
            r["id"]: r["create_idempotency_key"]
            for r in connection.execute(
                ProviderCategoryAssignmentModel.__table__.select()
            ).mappings()
        }

    def initial(self, operation):
        for event in self.audits:
            if (
                event["entity_type"] == "provider_category_assignment"
                and event["correlation_id"] == operation["correlation_id"]
            ):
                if event["action"] != "created" or event["entity_id"] in self.tips:
                    raise ValueError("Invalid initial assignment.")
                state = json.loads(event["after_snapshot"])
                category = self.categories.at(state["categoryId"], operation["correlation_id"])
                if category["archivedAt"] is not None:
                    raise ValueError("Initial assignment used an archived category.")
                self.tips[event["entity_id"]] = state
                self.seen.add(event["id"])

    def validate(self, command, row, result, profile):
        verb, payload, state = (
            command.action.removeprefix("assignment_"),
            command.payload,
            result["item"],
        )
        if result["kind"] != "assignment" or profile["archivedAt"] is not None:
            raise ValueError("Invalid assignment result/lifecycle.")
        _uuid(state["id"])
        previous = self.tips.get(state["id"])
        expected_keys = {"assignment_id"} | (
            {"category_id", "expected_category_revision"}
            if verb == "create"
            else {"confirmed", "reason"}
            if verb == "archive"
            else {"confirmed", "expected_category_revision"}
        )
        if (
            set(payload) != expected_keys
            or state["providerPartyId"] != row["party_id"]
            or payload["assignment_id"] != (None if verb == "create" else state["id"])
        ):
            raise ValueError("Assignment request differs.")
        category = self.categories.at(state["categoryId"], row["correlation_id"])
        if result["category"] != category:
            raise ValueError("Assignment category snapshot differs.")
        if verb != "archive" and (
            type(payload["expected_category_revision"]) is not int
            or payload["expected_category_revision"] != category["revision"]
            or category["archivedAt"] is not None
        ):
            raise ValueError("Assignment category revision/lifecycle differs.")
        if verb == "create":
            if (
                previous
                or state["categoryId"] != payload["category_id"]
                or self.creation_keys[state["id"]] != row["idempotency_key"]
            ):
                raise ValueError("Assignment identity differs.")
            expected = {
                "id": state["id"],
                "providerPartyId": row["party_id"],
                "categoryId": payload["category_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["created_at"],
                "archivedAt": None,
                "archiveReason": None,
            }
        else:
            if previous is None or payload["confirmed"] is not True:
                raise ValueError("Assignment lifecycle command differs.")
            expected = dict(previous)
            if verb == "archive":
                reason = payload["reason"]
                if (
                    not isinstance(reason, str)
                    or not 1 <= len(reason) <= 1000
                    or reason.strip() != reason
                    or (previous["archivedAt"] is not None and reason != previous["archiveReason"])
                ):
                    raise ValueError("Assignment archive reason differs.")
                if previous["archivedAt"] is None:
                    expected.update(
                        archivedAt=row["created_at"],
                        archiveReason=reason,
                        updatedAt=row["created_at"],
                    )
            elif previous["archivedAt"] is not None:
                expected.update(archivedAt=None, archiveReason=None, updatedAt=row["created_at"])
        if expected != state:
            raise ValueError("Assignment result differs from command.")
        events = [
            a
            for a in self.audits
            if a["entity_type"] == "provider_category_assignment"
            and a["entity_id"] == state["id"]
            and a["correlation_id"] == row["correlation_id"]
        ]
        if state != previous:
            action = {"create": "created", "archive": "archived", "restore": "restored"}[verb]
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
                raise ValueError("Assignment audit differs.")
            self.seen.add(events[0]["id"])
        elif events:
            raise ValueError("Assignment no-op audit differs.")
        self.tips[state["id"]] = state
        return state != previous

    def finish(self):
        if self.current != self.tips or any(
            a["entity_type"] == "provider_category_assignment" and a["id"] not in self.seen
            for a in self.audits
        ):
            raise ValueError("Retained assignment differs from its receipts.")
