"""Composition-only COM-001 context adapters over owning module persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.communications.domain.models import Communication
from app.modules.finance.infrastructure.sqlalchemy_models import RentExpectationModel, RentReceiptModel
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseRenewalOptionModel
from app.modules.parties.infrastructure.sqlalchemy_models import PartyContactMethodModel, PartyModel
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.modules.tasks.application.ports import TaskTransactionOperations
from app.modules.tasks.application.service import TaskCreateCommand, new_task
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel


class SQLiteCommunicationContextOperations:
    def __init__(self, task_operations: TaskTransactionOperations) -> None:
        self.task_operations = task_operations

    def participant_snapshot(self, connection: Any, party_id: str, contact_method_id: str | None) -> tuple[str, str | None]:
        party = connection.execute(PartyModel.__table__.select().where(PartyModel.id == party_id)).mappings().first()
        if party is None or party["archived_at"] is not None:
            raise ValueError("Participant party must be active.")
        if contact_method_id is None:
            return party["display_name"], None
        method = connection.execute(PartyContactMethodModel.__table__.select().where(PartyContactMethodModel.id == contact_method_id)).mappings().first()
        if method is None or method["party_id"] != party["id"] or method["status"] != "active":
            raise ValueError("Participant contact method must be active and belong to the party.")
        return party["display_name"], method["display_value"]

    def validate_retained_participant(self, connection: Any, party_id: str, contact_method_id: str | None) -> None:
        """Validate durable ownership without rewriting historical archived participants."""
        party = connection.execute(select(PartyModel.id).where(PartyModel.id == party_id)).scalar_one_or_none()
        if party is None:
            raise KeyError("Communication participant party was not found.")
        if contact_method_id is None:
            return
        method_party = connection.execute(select(PartyContactMethodModel.party_id).where(
            PartyContactMethodModel.id == contact_method_id,
        )).scalar_one_or_none()
        if method_party != party_id:
            raise ValueError("Communication participant contact method does not belong to its party.")

    def validate_link(self, connection: Any, entity_type: str, entity_id: str) -> str | None:
        if entity_type == "party":
            if connection.execute(select(PartyModel.id).where(PartyModel.id == entity_id)).scalar_one_or_none() is None:
                raise KeyError("Linked party was not found.")
            return None
        if entity_type == "property":
            return _property_zone(connection, entity_id)
        if entity_type == "space":
            return _one_zone(connection, select(PropertyModel.time_zone).join(SpaceModel).where(SpaceModel.id == entity_id), "space")
        if entity_type == "lease":
            return _one_zone(connection, select(PropertyModel.time_zone).join(SpaceModel).join(LeaseModel).where(LeaseModel.id == entity_id), "lease")
        if entity_type == "rent_expectation":
            return _one_zone(connection, select(PropertyModel.time_zone).join(SpaceModel).join(LeaseModel).join(RentExpectationModel).where(RentExpectationModel.id == entity_id), "rent expectation")
        if entity_type == "rent_receipt":
            if connection.execute(select(RentReceiptModel.id).where(RentReceiptModel.id == entity_id)).scalar_one_or_none() is None:
                raise KeyError("Linked rent receipt was not found.")
            return None
        if entity_type == "renewal_option":
            return _one_zone(connection, select(PropertyModel.time_zone).join(SpaceModel).join(LeaseModel).join(LeaseRenewalOptionModel).where(LeaseRenewalOptionModel.id == entity_id), "renewal option")
        if entity_type == "task":
            if connection.execute(select(TaskModel.id).where(TaskModel.id == entity_id)).scalar_one_or_none() is None:
                raise KeyError("Linked task was not found.")
            return None
        raise ValueError("Communication link type is unsupported.")

    def create_follow_up(self, connection: Any, *, communication: Communication, title: str, notes: str | None,
                         due_at_utc: str | None, due_timezone: str | None, correlation_id: str) -> dict[str, object]:
        task = new_task(TaskCreateCommand(
            title=title, notes=notes, status="open", priority="normal",
            due_at_utc=due_at_utc, due_timezone=due_timezone, is_all_day=False,
            related_entity_type="communication", related_entity_id=communication.id,
            related_label=communication.subject,
        ))
        self.task_operations.insert_task(connection, task)
        return task.to_dict()

    def task_views(self, connection: Any, communication_id: str) -> list[dict[str, object]]:
        rows = connection.execute(TaskModel.__table__.select().where(
            TaskModel.related_entity_type == "communication", TaskModel.related_entity_id == communication_id,
        ).order_by(TaskModel.created_at_utc)).mappings()
        return [{"id": row["id"], "status": row["status"], "title": row["title"], "dueAtUtc": row["due_at_utc"], "dueTimezone": row["due_timezone"]} for row in rows]

    def matching_communication_ids_for_task_status(
        self,
        connection: Any,
        communication_ids: set[str],
        status: str,
    ) -> set[str]:
        if not communication_ids:
            return set()
        return set(connection.execute(select(TaskModel.related_entity_id).where(
            TaskModel.related_entity_type == "communication",
            TaskModel.status == status,
            TaskModel.related_entity_id.in_(communication_ids),
        )).scalars())

    def validate_follow_up_task(self, connection: Any, communication_id: str, task_id: str) -> None:
        row = connection.execute(select(TaskModel.related_entity_type, TaskModel.related_entity_id).where(
            TaskModel.id == task_id,
        )).first()
        if row != ("communication", communication_id):
            raise ValueError("Communication follow-up task reference is invalid.")

    def validate_communication_task_references(self, connection: Any, communication_ids: set[str]) -> None:
        rows = connection.execute(select(TaskModel.related_entity_id).where(
            TaskModel.related_entity_type == "communication",
        )).scalars()
        if any(item_id not in communication_ids for item_id in rows):
            raise ValueError("Communication follow-up task points to a missing communication.")


def _property_zone(connection: Any, property_id: str) -> str:
    result = connection.execute(select(PropertyModel.time_zone).where(PropertyModel.id == property_id)).scalar_one_or_none()
    if result is None:
        raise KeyError("Linked property was not found.")
    return result


def _one_zone(connection: Any, query, label: str) -> str:
    result = connection.execute(query).scalar_one_or_none()
    if result is None:
        raise KeyError(f"Linked {label} was not found.")
    return result
