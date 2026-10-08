"""Validate retained Maintenance receipts and their original audit evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import column, select, table

from app.modules.maintenance.application.commands import canonical_payload
from app.platform.migration_errors import MigrationSchemaError

from .sqlalchemy_models import MaintenanceCommandReceiptModel, MaintenanceIssueModel

# Exact source operation identities. These are intentionally Maintenance-specific.
COMMAND_TARGETS = {
    "create_issue": "issue",
    "patch_issue": "issue",
    "correct_reporter": "issue",
    "transition": "issue",
    "create_appointment": "issue",
    "create_cost": "issue",
    "link_expense": "issue",
    "create_quote": "issue",
    "create_assignment": "issue",
    "create_follow_up": "issue",
    "record": "issue",
    "update_appointment": "appointment",
    "finish_appointment": "appointment",
    "void_cost": "cost_context",
    "archive_expense_link": "expense_link",
    "withdraw_quote": "quote",
    "end_assignment": "assignment",
}


def validate_command_receipts(connection) -> None:
    issues = {
        row.id: row.revision
        for row in connection.execute(
            select(MaintenanceIssueModel.id, MaintenanceIssueModel.revision)
        )
    }
    events = table(
        "audit_events",
        *(
            column(name)
            for name in (
                "entity_type",
                "entity_id",
                "action",
                "before_snapshot",
                "after_snapshot",
                "correlation_id",
                "reason",
                "schema_version",
                "changed_fields",
            )
        ),
    )
    audits = defaultdict(list)
    for event in connection.execute(select(events)).mappings():
        audits[event["correlation_id"]].append(event)
    receipts = list(connection.execute(select(MaintenanceCommandReceiptModel)).mappings())
    chains = defaultdict(list)
    operation_ids = set()
    try:
        for receipt in receipts:
            operation_ids.add(receipt["id"])
            _validate_receipt(receipt, audits[receipt["id"]])
            chains[receipt["issue_id"]].append(receipt)
        for issue_id, current_revision in issues.items():
            chain = chains[issue_id]
            effective = sorted((r for r in chain if r["effective"]), key=lambda r: r["revision"])
            if (
                type(current_revision) is not int
                or current_revision < 1
                or [r["revision"] for r in effective] != list(range(1, current_revision + 1))
                or not effective
                or effective[0]["action"] != "create_issue"
                or any(r["revision"] > current_revision for r in chain)
            ):
                raise ValueError("issue revision chain")
        if set(chains) != set(issues):
            raise ValueError("receipt issue ownership")
        # Every source mutation audit must belong to an immutable command. External
        # evidence-link audit events retain their own source operation identities.
        actions = {
            "created",
            "updated",
            "reporter_corrected",
            "started",
            "returned_to_open",
            "resolved",
            "cancelled",
            "reopened",
            "completed",
            "voided",
            "archived",
            "withdrawn",
            "ended",
            "follow_up_created",
            "command_recorded",
        }
        entities = {
            "maintenance_issue",
            "maintenance_appointment",
            "maintenance_cost_context",
            "maintenance_expense_link",
            "maintenance_quote",
            "maintenance_assignment",
            "maintenance_work_journal_entry",
        }
        for correlation, correlated in audits.items():
            if any(e["entity_type"] in entities and e["action"] in actions for e in correlated):
                if correlation not in operation_ids:
                    raise ValueError("orphan command audit")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError(
            "Maintenance command receipts or audit evidence are incompatible."
        ) from error


def _validate_receipt(receipt, audits):
    for name in ("id", "idempotency_key", "issue_id", "target_id"):
        if receipt[name] is not None and str(UUID(receipt[name])) != receipt[name]:
            raise ValueError("command UUID")
    instant = datetime.fromisoformat(receipt["created_at"])
    if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
        raise ValueError("command instant")
    request = json.loads(receipt["request_payload"])
    response = json.loads(receipt["response_payload"])
    for prefix, payload in (("request", request), ("response", response)):
        encoded = receipt[f"{prefix}_payload"]
        if (
            canonical_payload(payload) != encoded
            or sha256(encoded.encode()).hexdigest() != receipt[f"{prefix}_fingerprint"]
        ):
            raise ValueError("canonical command evidence")
    action = receipt["action"]
    if COMMAND_TARGETS.get(action) != receipt["target_kind"]:
        raise ValueError("command identity")
    if set(request) != {"action", "targetKind", "targetId", "expectedRevision", "payload"}:
        raise ValueError("request envelope")
    if request != {
        "action": action,
        "targetKind": receipt["target_kind"],
        "targetId": receipt["target_id"],
        "expectedRevision": receipt["expected_revision"],
        "payload": request["payload"],
    } or not isinstance(request["payload"], dict):
        raise ValueError("request identity")
    expected, revision, effective = (
        receipt["expected_revision"],
        receipt["revision"],
        receipt["effective"],
    )
    if (
        type(expected) is not int
        or type(revision) is not int
        or type(effective) is not int
        or expected < 0
        or revision < 1
        or effective not in (0, 1)
        or revision != expected + effective
    ):
        raise ValueError("command revisions")
    if action == "create_issue":
        if receipt["target_id"] is not None or expected != 0 or effective != 1:
            raise ValueError("creation revision")
    elif receipt["target_id"] is None or expected < 1:
        raise ValueError("mutation target")
    if (
        not isinstance(response, dict)
        or response.get("operationId") != receipt["id"]
        or response.get("revision") != revision
    ):
        raise ValueError("response identity")
    UUID(response["id"])
    if action in {"create_issue", "patch_issue", "correct_reporter", "transition"}:
        if response["id"] != receipt["issue_id"]:
            raise ValueError("response issue")
    elif action == "create_follow_up":
        if (
            response.get("relatedEntityType") != "maintenance_issue"
            or response.get("relatedEntityId") != receipt["issue_id"]
        ):
            raise ValueError("response task ownership")
    elif response.get("issueId") != receipt["issue_id"]:
        raise ValueError("response child ownership")
    if receipt["target_kind"] != "issue" and response["id"] != receipt["target_id"]:
        raise ValueError("response child identity")
    markers = [e for e in audits if e["action"] == "command_recorded"]
    if len(markers) != 1:
        raise ValueError("command marker")
    marker = markers[0]
    snapshot = {
        "operationId": receipt["id"],
        "commandAction": action,
        "expectedRevision": expected,
        "revision": revision,
        "effective": bool(effective),
        "requestFingerprint": receipt["request_fingerprint"],
        "responseFingerprint": receipt["response_fingerprint"],
    }
    if (
        marker["entity_type"] != "maintenance_issue"
        or marker["entity_id"] != receipt["issue_id"]
        or marker["before_snapshot"] is not None
        or marker["reason"] != "maintenance_command"
        or marker["schema_version"] != 1
        or json.loads(marker["after_snapshot"]) != snapshot
        or json.loads(marker["changed_fields"]) != ["$"]
    ):
        raise ValueError("command marker evidence")
    mutations = [e for e in audits if e["action"] != "command_recorded"]
    if bool(mutations) != bool(effective):
        raise ValueError("effective command audit")
    if not effective and action not in {"patch_issue", "update_appointment"}:
        raise ValueError("unexpected no-op")
