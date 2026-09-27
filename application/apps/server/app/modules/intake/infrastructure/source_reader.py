"""Consumer-neutral transaction-aware projection of retained evidence."""
from __future__ import annotations
from typing import Any
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeTransaction


class SQLiteIntakeSourceReader:
    def source_projection(self, connection: Any, source_id: str) -> dict[str, object] | None:
        # No new connection: AI-GOV and later review workflows compare an
        # opaque source revision inside their caller-owned transaction.
        return SQLiteIntakeTransaction(connection, _NoAudit()).source_projection(source_id)


class _NoAudit:
    def record_change(self, *args, **kwargs): raise RuntimeError("Reader cannot record audit events.")
