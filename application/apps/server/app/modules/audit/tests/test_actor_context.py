"""Trusted invocation attribution is scoped, portable and transaction-bound."""

from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.domain.models import AuditEvent
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.application.service import WorkspaceService
from app.platform.actor_context import OperatorActor, current_operator_actor, operator_actor_scope
from app.platform.config import LocalConfig
from app.platform.product_migrations import ProductSchemaError, validate_latest_schema


@pytest.fixture
def ledger(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "local.json", tmp_path / "workspace"))
    manifest = workspace.initialize()
    repository = SQLiteAuditRepository(workspace.paths.database)
    return (
        workspace,
        repository,
        AuditRecorder(repository),
        OperatorActor(str(uuid4()), manifest.workspace_id),
    )


def change(recorder, connection, **kwargs):
    return recorder.record_change(
        connection,
        entity_type="probe",
        entity_id="one",
        action="created",
        before=None,
        after={"value": 1},
        **kwargs,
    )


def test_actor_scope_overrides_untrusted_attribution_and_resets_on_failure(ledger):
    workspace, repository, recorder, actor = ledger
    with closing(sqlite3.connect(workspace.paths.database)) as connection:
        with operator_actor_scope(actor):
            event = change(recorder, connection, actor_kind="connector", actor_reference="spoofed")
        connection.commit()
        assert event.actor_kind == "hosted_operator"
        assert event.actor_reference == actor.reference
        with pytest.raises(RuntimeError), operator_actor_scope(actor):
            change(recorder, connection)
            connection.rollback()
            raise RuntimeError("abort")
        assert current_operator_actor() is None
    assert repository.history("probe", "one") == [event]


def test_bulk_summary_is_attributed_and_local_mode_remains_local(ledger):
    workspace, _repository, recorder, actor = ledger
    with closing(sqlite3.connect(workspace.paths.database)) as connection:
        with operator_actor_scope(actor):
            events = recorder.record_many(
                connection,
                [
                    {
                        "entity_type": "probe",
                        "entity_id": "one",
                        "action": "created",
                        "before_snapshot": None,
                        "after_snapshot": {"value": 1},
                    }
                ],
                correlation_id=str(uuid4()),
                summary_entity_type="probe",
                summary_entity_id="batch",
            )
        assert all(
            event.actor_kind == "hosted_operator" and event.actor_reference == actor.reference
            for event in events
        )
        local = change(recorder, connection)
        assert local.actor_kind == "local_operator" and local.actor_reference is None


@pytest.mark.parametrize("reference", [None, "email@example.com", "A" * 36, str(uuid4()).upper()])
def test_hosted_actor_requires_canonical_uuid(reference):
    with pytest.raises(ValueError, match="canonical"):
        AuditEvent.change(
            entity_type="probe",
            entity_id="one",
            action="created",
            before_snapshot=None,
            after_snapshot={},
            actor_kind="hosted_operator",
            actor_reference=reference,
        )


def test_retained_validator_rejects_a_noncanonical_hosted_actor(ledger):
    workspace, _repository, _recorder, _actor = ledger
    with closing(sqlite3.connect(workspace.paths.database)) as connection:
        connection.execute(
            "INSERT INTO audit_events SELECT ?, occurred_at, entity_type, entity_id, action, "
            "before_snapshot, after_snapshot, changed_fields, reason, 'hosted_operator', ?, "
            "correlation_id, schema_version FROM audit_events LIMIT 1",
            (str(uuid4()), "x" * 36),
        )
        connection.commit()
    with pytest.raises(ProductSchemaError, match="hosted actor"):
        validate_latest_schema(workspace.paths.database)
