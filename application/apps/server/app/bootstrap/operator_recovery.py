"""Composition of source-owned recovery reference and receipt contracts."""

import json
from dataclasses import dataclass
from collections.abc import Mapping

from app.modules.communications.application.ports import CommunicationContextOperations
from app.modules.communications.application.receipt_ports import CommunicationReceiptReader
from app.modules.maintenance.application.receipt_ports import IssueCommandReceiptReader
from app.modules.operator.domain.models import OperatorConflict, OperatorError, fingerprint
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS
from app.bootstrap.operator_command_forms import require_complete_form
from app.modules.operator.application.recovery_results import receipt_projection
from app.modules.parties.application.ports import PartyTransactionOperations
from app.modules.portfolio.application.ports import PortfolioContextReader
from app.modules.tasks.application.creation import TaskCreationReceiptReader


@dataclass(frozen=True)
class RecoverySourcePorts:
    portfolio: PortfolioContextReader
    parties: PartyTransactionOperations
    contexts: CommunicationContextOperations


class OperatorRecoveryReferences:
    def __init__(
        self,
        sources: RecoverySourcePorts,
        issues: IssueCommandReceiptReader,
        communications: CommunicationReceiptReader,
        tasks: TaskCreationReceiptReader,
        *,
        commands: Mapping[str, RecoveryBinding] | None = None,
    ):
        self.portfolio, self.parties, self.contexts = (
            sources.portfolio,
            sources.parties,
            sources.contexts,
        )
        self.issues, self.communications = issues, communications
        self.tasks = tasks
        self.commands = commands or {}
        if commands is not None and set(commands) != set(COMMAND_SCHEMAS):
            raise ValueError("Recovery schemas and source bindings must match exactly.")

    def validate(self, connection, value):
        payload = json.loads(value["payload_json"])
        if value["form_key"] in self.commands:
            state = self._command_state(connection, value, payload)
            return self._context_state(connection, payload) if state == "available" else state
        source_state = self._source_state(connection, value)
        if source_state != "available":
            return source_state
        location_state = self._location_state(connection, payload)
        if location_state != "available":
            return location_state
        reporter = payload.get("reporter") or {}
        if reporter.get("partyId") and self.parties.party(connection, reporter["partyId"]) is None:
            return "source_missing"
        return self._context_state(connection, payload)

    def _command_state(self, connection, value, payload):
        binding = self.commands[value["form_key"]]
        if value["source_kind"] != binding.source_kind:
            return "unsupported_source"
        if binding.source_kind is None:
            return (
                "available"
                if value["source_id"] is None and value["base_source_revision"] is None
                else "unsupported_source"
            )
        state = binding.reader.state(connection, value["source_id"])
        if state is None or state.get("deleted_at_utc"):
            return "source_unavailable"
        if value["base_source_revision"] != str(state["revision"]) or payload.get(
            "expectedRevision"
        ) not in {None, state["revision"]}:
            return "source_changed"
        if not command_lifecycle(binding, state["status"]):
            return "source_unavailable"
        return related_command_state(connection, binding, value["source_id"], payload)

    def attempt_fingerprint(self, value, key):
        binding = self.commands.get(value["form_key"])
        if binding is None:
            raise OperatorConflict("This workflow has no registered command binding.")
        try:
            payload = json.loads(value["payload_json"])
            require_complete_form(value["form_key"], payload)
            if payload.get("expectedRevision") is None:
                raise OperatorError("Complete the expected source revision.")
            calculated = binding.fingerprint(value["source_id"], payload, key)
        except (ValueError, TypeError, KeyError) as error:
            if isinstance(error, OperatorError):
                raise
            raise OperatorError(
                "Complete a valid owning command before starting an attempt."
            ) from error
        return calculated

    def _source_state(self, connection, value):
        kind, source_id = value["source_kind"], value["source_id"]
        if not kind:
            return "available"
        if kind not in {"property", "space", "party"}:
            return "unsupported_source"
        if kind == "party":
            party = self.parties.party(connection, source_id)
            source = party.__dict__ if party else None
            active = party is not None and party.archived_at is None
        else:
            source = self._location_context(connection, kind, source_id)
            active = source is not None and source["property_status"] == "active"
            active = active and source.get("space_status") in {None, "active"}
        if not active:
            return "source_unavailable"
        if value["base_source_revision"] is not None and value[
            "base_source_revision"
        ] != fingerprint(source):
            return "source_changed"
        return "available"

    def _location_context(self, connection, kind, source_id):
        if kind == "property":
            return self.portfolio.context_for_property_space(connection, source_id, None)
        location = self.portfolio.context_for_space(connection, source_id)
        if location is None:
            return None
        return self.portfolio.context_for_property_space(
            connection, location["property_id"], source_id
        )

    def _location_state(self, connection, payload):
        property_id, space_id = payload.get("propertyId"), payload.get("spaceId")
        if property_id:
            context = self.portfolio.context_for_property_space(connection, property_id, space_id)
            if (
                context is None
                or context["property_status"] != "active"
                or context.get("space_status") not in {None, "active"}
            ):
                return "source_unavailable"
        elif space_id:
            if self.portfolio.context_for_space(connection, space_id) is None:
                return "source_missing"
        return "available"

    def _context_state(self, connection, payload):
        try:
            if payload.get("relatedEntityType") and payload.get("relatedEntityId"):
                self.contexts.validate_link(
                    connection, payload["relatedEntityType"], payload["relatedEntityId"]
                )
            for participant in payload.get("participants", ()):
                self.contexts.participant_snapshot(
                    connection, participant["partyId"], participant.get("partyContactMethodId")
                )
            for link in payload.get("links", ()):
                self.contexts.validate_link(connection, link["entityType"], link["entityId"])
        except ValueError, KeyError:
            return "source_unavailable"
        return "available"

    def resolve_attempt(self, connection, form_key, key, request_fingerprint, *, source_id=None):
        if form_key in self.commands:
            return self._command_outcome(connection, form_key, key, request_fingerprint, source_id)
        if form_key == "maintenance.issue.create":
            value = self.issues.receipt(connection, key)
            kind, target = "maintenance_issue", value["result_issue_id"] if value else None
        elif form_key == "communication.record":
            value = self.communications.receipt(connection, key)
            kind, target = "communication", value["result_communication_id"] if value else None
        elif form_key == "task.create":
            value = self.tasks.receipt(connection, key)
            kind, target = "task", value["task_id"] if value else None
        else:
            raise OperatorConflict("This workflow has no registered durable command receipt.")
        if value is None:
            return None
        if value["request_fingerprint"] != request_fingerprint:
            raise OperatorConflict("The owning command receipt belongs to a different request.")
        return {"sourceKind": kind, "sourceId": target, "receiptId": value["id"], "attemptKey": key}

    def _command_outcome(self, connection, form_key, key, request_fingerprint, source_id):
        binding = self.commands[form_key]
        outcome = binding.reader.outcome(connection, key, family=binding.family)
        if outcome is None:
            return None
        if outcome.request_fingerprint != request_fingerprint:
            raise OperatorConflict("The owning command receipt belongs to a different request.")
        if binding.source_kind is not None and outcome.source_id != source_id:
            raise OperatorConflict("The owning receipt belongs to a different source.")
        if outcome.action != binding.receipt_action:
            raise OperatorConflict("The owning receipt belongs to a different workflow.")
        return receipt_projection(outcome, binding.source_kind, key)


def command_lifecycle(binding, status):
    """Form reuse gate only; the source command still owns all mutation policy."""
    defaults = {
        "task": {"open", "in_progress"},
        "communication": {"draft"},
        "space": {"active"},
        "maintenance_issue": {"open", "in_progress"},
    }
    overrides = {
        ("task", "reopen"): {"completed", "cancelled"},
        ("task", "start"): {"open"},
        ("task", "delete"): {"open"},
        ("communication", "corrected"): {"recorded"},
        ("maintenance_issue", "reopen"): {"resolved", "cancelled"},
        ("maintenance_issue", "start"): {"open"},
        ("maintenance_issue", "return_to_open"): {"in_progress"},
        ("maintenance_issue", "record"): {"open", "in_progress", "resolved", "cancelled"},
        ("maintenance_issue", "correct_reporter"): {"open", "in_progress", "resolved", "cancelled"},
    }
    return status in overrides.get(
        (binding.source_kind, binding.action), defaults[binding.source_kind]
    )


def related_command_state(connection, binding, source_id, payload):
    targets = {
        "update_appointment": ("appointment", "targetId"),
        "finish_appointment": ("appointment", "targetId"),
        "void_cost": ("cost_context", "targetId"),
        "archive_expense_link": ("expense_link", "targetId"),
        "withdraw_quote": ("quote", "targetId"),
        "end_assignment": ("assignment", "targetId"),
        "acknowledge": ("reminder", "reminderId"),
        "dismiss": ("reminder", "reminderId"),
        "occupancy_cancelled": ("occupancy", "periodId"),
        "occupancy_replaced": ("occupancy", "periodId"),
        "occupancy_corrected": ("occupancy", "periodId"),
        "occupancy_rescheduled": ("occupancy", "periodId"),
    }
    target = targets.get(binding.action)
    if target is None or payload.get(target[1]) is None:
        return "available"  # incomplete autosave; preparation requires this field
    kind, field = target
    state = binding.related_state(connection, kind, payload[field])
    if state is None or state["source_id"] != source_id or state.get("terminal_at") is not None:
        return "source_unavailable"
    allowed = {"appointment": "scheduled", "reminder": "pending", "occupancy": "valid"}
    if kind in allowed and state["status"] != allowed[kind]:
        return "source_unavailable"
    if kind == "occupancy" and state["source_kind"] != "manual":
        return "source_unavailable"
    return "available"
