"""One bounded immutable receipt projection for presentation and retained validation."""

from app.platform.command_recovery import CommandOutcome


def receipt_projection(outcome: CommandOutcome, result_kind: str, key: str):
    return {
        "sourceKind": result_kind,
        "sourceId": outcome.source_id,
        "receiptId": outcome.operation_id,
        "attemptKey": key,
        "result": {
            "targetId": outcome.result.target_id,
            "revision": outcome.result.revision,
            "status": outcome.result.status,
            "operationId": outcome.operation_id,
            **(
                {"fileId": outcome.result.file_id, "linkId": outcome.result.link_id}
                if outcome.result.file_id is not None
                else {}
            ),
            **(
                {"evidenceRevisionId": outcome.result.evidence_revision_id}
                if outcome.result.evidence_revision_id is not None
                else {}
            ),
        },
    }
