"""Shared, non-sensitive source summary projection."""

from __future__ import annotations

from typing import Mapping


def source_summary(
    source: Mapping[str, object],
    *,
    fingerprint: str | None,
    attachment_count: int,
) -> dict[str, object]:
    """Map retained source facts to the one public summary shape.

    Both operator persistence reads and cross-module reader projections use
    this function so source-status additions cannot diverge between list and
    single-record paths.
    """
    return {
        "sourceId": source["id"],
        "sourceKind": source["source_kind"],
        "channel": source["channel"],
        "revision": source["current_revision_id"],
        "fingerprint": fingerprint,
        "technicalStatus": source["technical_status"],
        "failureCode": source["failure_code"],
        "attentionStatus": source["attention_status"],
        "occurredAtUtc": source["occurred_at_utc"],
        "receivedAtUtc": source["received_at_utc"],
        "supersedesSourceId": source["supersedes_source_id"],
        "supersededBySourceId": source["superseded_by_source_id"],
        "provenance": {
            "originSystem": source["origin_system"],
            "accountIdentityState": source["account_identity_state"],
            "submitterKind": source["submitter_kind"],
        },
        "attachmentCount": attachment_count,
        "comparisonAvailable": source["technical_status"] == "ready",
    }
