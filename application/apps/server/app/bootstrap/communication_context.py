"""Composition-only COM-001 context adapters over owning module persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.communications.domain.models import Communication
from app.modules.communications.application.service import FollowUpInput
from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentExpectationModel,
    RentReceiptModel,
)
from app.modules.intake.application.ports import IntakeSourceReader
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseRenewalOptionModel
from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceIssueModel
from app.modules.owner_management.infrastructure.sqlalchemy_models import OwnerConcernModel
from app.modules.parties.infrastructure.sqlalchemy_models import PartyContactMethodModel, PartyModel
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.modules.tasks.application.ports import TaskTransactionOperations
from app.modules.tasks.application.service import TaskCreateCommand, new_task
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel


class SQLiteCommunicationContextOperations:
    def __init__(
        self,
        task_operations: TaskTransactionOperations,
        intake_sources: IntakeSourceReader,
    ) -> None:
        self.task_operations = task_operations
        self.intake_sources = intake_sources

    def participant_snapshot(
        self, connection: Any, party_id: str, contact_method_id: str | None
    ) -> tuple[str, str | None]:
        party = (
            connection.execute(PartyModel.__table__.select().where(PartyModel.id == party_id))
            .mappings()
            .first()
        )
        if party is None or party["archived_at"] is not None:
            raise ValueError("Participant party must be active.")
        if contact_method_id is None:
            return party["display_name"], None
        method = (
            connection.execute(
                PartyContactMethodModel.__table__.select().where(
                    PartyContactMethodModel.id == contact_method_id
                )
            )
            .mappings()
            .first()
        )
        if method is None or method["party_id"] != party["id"] or method["status"] != "active":
            raise ValueError("Participant contact method must be active and belong to the party.")
        return party["display_name"], method["display_value"]

    def validate_retained_participant(
        self, connection: Any, party_id: str, contact_method_id: str | None
    ) -> None:
        """Validate durable ownership without rewriting historical archived participants."""
        party = connection.execute(
            select(PartyModel.id).where(PartyModel.id == party_id)
        ).scalar_one_or_none()
        if party is None:
            raise KeyError("Communication participant party was not found.")
        if contact_method_id is None:
            return
        method_party = connection.execute(
            select(PartyContactMethodModel.party_id).where(
                PartyContactMethodModel.id == contact_method_id,
            )
        ).scalar_one_or_none()
        if method_party != party_id:
            raise ValueError(
                "Communication participant contact method does not belong to its party."
            )

    def validate_link(self, connection: Any, entity_type: str, entity_id: str) -> str | None:
        validators = {
            "party": lambda: _existing_link(connection, PartyModel.id, entity_id, "party"),
            "property": lambda: _property_zone(connection, entity_id),
            "space": lambda: _one_zone(
                connection,
                select(PropertyModel.time_zone).join(SpaceModel).where(SpaceModel.id == entity_id),
                "space",
            ),
            "lease": lambda: _one_zone(
                connection,
                select(PropertyModel.time_zone)
                .join(SpaceModel)
                .join(LeaseModel)
                .where(LeaseModel.id == entity_id),
                "lease",
            ),
            "rent_expectation": lambda: _one_zone(
                connection,
                select(PropertyModel.time_zone)
                .join(SpaceModel)
                .join(LeaseModel)
                .join(RentExpectationModel)
                .where(RentExpectationModel.id == entity_id),
                "rent expectation",
            ),
            "rent_receipt": lambda: _existing_link(
                connection, RentReceiptModel.id, entity_id, "rent receipt"
            ),
            "renewal_option": lambda: _one_zone(
                connection,
                select(PropertyModel.time_zone)
                .join(SpaceModel)
                .join(LeaseModel)
                .join(LeaseRenewalOptionModel)
                .where(LeaseRenewalOptionModel.id == entity_id),
                "renewal option",
            ),
            "task": lambda: _existing_link(connection, TaskModel.id, entity_id, "task"),
            "maintenance_issue": lambda: _one_zone(
                connection,
                select(MaintenanceIssueModel.reported_timezone).where(
                    MaintenanceIssueModel.id == entity_id
                ),
                "maintenance issue",
            ),
            "owner_concern": lambda: _one_zone(
                connection,
                select(OwnerConcernModel.property_timezone_snapshot).where(
                    OwnerConcernModel.id == entity_id
                ),
                "owner concern",
            ),
            "intake_source": lambda: self._validate_intake_link(connection, entity_id),
        }
        validator = validators.get(entity_type)
        if validator is None:
            raise ValueError("Communication link type is unsupported.")
        return validator()

    def _validate_intake_link(self, connection: Any, entity_id: str) -> None:
        source = self.intake_sources.source_state(connection, entity_id)
        if (
            source is None
            or source["technical_status"] != "ready"
            or source["superseded_by_source_id"] is not None
        ):
            raise KeyError("Linked intake source was not found or is not ready.")

    def validate_retained_link(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> str | None:
        """Historical links retain their original target instead of following
        mutable source lifecycle state (notably intake supersession)."""
        if entity_type == "intake_source":
            if self.intake_sources.source_state(connection, entity_id) is None:
                raise KeyError("Linked intake source was not found.")
            return None
        return self.validate_link(connection, entity_type, entity_id)

    def link_context(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> dict[str, object] | None:
        """Mutable context is a read projection only; the stored COM link is immutable."""
        if entity_type != "intake_source":
            return None
        row = self.intake_sources.source_state(connection, entity_id)
        if row is None:
            return {"targetExists": False}
        return {
            "targetExists": True,
            "technicalStatus": row["technical_status"],
            "currentRevision": row["current_revision_id"],
            "supersededBySourceId": row["superseded_by_source_id"],
            "isCurrent": row["technical_status"] == "ready"
            and row["superseded_by_source_id"] is None,
        }

    def create_follow_up(
        self,
        connection: Any,
        *,
        communication: Communication,
        follow_up: FollowUpInput,
    ) -> dict[str, object]:
        task = new_task(
            TaskCreateCommand(
                title=follow_up.title,
                notes=follow_up.notes,
                status="open",
                priority="normal",
                due_at_utc=follow_up.due_at_utc,
                due_timezone=follow_up.due_timezone,
                is_all_day=False,
                related_entity_type="communication",
                related_entity_id=communication.id,
                related_label=communication.subject,
            )
        )
        self.task_operations.insert_task(connection, task)
        return task.to_dict()

    def task_views(self, connection: Any, communication_id: str) -> list[dict[str, object]]:
        rows = connection.execute(
            TaskModel.__table__.select()
            .where(
                TaskModel.related_entity_type == "communication",
                TaskModel.related_entity_id == communication_id,
            )
            .order_by(TaskModel.created_at_utc)
        ).mappings()
        return [
            {
                "id": row["id"],
                "status": row["status"],
                "title": row["title"],
                "dueAtUtc": row["due_at_utc"],
                "dueTimezone": row["due_timezone"],
            }
            for row in rows
        ]

    def matching_communication_ids_for_task_status(
        self,
        connection: Any,
        communication_ids: set[str],
        status: str,
    ) -> set[str]:
        if not communication_ids:
            return set()
        return set(
            connection.execute(
                select(TaskModel.related_entity_id).where(
                    TaskModel.related_entity_type == "communication",
                    TaskModel.status == status,
                    TaskModel.related_entity_id.in_(communication_ids),
                )
            ).scalars()
        )

    def validate_follow_up_task(self, connection: Any, communication_id: str, task_id: str) -> None:
        row = connection.execute(
            select(TaskModel.related_entity_type, TaskModel.related_entity_id).where(
                TaskModel.id == task_id,
            )
        ).first()
        if row != ("communication", communication_id):
            raise ValueError("Communication follow-up task reference is invalid.")

    def validate_communication_task_references(
        self, connection: Any, communication_ids: set[str]
    ) -> None:
        rows = connection.execute(
            select(TaskModel.related_entity_id).where(
                TaskModel.related_entity_type == "communication",
            )
        ).scalars()
        if any(item_id not in communication_ids for item_id in rows):
            raise ValueError("Communication follow-up task points to a missing communication.")


def _property_zone(connection: Any, property_id: str) -> str:
    result = connection.execute(
        select(PropertyModel.time_zone).where(PropertyModel.id == property_id)
    ).scalar_one_or_none()
    if result is None:
        raise KeyError("Linked property was not found.")
    return result


def _existing_link(connection: Any, entity_id_column: Any, entity_id: str, label: str) -> None:
    query = select(entity_id_column).where(entity_id_column == entity_id)
    if connection.execute(query).scalar_one_or_none() is None:
        raise KeyError(f"Linked {label} was not found.")


def _one_zone(connection: Any, query, label: str) -> str:
    result = connection.execute(query).scalar_one_or_none()
    if result is None:
        raise KeyError(f"Linked {label} was not found.")
    return result
