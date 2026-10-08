"""Slice 29 original-result and atomicity proofs across the real SQLite boundary."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app.modules.ai_governance.application.service import AiAdapterRegistry
from app.modules.ai_governance.domain.models import AiConflictError, AiValidationError
from app.modules.ai_governance.infrastructure.schema_validation import validate_ai_governance_schema
from app.modules.ai_governance.tests.test_governance import (
    _SyntheticApprovalEvidence,
    _SyntheticSource,
)
from app.platform.migration_errors import MigrationSchemaError


@pytest.fixture
def ai_commands():
    from app.modules.ai_governance.tests.test_governance import AiGovernanceTests

    fixture = AiGovernanceTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.unit_of_work.engine.dispose()
        fixture.tearDown()


def generate(fixture):
    return fixture.generation.run(
        action_type="synthetic_action",
        source_entity_type="synthetic",
        source_entity_id="source",
        source_revision="1",
        source_fingerprint="a" * 64,
        candidate={"message": "safe"},
        idempotency_key=str(uuid4()),
    )["draft"]["id"]


def validate(fixture):
    with fixture.unit_of_work.engine.connect() as connection:
        validate_ai_governance_schema(
            connection,
            fixture.actions,
            fixture.profiles,
            fixture.configuration.adapters,
            approval_validators={"synthetic_action": _SyntheticApprovalEvidence()},
            source_validators={"synthetic": _SyntheticSource()},
        )


def state(fixture):
    with fixture.unit_of_work.engine.connect() as connection:
        return {
            table: connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY rowid").all()
            for table in (
                "ai_settings",
                "ai_model_connections",
                "ai_action_limits",
                "ai_drafts",
                "ai_review_decisions",
                "ai_command_operations",
                "synthetic_ai_results",
                "audit_events",
            )
        }


def test_settings_recovery_is_original_and_one_indexed_read(ai_commands):
    config = ai_commands.configuration
    key = str(uuid4())
    revision = config.settings()["revision"]
    first = config.update_settings(
        kill_switch=True, expected_revision=revision, idempotency_key=key
    )
    config.update_settings(
        kill_switch=False, expected_revision=first["revision"], idempotency_key=str(uuid4())
    )
    before = state(ai_commands)
    assert (
        config.update_settings(kill_switch=True, expected_revision=revision, idempotency_key=key)
        == first
    )
    statements = []

    def observe(*args):
        statements.append(args[2])

    event.listen(ai_commands.unit_of_work.engine, "before_cursor_execute", observe)
    try:
        recovered = config.command_result(idempotency_key=key)
    finally:
        event.remove(ai_commands.unit_of_work.engine, "before_cursor_execute", observe)
    assert recovered["result"] == first
    assert len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]) == 1
    assert config.command_result(operation_id=first["operationId"]) == recovered
    assert state(ai_commands) == before
    validate(ai_commands)


def test_connection_creation_patch_and_noop_replay(ai_commands):
    config = ai_commands.configuration
    source = config.connections()[0]
    data = {
        "label": "Other",
        "adapter_id": source["adapterId"],
        "adapter_version": source["adapterVersion"],
        "model_identifier": source["modelIdentifier"],
        "execution_location": "on_device",
        "model_artifact_digest": "digest",
        "quantization": "q",
        "runtime_id": "runtime",
        "runtime_version": "1",
    }
    create_key = str(uuid4())
    created = config.create_connection(data, expected_revision=0, idempotency_key=create_key)
    patch_key = str(uuid4())
    changed = config.update_connection(
        created["id"], expected_revision=1, idempotency_key=patch_key, data={"label": "Later"}
    )
    noop = config.update_connection(
        created["id"], expected_revision=2, idempotency_key=str(uuid4()), data={"label": "Later"}
    )
    assert (noop["revision"], noop["updatedAt"]) == (changed["revision"], changed["updatedAt"])
    assert (
        config.create_connection(data, expected_revision=0, idempotency_key=create_key) == created
    )
    assert (
        config.update_connection(
            created["id"], expected_revision=1, idempotency_key=patch_key, data={"label": "Later"}
        )
        == changed
    )
    with pytest.raises(AiConflictError, match="ai_idempotency_conflict"):
        config.update_connection(
            created["id"],
            expected_revision=1,
            idempotency_key=patch_key,
            data={"label": "Different"},
        )
    with pytest.raises(AiConflictError) as error:
        config.update_connection(
            created["id"],
            expected_revision=1,
            idempotency_key=str(uuid4()),
            data={"label": "Stale"},
        )
    assert error.value.revision == 2
    assert error.value.current["label"] == "Later"
    validate(ai_commands)


def test_destination_disclosure_replay_and_noop(ai_commands):
    config = ai_commands.configuration
    config.adapters = AiAdapterRegistry(
        (
            *config.adapters.all(),
            replace(config.adapters.all()[0], adapter_id="cloud", execution_location="cloud"),
        )
    )
    connection = config.create_connection(
        {
            "label": "Cloud",
            "adapter_id": "cloud",
            "adapter_version": "1",
            "model_identifier": "synthetic-model",
            "execution_location": "cloud",
        },
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key = str(uuid4())
    consent = config.set_disclosure(
        connection["id"],
        expected_revision=1,
        idempotency_key=key,
        disclosure_version="1",
        data_classes=["summary"],
    )
    noop = config.set_disclosure(
        connection["id"],
        expected_revision=2,
        idempotency_key=str(uuid4()),
        disclosure_version="1",
        data_classes=["summary"],
    )
    assert (noop["revision"], noop["updatedAt"]) == (consent["revision"], consent["updatedAt"])
    changed = config.update_connection(
        connection["id"],
        expected_revision=2,
        idempotency_key=str(uuid4()),
        data={"label": "Renamed"},
    )
    assert changed["disclosureVersion"] is None
    assert (
        config.set_disclosure(
            connection["id"],
            expected_revision=1,
            idempotency_key=key,
            disclosure_version="1",
            data_classes=["summary"],
        )
        == consent
    )
    validate(ai_commands)


def test_limits_revision_noop_and_original_result(ai_commands):
    config = ai_commands.configuration
    key = str(uuid4())
    first = config.put_limit(
        "synthetic_action", {"enabled": True}, expected_revision=0, idempotency_key=key
    )
    noop = config.put_limit(
        "synthetic_action", {"enabled": True}, expected_revision=1, idempotency_key=str(uuid4())
    )
    assert (noop["revision"], noop["updatedAt"]) == (1, first["updatedAt"])
    changed = config.put_limit(
        "synthetic_action", {"enabled": False}, expected_revision=1, idempotency_key=str(uuid4())
    )
    assert changed["revision"] == 2
    assert (
        config.put_limit(
            "synthetic_action", {"enabled": True}, expected_revision=0, idempotency_key=key
        )
        == first
    )
    validate(ai_commands)


def test_draft_edit_replays_its_original_version_after_dismissal(ai_commands):
    draft_id = generate(ai_commands)
    key = str(uuid4())
    edited = ai_commands.drafts.edit_draft(
        draft_id,
        version=1,
        idempotency_key=key,
        payload={"summary": "Reviewed"},
        operator_note="checked",
    )
    dismissed = ai_commands.drafts.dismiss_draft(
        draft_id, version=2, idempotency_key=str(uuid4()), operator_note="closed"
    )
    assert dismissed["status"] == "dismissed"
    before = state(ai_commands)
    assert (
        ai_commands.drafts.edit_draft(
            draft_id,
            version=1,
            idempotency_key=key,
            payload={"summary": "Reviewed"},
            operator_note="checked",
        )
        == edited
    )
    assert ai_commands.drafts.command_result(operation_id=edited["operationId"])["result"] == edited
    assert state(ai_commands) == before
    validate(ai_commands)


def test_approval_records_result_in_the_owner_transaction_and_replays_after_source_changes(
    ai_commands,
):
    draft_id = generate(ai_commands)
    key = str(uuid4())
    approved = ai_commands.drafts.approve_draft(
        draft_id, version=1, idempotency_key=key, operator_note="confirmed"
    )
    with ai_commands.unit_of_work.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE synthetic_ai_sources SET revision='2' WHERE id='source'")
    before = state(ai_commands)
    assert (
        ai_commands.drafts.approve_draft(
            draft_id, version=1, idempotency_key=key, operator_note="confirmed"
        )
        == approved
    )
    assert state(ai_commands) == before
    receipt = ai_commands.drafts.command_result(idempotency_key=key)
    assert receipt["result"] == approved
    with ai_commands.unit_of_work.engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM synthetic_ai_results").scalar_one()
            == 1
        )
        types = (
            connection.exec_driver_sql(
                "SELECT entity_type FROM audit_events WHERE correlation_id=?",
                (receipt["correlationId"],),
            )
            .scalars()
            .all()
        )
        assert {
            "synthetic_ai_result",
            "ai_draft",
            "ai_review_decision",
            "ai_command_operation",
        } <= set(types)
    validate(ai_commands)


@pytest.mark.parametrize(
    "action", ["settings", "connection", "limit", "edited", "dismissed", "approved"]
)
def test_receipt_failure_rolls_back_all_effects(ai_commands, action):
    config = ai_commands.configuration
    connection_id = config.connections()[0]["id"]
    draft_id = generate(ai_commands) if action in {"edited", "dismissed", "approved"} else None
    before = state(ai_commands)
    key = str(uuid4())
    commands = {
        "settings": lambda: config.update_settings(
            kill_switch=True, expected_revision=2, idempotency_key=key
        ),
        "connection": lambda: config.update_connection(
            connection_id, expected_revision=1, idempotency_key=key, data={"label": "fail"}
        ),
        "limit": lambda: config.put_limit(
            "synthetic_action", {"enabled": False}, expected_revision=0, idempotency_key=key
        ),
        "edited": lambda: ai_commands.drafts.edit_draft(
            draft_id, version=1, idempotency_key=key, payload={"summary": "changed"}
        ),
        "dismissed": lambda: ai_commands.drafts.dismiss_draft(
            draft_id, version=1, idempotency_key=key
        ),
        "approved": lambda: ai_commands.drafts.approve_draft(
            draft_id, version=1, idempotency_key=key
        ),
    }
    with patch(
        "app.modules.ai_governance.infrastructure.unit_of_work.AiGovernanceTransaction.insert_command",
        side_effect=RuntimeError("receipt failed"),
    ):
        with pytest.raises(RuntimeError, match="receipt failed"):
            commands[action]()
    assert state(ai_commands) == before


def test_duplicate_and_competing_revision_submissions_are_atomic(ai_commands):
    config = ai_commands.configuration
    revision = config.settings()["revision"]
    key = str(uuid4())
    gate = threading.Barrier(2)

    def submit():
        gate.wait()
        return config.update_settings(
            kill_switch=True, expected_revision=revision, idempotency_key=key
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: submit(), range(2)))
    assert first == second
    gate = threading.Barrier(2)

    def competing():
        gate.wait()
        try:
            return config.update_settings(
                kill_switch=False, expected_revision=first["revision"], idempotency_key=str(uuid4())
            )
        except AiConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: competing(), range(2)))
    assert sum(isinstance(result, AiConflictError) for result in results) == 1
    validate(ai_commands)


@pytest.mark.parametrize("revision,key", [(True, "valid"), (-1, "valid"), (1, "bad")])
def test_direct_call_validation_precedes_replay(ai_commands, revision, key):
    key = str(uuid4()) if key == "valid" else key
    before = state(ai_commands)
    with pytest.raises(AiValidationError):
        ai_commands.configuration.update_settings(
            expected_revision=revision, idempotency_key=key, kill_switch=True
        )
    assert state(ai_commands) == before


def test_immutable_receipts_reject_update_delete_and_replace(ai_commands):
    with ai_commands.unit_of_work.engine.connect() as connection:
        row = (
            connection.exec_driver_sql("SELECT * FROM ai_command_operations LIMIT 1")
            .mappings()
            .one()
        )
    for statement, parameters in (
        ("UPDATE ai_command_operations SET result_json='{}' WHERE id=?", (row["id"],)),
        ("DELETE FROM ai_command_operations WHERE id=?", (row["id"],)),
        (
            "INSERT OR REPLACE INTO ai_command_operations SELECT * FROM ai_command_operations WHERE id=?",
            (row["id"],),
        ),
    ):
        with pytest.raises(SQLAlchemyError):
            with ai_commands.unit_of_work.engine.begin() as connection:
                connection.exec_driver_sql(statement, parameters)


def test_retained_validator_rejects_rewritten_original_result(ai_commands):
    receipt = ai_commands.configuration.update_settings(
        kill_switch=True, expected_revision=2, idempotency_key=str(uuid4())
    )
    with ai_commands.unit_of_work.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER ai_command_operations_no_update")
        altered = {**receipt, "killSwitch": False}
        connection.exec_driver_sql(
            "UPDATE ai_command_operations SET result_json=? WHERE id=?",
            (json.dumps(altered, sort_keys=True, separators=(",", ":")), receipt["operationId"]),
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER ai_command_operations_no_update BEFORE UPDATE ON ai_command_operations BEGIN SELECT RAISE(ABORT, 'AI command operations are immutable'); END"
        )
    with pytest.raises(MigrationSchemaError, match="command history"):
        validate(ai_commands)


def test_approval_duplicate_race_creates_only_one_official_result(ai_commands):
    draft_id = generate(ai_commands)
    key = str(uuid4())
    gate = threading.Barrier(2)

    def approve():
        gate.wait()
        return ai_commands.drafts.approve_draft(draft_id, version=1, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, retry = list(pool.map(lambda _: approve(), range(2)))
    assert first == retry
    with ai_commands.unit_of_work.engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM synthetic_ai_results").scalar_one()
            == 1
        )
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM ai_review_decisions WHERE draft_id=?", (draft_id,)
            ).scalar_one()
            == 1
        )
    validate(ai_commands)


def test_commit_failure_rolls_back_command_receipt_and_effects(ai_commands):
    before = state(ai_commands)

    def fail_commit(_):
        raise RuntimeError("commit failed")

    event.listen(ai_commands.unit_of_work.engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            ai_commands.configuration.update_settings(
                kill_switch=True, expected_revision=2, idempotency_key=str(uuid4())
            )
    finally:
        event.remove(ai_commands.unit_of_work.engine, "commit", fail_commit)
    assert state(ai_commands) == before


def test_fixed_clock_review_history_remains_unambiguous(ai_commands):
    from datetime import UTC, datetime

    draft_id = generate(ai_commands)
    instant = datetime.now(UTC)
    ai_commands.drafts._clock = lambda: instant
    first = ai_commands.drafts.edit_draft(
        draft_id, version=1, idempotency_key=str(uuid4()), payload={"summary": "First"}
    )
    second = ai_commands.drafts.edit_draft(
        draft_id, version=2, idempotency_key=str(uuid4()), payload={"summary": "Second"}
    )
    assert first["operationId"] != second["operationId"]
    validate(ai_commands)


def test_operation_audit_failure_rolls_back_effect_and_receipt(ai_commands):
    from app.modules.ai_governance.infrastructure.unit_of_work import AiGovernanceTransaction

    before = state(ai_commands)
    original = AiGovernanceTransaction.record_audit

    def fail_receipt_audit(tx, **values):
        if values["entity_type"] == "ai_command_operation":
            raise RuntimeError("audit failed")
        return original(tx, **values)

    with patch.object(AiGovernanceTransaction, "record_audit", fail_receipt_audit):
        with pytest.raises(RuntimeError, match="audit failed"):
            ai_commands.configuration.update_settings(
                kill_switch=True, expected_revision=2, idempotency_key=str(uuid4())
            )
    assert state(ai_commands) == before


def test_stale_terminal_review_returns_current_draft_and_invalid_edit_is_atomic(ai_commands):
    draft_id = generate(ai_commands)
    before = state(ai_commands)
    with pytest.raises(AiValidationError):
        ai_commands.drafts.edit_draft(
            draft_id, version=1, idempotency_key=str(uuid4()), payload={"summary": 123}
        )
    assert state(ai_commands) == before
    ai_commands.drafts.edit_draft(
        draft_id, version=1, idempotency_key=str(uuid4()), payload={"summary": "Reviewed"}
    )
    ai_commands.drafts.dismiss_draft(draft_id, version=2, idempotency_key=str(uuid4()))
    with pytest.raises(AiConflictError) as error:
        ai_commands.drafts.edit_draft(
            draft_id, version=1, idempotency_key=str(uuid4()), payload={"summary": "Stale"}
        )
    assert error.value.revision == 2
    assert error.value.current["status"] == "dismissed"
    assert error.value.current["sourceEntityType"] == "synthetic"
