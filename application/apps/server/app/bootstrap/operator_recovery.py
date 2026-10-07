"""Composition of source-owned recovery reference and receipt contracts."""

import json
from dataclasses import dataclass

from app.modules.communications.application.ports import CommunicationContextOperations
from app.modules.communications.application.receipt_ports import CommunicationReceiptReader
from app.modules.maintenance.application.receipt_ports import IssueCommandReceiptReader
from app.modules.operator.domain.models import OperatorConflict, fingerprint
from app.modules.parties.application.ports import PartyTransactionOperations
from app.modules.portfolio.application.ports import PortfolioContextReader


@dataclass(frozen=True)
class RecoverySourcePorts:
    portfolio: PortfolioContextReader
    parties: PartyTransactionOperations
    contexts: CommunicationContextOperations


class OperatorRecoveryReferences:
    def __init__(
        self,
        portfolio: PortfolioContextReader,
        parties: PartyTransactionOperations,
        contexts: CommunicationContextOperations,
        issues: IssueCommandReceiptReader,
        communications: CommunicationReceiptReader,
    ):
        self.portfolio, self.parties, self.contexts = portfolio, parties, contexts
        self.issues, self.communications = issues, communications

    def validate(self, connection, value):
        payload = json.loads(value["payload_json"])
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

    def resolve_attempt(self, connection, form_key, key, request_fingerprint):
        if form_key == "maintenance.issue.create":
            value = self.issues.receipt(connection, key)
            kind, target = "maintenance_issue", value["id"] if value else None
        elif form_key == "communication.record":
            value = self.communications.receipt(connection, key)
            kind, target = "communication", value["result_communication_id"] if value else None
        else:
            raise OperatorConflict("This workflow has no registered durable command receipt.")
        if value is None:
            return None
        if value["request_fingerprint"] != request_fingerprint:
            raise OperatorConflict("The owning command receipt belongs to a different request.")
        return {"sourceKind": kind, "sourceId": target, "receiptId": value["id"], "attemptKey": key}
