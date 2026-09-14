"""SQLite adapter and composition-side context implementation for COM-001."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.communications.application.ports import CommunicationContextOperations
from app.modules.communications.domain.models import Communication, CommunicationLink, CommunicationOperation, CommunicationParticipant
from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationLinkModel, CommunicationModel, CommunicationOperationModel, CommunicationParticipantModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")
LIST_SCAN_CHUNK = 200
MAX_LIST_CANDIDATES = 1_000


class SQLiteCommunicationUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder, context: CommunicationContextOperations) -> None:
        self.engine = create_sqlite_engine(database); self.recorder = recorder; self.context = context

    def write(self, operation: Callable[[Any], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(_Transaction(connection, self.recorder, self.context))

    def read(self, operation: Callable[[Any], Result]) -> Result:
        with self.engine.connect() as connection:
            return operation(_Transaction(connection, self.recorder, self.context))


class _Transaction:
    def __init__(self, connection: Any, recorder: AuditRecorder, context: CommunicationContextOperations) -> None:
        self.connection = connection; self.recorder = recorder; self.context = context
    def communication(self, item_id):
        row = self.connection.execute(select(CommunicationModel).where(CommunicationModel.id == item_id)).mappings().first()
        return Communication(**dict(row)) if row else None
    def participants(self, communication_id):
        rows = self.connection.execute(select(CommunicationParticipantModel).where(CommunicationParticipantModel.communication_id == communication_id).order_by(CommunicationParticipantModel.id)).mappings()
        return [CommunicationParticipant(**dict(row)) for row in rows]
    def links(self, communication_id):
        rows = self.connection.execute(select(CommunicationLinkModel).where(CommunicationLinkModel.communication_id == communication_id).order_by(CommunicationLinkModel.id)).mappings()
        return [CommunicationLink(**dict(row)) for row in rows]
    def insert_communication(self, item): self.connection.execute(CommunicationModel.__table__.insert().values(**item.__dict__))
    def replace_communication(self, item): self.connection.execute(CommunicationModel.__table__.update().where(CommunicationModel.id == item.id).values(**item.__dict__))
    def insert_participant(self, item): self.connection.execute(CommunicationParticipantModel.__table__.insert().values(**item.__dict__))
    def insert_link(self, item): self.connection.execute(CommunicationLinkModel.__table__.insert().values(**item.__dict__))
    def replace_link(self, item): self.connection.execute(CommunicationLinkModel.__table__.update().where(CommunicationLinkModel.id == item.id).values(**item.__dict__))
    def delete_participants(self, communication_id): self.connection.execute(CommunicationParticipantModel.__table__.delete().where(CommunicationParticipantModel.communication_id == communication_id))
    def delete_links(self, communication_id): self.connection.execute(CommunicationLinkModel.__table__.delete().where(CommunicationLinkModel.communication_id == communication_id))
    def operation(self, key):
        row = self.connection.execute(select(CommunicationOperationModel).where(CommunicationOperationModel.idempotency_key == key)).mappings().first()
        return CommunicationOperation(**dict(row)) if row else None
    def insert_operation(self, item): self.connection.execute(CommunicationOperationModel.__table__.insert().values(**item.__dict__))
    def validate_participant(self, party_id, contact_id): return self.context.participant_snapshot(self.connection, party_id, contact_id)
    def validate_link(self, entity_type, entity_id): return self.context.validate_link(self.connection, entity_type, entity_id)
    def create_follow_up(self, **kwargs): return self.context.create_follow_up(self.connection, **kwargs)
    def task_views(self, communication_id): return self.context.task_views(self.connection, communication_id)
    def list_views(self, status, direction=None, channel=None, party_id=None, entity_type=None, entity_id=None, limit=100, cursor=None, occurred_on_or_after=None, occurred_on_or_before=None, task_status=None):
        query = select(CommunicationModel).order_by(CommunicationModel.occurred_at_utc.desc(), CommunicationModel.id.desc())
        if status: query = query.where(CommunicationModel.status == status)
        if direction: query = query.where(CommunicationModel.direction == direction)
        if channel: query = query.where(CommunicationModel.channel == channel)
        if party_id:
            query = query.where(CommunicationModel.id.in_(select(CommunicationParticipantModel.communication_id).where(CommunicationParticipantModel.party_id == party_id)))
        if entity_type and entity_id:
            query = query.where(CommunicationModel.id.in_(select(CommunicationLinkModel.communication_id).where(CommunicationLinkModel.entity_type == entity_type, CommunicationLinkModel.entity_id == entity_id)))
        if cursor:
            occurred, item_id = cursor
            query = query.where((CommunicationModel.occurred_at_utc < occurred) | ((CommunicationModel.occurred_at_utc == occurred) & (CommunicationModel.id < item_id)))
        # Local-date conversion needs IANA-zone rules that SQLite does not provide.
        # Scan ordered database chunks and return a cursor for the last scanned
        # record whenever a selective filter has not yet filled the page.
        output: list[dict[str, object]] = []
        scan_cursor = cursor
        scanned = 0
        while True:
            chunk_query = query
            if scan_cursor:
                occurred, item_id = scan_cursor
                chunk_query = chunk_query.where(
                    (CommunicationModel.occurred_at_utc < occurred)
                    | ((CommunicationModel.occurred_at_utc == occurred) & (CommunicationModel.id < item_id))
                )
            rows = list(self.connection.execute(chunk_query.limit(LIST_SCAN_CHUNK)).mappings())
            if not rows:
                return output, None
            scanned += len(rows)
            matching_ids = (
                self.context.matching_communication_ids_for_task_status(
                    self.connection, {row["id"] for row in rows}, task_status,
                )
                if task_status else None
            )
            for row in rows:
                scan_cursor = (row["occurred_at_utc"], row["id"])
                if matching_ids is not None and row["id"] not in matching_ids:
                    continue
                local_date = datetime.fromisoformat(row["occurred_at_utc"].replace("Z", "+00:00")).astimezone(ZoneInfo(row["occurred_timezone"])).date().isoformat()
                if occurred_on_or_after and local_date < occurred_on_or_after:
                    continue
                if occurred_on_or_before and local_date > occurred_on_or_before:
                    continue
                output.append({**Communication(**dict(row)).to_dict(), "participants": [item.to_dict() for item in self.participants(row["id"])], "links": [item.to_dict() for item in self.links(row["id"])], "followUpTasks": self.task_views(row["id"])})
                if len(output) >= limit:
                    return output, scan_cursor
            if scanned >= MAX_LIST_CANDIDATES:
                return output, scan_cursor
            if len(rows) < LIST_SCAN_CHUNK:
                return output, None
    def record_change(self, **kwargs): self.recorder.record_change(self.connection.connection.driver_connection, **kwargs)
