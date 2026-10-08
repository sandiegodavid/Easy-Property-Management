"""One bounded immutable receipt projection for presentation and retained validation."""

from app.platform.command_recovery import CommandOutcome


def receipt_projection(outcome: CommandOutcome, source_kind: str | None, key: str):
    return {
        "sourceKind": source_kind or "communication",
        "sourceId": outcome.source_id,
        "receiptId": outcome.operation_id,
        "attemptKey": key,
        "result": {
            "targetId": outcome.result.target_id,
            "revision": outcome.result.revision,
            "status": outcome.result.status,
            "operationId": outcome.operation_id,
        },
    }
