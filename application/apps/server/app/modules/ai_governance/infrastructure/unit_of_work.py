"""Transaction-aware persistence for AI governance records."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Mapping, TypeVar
from uuid import uuid4

from sqlalchemy import and_, func, select
from app.modules.ai_governance.application.commands import (
    record_command,
    replay_command,
    require_revision,
)
from app.modules.ai_governance.domain.models import (
    AiConflictError,
    AiNotFoundError,
    AiValidationError,
)

from app.modules.ai_governance.infrastructure.sqlalchemy_models import (
    AiActionLimitModel,
    AiCommandOperationModel,
    AiDraftModel,
    AiExternalOperationModel,
    AiModelConnectionModel,
    AiReviewDecisionModel,
    AiRunModel,
    AiSettingsModel,
)
from app.modules.audit.application.recorder import AuditRecorder
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteAiGovernanceUnitOfWork:
    def __init__(
        self, database, recorder: AuditRecorder, source_validators: Mapping[str, Any] | None = None
    ) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.source_validators = dict(source_validators or {})

    def write(self, operation: Callable[["AiGovernanceTransaction"], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(
                AiGovernanceTransaction(connection, self.recorder, self.source_validators)
            )

    def read(self, operation: Callable[[Any], Result]) -> Result:
        with self.engine.connect() as connection:
            with connection.begin():
                return operation(connection)

    def settings_row(self):
        return self.read(
            lambda c: dict(
                c.execute(AiSettingsModel.__table__.select().where(AiSettingsModel.singleton == 1))
                .mappings()
                .one()
            )
        )

    def command_row(self, *, operation_id=None, key=None):
        predicate = (
            AiCommandOperationModel.id == operation_id
            if operation_id is not None
            else AiCommandOperationModel.idempotency_key == key
        )
        return self.read(
            lambda c: _mapping(
                c.execute(AiCommandOperationModel.__table__.select().where(predicate))
            )
        )

    def connection_row(self, connection_id: str):
        return self.read(
            lambda c: _mapping(
                c.execute(
                    AiModelConnectionModel.__table__.select().where(
                        AiModelConnectionModel.id == connection_id
                    )
                )
            )
        )

    def external_row(self, *, operation_id=None, key=None):
        predicate = (
            AiExternalOperationModel.id == operation_id
            if operation_id is not None
            else AiExternalOperationModel.idempotency_key == key
        )
        return self.read(
            lambda c: _mapping(
                c.execute(AiExternalOperationModel.__table__.select().where(predicate))
            )
        )

    def connection_rows(self):
        return self.read(
            lambda c: [
                dict(row)
                for row in c.execute(
                    AiModelConnectionModel.__table__.select().order_by(
                        AiModelConnectionModel.label, AiModelConnectionModel.id
                    )
                ).mappings()
            ]
        )

    def action_limit_row(self, action_type: str):
        return self.read(
            lambda c: _mapping(
                c.execute(
                    AiActionLimitModel.__table__.select().where(
                        AiActionLimitModel.action_type == action_type
                    )
                )
            )
        )

    def action_limit_rows(self):
        return self.read(
            lambda c: [
                dict(row)
                for row in c.execute(
                    AiActionLimitModel.__table__.select().order_by(AiActionLimitModel.action_type)
                ).mappings()
            ]
        )

    def run_row(self, run_id: str):
        return self.read(
            lambda c: _mapping(
                c.execute(AiRunModel.__table__.select().where(AiRunModel.id == run_id))
            )
        )

    def page_draft_rows(self, **filters):
        return self.read(lambda c: AiGovernanceTransaction(c, self.recorder).page_drafts(**filters))

    def draft_detail_row(self, draft_id: str):
        def operation(connection):
            query = (
                select(
                    *AiDraftModel.__table__.c,
                    AiRunModel.action_type,
                    AiRunModel.owning_module,
                    AiRunModel.source_entity_type,
                    AiRunModel.source_entity_id,
                    AiRunModel.source_revision,
                    AiRunModel.source_fingerprint,
                    AiRunModel.governed_input_json,
                    AiRunModel.execution_kind,
                    AiRunModel.transport_provider,
                    AiRunModel.adapter_version,
                    AiRunModel.model_identifier,
                    AiRunModel.execution_location,
                    AiRunModel.model_artifact_digest,
                    AiRunModel.quantization,
                    AiRunModel.runtime_id,
                    AiRunModel.runtime_version,
                    AiRunModel.prompt_template_id,
                    AiRunModel.prompt_template_version,
                    AiRunModel.output_schema_version,
                    AiRunModel.redaction_profile,
                    AiRunModel.redaction_profile_version,
                    AiRunModel.prompt_tokens,
                    AiRunModel.completion_tokens,
                    AiRunModel.correlation_id,
                    AiRunModel.status.label("run_status"),
                    AiRunModel.id.label("run_id_value"),
                )
                .join(AiRunModel, AiDraftModel.run_id == AiRunModel.id)
                .where(AiDraftModel.id == draft_id)
            )
            return _mapping(connection.execute(query))

        return self.read(operation)

    def draft_decision_rows(self, draft_id: str):
        return self.read(
            lambda c: [
                dict(row)
                for row in c.execute(
                    AiReviewDecisionModel.__table__.select()
                    .where(AiReviewDecisionModel.draft_id == draft_id)
                    .order_by(
                        AiReviewDecisionModel.draft_version_before,
                        AiReviewDecisionModel.decided_at,
                        AiReviewDecisionModel.id,
                    )
                ).mappings()
            ]
        )

    def approval_context_row(self, draft_id: str):
        def operation(connection):
            query = (
                select(
                    *AiDraftModel.__table__.c,
                    AiRunModel.action_type,
                    AiRunModel.owning_module,
                    AiRunModel.source_entity_type,
                    AiRunModel.source_entity_id,
                    AiRunModel.source_revision,
                    AiRunModel.source_fingerprint,
                    AiRunModel.correlation_id,
                )
                .join(AiRunModel, AiDraftModel.run_id == AiRunModel.id)
                .where(AiDraftModel.id == draft_id)
            )
            return _mapping(connection.execute(query))

        return self.read(operation)


class AiGovernanceTransaction:
    def __init__(
        self,
        connection: Any,
        recorder: AuditRecorder,
        source_validators: Mapping[str, Any] | None = None,
    ) -> None:
        self.connection = connection
        self.recorder = recorder
        self.source_validators = dict(source_validators or {})

    def external_by_key(self, key):
        return _mapping(
            self.connection.execute(
                AiExternalOperationModel.__table__.select().where(
                    AiExternalOperationModel.idempotency_key == key
                )
            )
        )

    def external_operation(self, operation_id):
        return _mapping(
            self.connection.execute(
                AiExternalOperationModel.__table__.select().where(
                    AiExternalOperationModel.id == operation_id
                )
            )
        )

    def pending_external(self, connection_id):
        return (
            self.connection.execute(
                select(AiExternalOperationModel.id)
                .where(
                    AiExternalOperationModel.connection_id == connection_id,
                    AiExternalOperationModel.result_json.is_(None),
                )
                .limit(1)
            ).first()
            is not None
        )

    def insert_external(self, row):
        self.connection.execute(AiExternalOperationModel.__table__.insert().values(**row))

    def complete_external(self, operation_id, result_json, stamp):
        self.connection.execute(
            AiExternalOperationModel.__table__.update()
            .where(AiExternalOperationModel.id == operation_id)
            .values(result_json=result_json, completed_at=stamp)
        )

    def settings(self) -> dict[str, Any]:
        row = self.connection.execute(select(AiSettingsModel)).mappings().first()
        if row is None:
            stamp = datetime.now(UTC).isoformat()
            self.connection.execute(
                AiSettingsModel.__table__.insert().values(
                    singleton=1,
                    kill_switch=False,
                    built_in_enabled=False,
                    default_connection_id=None,
                    updated_at=stamp,
                )
            )
            return {
                "singleton": 1,
                "kill_switch": False,
                "built_in_enabled": False,
                "default_connection_id": None,
                "updated_at": stamp,
                "revision": 1,
            }
        return dict(row)

    def command_by_key(self, key):
        return _mapping(
            self.connection.execute(
                AiCommandOperationModel.__table__.select().where(
                    AiCommandOperationModel.idempotency_key == key
                )
            )
        )

    def insert_command(self, values):
        self.connection.execute(AiCommandOperationModel.__table__.insert().values(**values))

    def update_settings(self, values: dict[str, Any]) -> None:
        self.connection.execute(
            AiSettingsModel.__table__.update()
            .where(AiSettingsModel.singleton == 1)
            .values(**values)
        )

    def model_connection(self, connection_id: str) -> dict[str, Any] | None:
        row = (
            self.connection.execute(
                AiModelConnectionModel.__table__.select().where(
                    AiModelConnectionModel.id == connection_id
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def connections(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                AiModelConnectionModel.__table__.select().order_by(
                    AiModelConnectionModel.label, AiModelConnectionModel.id
                )
            ).mappings()
        ]

    def insert_connection(self, values: dict[str, Any]) -> None:
        self.connection.execute(AiModelConnectionModel.__table__.insert().values(**values))

    def replace_connection(self, connection_id: str, values: dict[str, Any]) -> None:
        self.connection.execute(
            AiModelConnectionModel.__table__.update()
            .where(AiModelConnectionModel.id == connection_id)
            .values(**values)
        )

    def action_limit(self, action_type: str) -> dict[str, Any] | None:
        row = (
            self.connection.execute(
                AiActionLimitModel.__table__.select().where(
                    AiActionLimitModel.action_type == action_type
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def action_limits(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                AiActionLimitModel.__table__.select().order_by(AiActionLimitModel.action_type)
            ).mappings()
        ]

    def put_action_limit(self, values: dict[str, Any]) -> None:
        self.connection.execute(
            AiActionLimitModel.__table__.insert().values(**values).prefix_with("OR REPLACE")
        )

    def run_by_key(self, key: str) -> dict[str, Any] | None:
        row = (
            self.connection.execute(
                AiRunModel.__table__.select().where(AiRunModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def validate_current_source(
        self,
        *,
        source_entity_type: str,
        source_entity_id: str,
        source_revision: str,
        source_fingerprint: str,
    ) -> None:
        validator = self.source_validators.get(source_entity_type)
        if validator is None:
            raise ValueError("AI source validation is unavailable.")
        validator.validate_current_source(
            self.connection,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            source_revision=source_revision,
            source_fingerprint=source_fingerprint,
        )

    def run(self, run_id: str) -> dict[str, Any] | None:
        row = (
            self.connection.execute(AiRunModel.__table__.select().where(AiRunModel.id == run_id))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def insert_run(self, values: dict[str, Any]) -> None:
        self.connection.execute(AiRunModel.__table__.insert().values(**values))

    def update_run(self, run_id: str, values: dict[str, Any]) -> None:
        self.connection.execute(
            AiRunModel.__table__.update().where(AiRunModel.id == run_id).values(**values)
        )

    def active_run_count(self, action_type: str, day_start: str, day_end: str) -> int:
        # A reservation is a durable quota slot.  Counting it closes the gap
        # between reservation and dispatch under the single SQLite writer.
        return int(
            self.connection.scalar(
                select(func.count())
                .select_from(AiRunModel)
                .where(
                    and_(
                        AiRunModel.action_type == action_type,
                        AiRunModel.created_at >= day_start,
                        AiRunModel.created_at < day_end,
                        ((AiRunModel.status == "reserved") | (AiRunModel.started_at.is_not(None))),
                    )
                )
            )
            or 0
        )

    def draft(self, draft_id: str) -> dict[str, Any] | None:
        row = (
            self.connection.execute(
                AiDraftModel.__table__.select().where(AiDraftModel.id == draft_id)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def draft_for_run(self, run_id: str) -> dict[str, Any] | None:
        row = (
            self.connection.execute(
                AiDraftModel.__table__.select().where(AiDraftModel.run_id == run_id)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def insert_draft(self, values: dict[str, Any]) -> None:
        self.connection.execute(AiDraftModel.__table__.insert().values(**values))

    def update_draft(self, draft_id: str, values: dict[str, Any]) -> None:
        self.connection.execute(
            AiDraftModel.__table__.update().where(AiDraftModel.id == draft_id).values(**values)
        )

    def decisions(self, draft_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                AiReviewDecisionModel.__table__.select()
                .where(AiReviewDecisionModel.draft_id == draft_id)
                .order_by(
                    AiReviewDecisionModel.draft_version_before,
                    AiReviewDecisionModel.decided_at,
                    AiReviewDecisionModel.id,
                )
            ).mappings()
        ]

    def insert_decision(self, values: dict[str, Any]) -> None:
        self.connection.execute(AiReviewDecisionModel.__table__.insert().values(**values))

    def record_audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        correlation_id: str,
        actor: str,
        reason: str,
        event_id: str | None = None,
    ) -> None:
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            actor_kind=actor,
            reason=reason,
            correlation_id=correlation_id,
            event_id=event_id,
        )

    def review_operations(self) -> "SQLiteAiReviewOperations":
        return SQLiteAiReviewOperations(self)

    def complete_approval(
        self,
        *,
        draft_id: str,
        expected_version: int,
        result_entity_type: str | None,
        result_entity_id: str | None,
        operator_note: str | None,
        command,
    ) -> dict[str, Any]:
        """Low-level atomic terminal write; policy remains in the service."""
        if (
            command.action != "approved"
            or command.target_id != draft_id
            or command.expected_revision != expected_version
            or json.loads(command.request_json)["payload"] != {"operatorNote": operator_note}
        ):
            raise AiValidationError("Approval command does not match its completion.")
        draft = self.draft(draft_id)
        if (
            draft is None
            or draft["status"] not in {"proposed", "edited"}
            or draft["version"] != expected_version
        ):
            raise AiConflictError("ai_draft_version_conflict")
        stamp = datetime.now(UTC).isoformat()
        self.update_draft(
            draft_id, {"status": "approved", "terminal_at": stamp, "updated_at": stamp}
        )
        run = self.run(draft["run_id"])
        record = {
            "id": str(uuid4()),
            "draft_id": draft_id,
            "decision": "approved",
            "draft_version_before": expected_version,
            "draft_version_after": expected_version,
            "operator_note": operator_note,
            "result_entity_type": result_entity_type,
            "result_entity_id": result_entity_id,
            "correlation_id": run["correlation_id"],
            "decided_at": stamp,
        }
        self.insert_decision(record)
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type="ai_draft",
            entity_id=draft_id,
            action="approved",
            before=draft,
            after={**draft, "status": "approved", "terminal_at": stamp, "updated_at": stamp},
            reason="ai_approved",
            correlation_id=run["correlation_id"],
            event_id=command.operation_id,
        )
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type="ai_review_decision",
            entity_id=record["id"],
            action="approved",
            before=None,
            after=record,
            reason="ai_approved",
            correlation_id=run["correlation_id"],
        )
        return record_command(
            self,
            command,
            {
                "status": "approved",
                "resultEntityId": result_entity_id,
                "resultEntityType": result_entity_type,
                "draftId": draft_id,
                "version": expected_version,
                "updatedAt": stamp,
            },
            stamp,
        )

    def interrupted_runs(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                AiRunModel.__table__.select().where(AiRunModel.status.in_(("reserved", "running")))
            ).mappings()
        ]

    def page_drafts(
        self,
        *,
        status: str | None,
        owning_module: str | None,
        entity_kind: str | None,
        action_type: str | None,
        source_type: str | None,
        source_id: str | None,
        limit: int,
        cursor: tuple[str, str] | None,
    ) -> list[dict[str, Any]]:
        query = select(
            *AiDraftModel.__table__.c,
            AiRunModel.action_type,
            AiRunModel.owning_module,
            AiRunModel.source_entity_type,
            AiRunModel.source_entity_id,
            AiRunModel.source_revision,
            AiRunModel.status.label("run_status"),
        ).join(AiRunModel, AiDraftModel.run_id == AiRunModel.id)
        if status:
            query = query.where(AiDraftModel.status == status)
        if owning_module:
            query = query.where(AiRunModel.owning_module == owning_module)
        if entity_kind:
            query = query.where(AiDraftModel.entity_kind == entity_kind)
        if action_type:
            query = query.where(AiRunModel.action_type == action_type)
        if source_type is not None:
            query = query.where(
                AiRunModel.source_entity_type == source_type,
                AiRunModel.source_entity_id == source_id,
            )
        if cursor:
            query = query.where(
                (AiDraftModel.updated_at < cursor[0])
                | ((AiDraftModel.updated_at == cursor[0]) & (AiDraftModel.id < cursor[1]))
            )
        return [
            dict(row)
            for row in self.connection.execute(
                query.order_by(AiDraftModel.updated_at.desc(), AiDraftModel.id.desc()).limit(limit)
            ).mappings()
        ]


class SQLiteAiReviewOperations:
    """Narrow application adapter injected into an owning domain's UoW."""

    def __init__(self, transaction: AiGovernanceTransaction) -> None:
        self._transaction = transaction

    def draft(self, draft_id: str) -> dict[str, Any] | None:
        return self._transaction.draft(draft_id)

    def approval_replay(self, context):
        prior = replay_command(self._transaction, context.command)
        if prior is not None:
            return prior
        draft = self.draft(context.draft_id)
        if draft is None:
            raise AiNotFoundError("AI draft was not found.")
        require_revision(
            context.command,
            draft["version"],
            {"id": draft["id"], "version": draft["version"], "status": draft["status"]},
        )
        if draft["status"] not in {"proposed", "edited"}:
            raise AiConflictError("ai_draft_terminal")
        return None

    def complete_approval(self, **kwargs: Any) -> dict[str, Any]:
        return self._transaction.complete_approval(**kwargs)


def _mapping(result):
    row = result.mappings().first()
    return None if row is None else dict(row)
