"""Explicit OPS composition without initializing or opening the workspace."""

from app.bootstrap.operator_recovery import OperatorRecoveryReferences
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.communications.infrastructure.receipt_reader import (
    SQLiteCommunicationReceiptReader,
)
from app.modules.maintenance.infrastructure.receipt_reader import SQLiteIssueCommandReceiptReader
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork


def compose_operator(workspace, runtime, recorder, sources):
    def identity():
        state = "ready" if runtime.ready else "unavailable"
        if runtime.startup_attempted and not runtime.writer_lock_acquired:
            state = "busy"
        return RuntimeIdentity(
            state,
            runtime.workspace_id if runtime.ready else None,
            runtime.read_epoch,
            runtime.ready and runtime.can_write,
            None if runtime.ready else "workspace_" + state,
        )

    references = OperatorRecoveryReferences(
        sources.portfolio,
        sources.parties,
        sources.contexts,
        SQLiteIssueCommandReceiptReader(),
        SQLiteCommunicationReceiptReader(),
    )
    return OperatorService(
        SQLiteOperatorUnitOfWork(
            workspace.paths.database, recorder, references, SQLiteAuditReadMarker()
        ),
        runtime=identity,
        capabilities=("operator.preferences", "operator.recovery"),
    )
