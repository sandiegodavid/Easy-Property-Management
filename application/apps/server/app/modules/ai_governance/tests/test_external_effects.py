"""Slice 39: real SQLite intents, device effects and uncertainty recovery."""

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import event

from app.modules.ai_governance.application.external_effects import AiExternalEffectService
from app.modules.ai_governance.application.ports import AiProviderResult
from app.modules.ai_governance.domain.models import AiConflictError, AiValidationError
from app.modules.ai_governance.infrastructure.unit_of_work import AiGovernanceTransaction
from app.modules.ai_governance.tests.test_command_readiness import (
    ai_commands as ai_commands,
    validate,
)
from app.platform.migration_errors import MigrationSchemaError


class Credentials:
    def __init__(self, uow):
        self.uow = uow
        self.value = None
        self.calls = 0
        self.fail = False

    def outside_transaction(self):
        with self.uow.engine.connect() as connection:
            connection.info["sqlite_immediate"] = True
            connection.begin()
            connection.rollback()

    def get_credential(self, workspace, connection):
        self.outside_transaction()
        return self.value

    def set_credential(self, workspace, connection, value):
        self.outside_transaction()
        self.calls += 1
        self.value = value
        if self.fail:
            raise RuntimeError("sensitive credential and provider response")

    def delete_credential(self, workspace, connection):
        self.outside_transaction()
        self.calls += 1
        self.value = None


@pytest.fixture
def effects(ai_commands):
    fixture = ai_commands
    credentials = Credentials(fixture.unit_of_work)
    service = AiExternalEffectService(
        fixture.unit_of_work,
        workspace_id="test-device",
        adapters=fixture.adapters,
        credentials=credentials,
        providers=fixture.generation.providers,
    )
    connection = fixture.configuration.connections()[0]
    return fixture, service, credentials, connection


def execute(service, connection, action="credential_set", key=None, credential="private-value"):
    # Test helper explicitly starts a new command at the current revision;
    # retries reuse the original request revision, never the later revision.
    key = key or str(uuid4())
    prior = service.unit_of_work.external_row(key=key)
    revision = (
        prior["expected_revision"]
        if prior is not None
        else service.unit_of_work.connection_row(connection["id"])["revision"]
    )
    return service.execute(
        action,
        connection["id"],
        expected_revision=revision,
        idempotency_key=key,
        credential=credential,
    )


def test_original_replay_never_reapplies_secret_or_uses_current_state(effects):
    fixture, service, credentials, connection = effects
    key = str(uuid4())
    first = execute(service, connection, key=key)
    assert first["status"] == "completed" and first["requiresDeviceValidation"]
    fixture.configuration.update_connection(
        connection["id"],
        data={"label": "Changed"},
        expected_revision=first["revision"],
        idempotency_key=str(uuid4()),
    )
    # A key identifies the intent, not a retained secret/hash. A different live
    # credential is not applied on replay; changing it requires a fresh key.
    assert execute(service, connection, key=key, credential="different-secret") == first
    assert credentials.calls == 1 and credentials.value == "private-value"
    assert service.receipt(operation_id=first["operationId"]) == first
    assert service.receipt(key=key) == first
    with pytest.raises(AiConflictError, match="idempotency"):
        execute(service, connection, action="credential_delete", key=key)
    validate(fixture)
    with fixture.unit_of_work.engine.connect() as database:
        rows = database.exec_driver_sql(
            "SELECT request_json,result_json FROM ai_external_operations"
        ).all()
        audits = database.exec_driver_sql(
            "SELECT before_snapshot,after_snapshot FROM audit_events"
        ).all()
    assert "private-value" not in str(rows + audits)
    assert "different-secret" not in str(rows + audits)


def test_credential_delete_and_probe_keep_exact_receipts(effects):
    fixture, service, credentials, connection = effects
    execute(service, connection)
    deleted = execute(service, connection, "credential_delete")
    assert deleted["result"]["beforePresent"] and not deleted["result"]["afterPresent"]
    assert credentials.value is None
    with patch.object(
        fixture.provider, "probe", return_value=AiProviderResult({"status": "ok"})
    ) as probe:

        def check(*args):
            credentials.outside_transaction()
            return AiProviderResult({"status": "ok"})

        probe.side_effect = check
        key = str(uuid4())
        result = execute(service, connection, "connection_probe", key)
        assert result["result"] == {"status": "completed", "ready": True, "reason": None}
        assert execute(service, connection, "connection_probe", key) == result
        assert probe.call_count == 1
        fixture.configuration.settings()
        assert probe.call_count == 1  # Settings is not an implicit probe.
    validate(fixture)


def test_interrupted_device_effect_is_unknown_until_explicit_acknowledgement(effects):
    fixture, service, credentials, connection = effects
    credentials.fail = True
    key = str(uuid4())
    unknown = execute(service, connection, key=key)
    assert unknown["status"] == "outcome_unknown" and credentials.value == "private-value"
    restarted = AiExternalEffectService(
        fixture.unit_of_work,
        workspace_id="test-device",
        adapters=fixture.adapters,
        credentials=credentials,
        providers=fixture.generation.providers,
    )
    assert execute(restarted, connection, key=key) == unknown and credentials.calls == 1
    with pytest.raises(AiConflictError, match="outcome_unknown"):
        execute(restarted, connection)
    abandoned = restarted.acknowledge_unknown(unknown["operationId"])
    assert abandoned["result"] == {"status": "abandoned"}
    assert restarted.acknowledge_unknown(unknown["operationId"]) == abandoned
    credentials.fail = False
    assert execute(restarted, connection)["status"] == "completed"
    assert credentials.calls == 2
    validate(fixture)


@pytest.mark.parametrize("failure_stage", ["intent", "result"])
def test_commit_failure_never_repeats_device_effect(effects, failure_stage):
    fixture, service, credentials, connection = effects
    calls = 0

    def mark_write(database, cursor, statement, parameters, context, many):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT INTO AI_EXTERNAL_OPERATIONS", "UPDATE AI_EXTERNAL_OPERATIONS"))
        ):
            database.info["external_test_write"] = True

    def fail_commit(database):
        nonlocal calls
        if not database.info.pop("external_test_write", False):
            return
        calls += 1
        if calls == (1 if failure_stage == "intent" else 2):
            raise SQLAlchemyError("simulated database commit failure")

    key = str(uuid4())
    event.listen(fixture.unit_of_work.engine, "commit", fail_commit)
    event.listen(fixture.unit_of_work.engine, "before_cursor_execute", mark_write)
    try:
        with pytest.raises(SQLAlchemyError):
            execute(service, connection, key=key)
    finally:
        event.remove(fixture.unit_of_work.engine, "commit", fail_commit)
        event.remove(fixture.unit_of_work.engine, "before_cursor_execute", mark_write)
    if failure_stage == "intent":
        assert credentials.calls == 0
        assert fixture.unit_of_work.external_row(key=key) is None
        validate(fixture)
        return
    assert credentials.calls == 1
    assert execute(service, connection, key=key)["status"] == "outcome_unknown"
    assert credentials.calls == 1
    validate(fixture)


def test_intent_audit_failure_rolls_back_before_device_effect(effects):
    fixture, service, credentials, connection = effects
    with patch.object(
        AiGovernanceTransaction, "record_audit", side_effect=SQLAlchemyError("audit failed")
    ):
        with pytest.raises(SQLAlchemyError):
            execute(service, connection)
    assert credentials.calls == 0
    with fixture.unit_of_work.engine.connect() as database:
        assert (
            database.exec_driver_sql("SELECT count(*) FROM ai_external_operations").scalar_one()
            == 0
        )


@pytest.mark.parametrize("revision", [True, "1", -1, 0])
def test_direct_call_revision_validation(effects, revision):
    _, service, _, connection = effects
    with pytest.raises(AiValidationError):
        service.execute(
            "credential_set",
            connection["id"],
            expected_revision=revision,
            idempotency_key=str(uuid4()),
            credential="value",
        )


def test_stale_revision_is_rejected_before_external_call(effects):
    fixture, service, credentials, connection = effects
    fixture.configuration.update_connection(
        connection["id"],
        data={"label": "Changed"},
        expected_revision=connection["revision"],
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(AiConflictError, match="revision") as caught:
        service.execute(
            "credential_set",
            connection["id"],
            expected_revision=connection["revision"],
            idempotency_key=str(uuid4()),
            credential="value",
        )
    assert caught.value.revision == connection["revision"] + 1
    assert credentials.calls == 0


def test_concurrent_duplicate_and_acknowledgement_do_not_repeat_probe(effects):
    fixture, service, _, connection = effects
    entered, release = Event(), Event()
    key = str(uuid4())

    def probe(*args):
        entered.set()
        assert release.wait(5)
        return AiProviderResult({"status": "ok"})

    with patch.object(fixture.provider, "probe", side_effect=probe) as transport:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(execute, service, connection, "connection_probe", key)
            assert entered.wait(5)
            try:
                intent = service.receipt(key=key)
                with pytest.raises(AiConflictError, match="in_progress"):
                    service.acknowledge_unknown(intent["operationId"])
                with pytest.raises(AiConflictError, match="in_progress"):
                    execute(service, connection, "connection_probe", key)
                with pytest.raises(AiConflictError, match="outcome_unknown"):
                    execute(service, connection, "connection_probe")
            finally:
                release.set()
            result = first.result(5)
        assert execute(service, connection, "connection_probe", key) == result
        assert transport.call_count == 1
    validate(fixture)


def test_unknown_probe_does_not_store_provider_error_and_is_not_retried(effects):
    fixture, service, _, connection = effects
    key = str(uuid4())
    with patch.object(
        fixture.provider, "probe", side_effect=RuntimeError("secret-provider-body")
    ) as transport:
        unknown = execute(service, connection, "connection_probe", key)
        assert unknown["status"] == "outcome_unknown"
        assert execute(service, connection, "connection_probe", key) == unknown
        assert transport.call_count == 1
    with fixture.unit_of_work.engine.connect() as database:
        assert "secret-provider-body" not in str(
            database.exec_driver_sql("SELECT * FROM ai_external_operations").all()
        )
    validate(fixture)


def test_terminal_result_and_intent_are_immutable(effects):
    fixture, service, _, connection = effects
    execute(service, connection)
    for statement in (
        "UPDATE ai_external_operations SET request_fingerprint='f'",
        "DELETE FROM ai_external_operations",
        "UPDATE ai_external_operations SET result_json='{}'",
    ):
        with fixture.unit_of_work.engine.begin() as database:
            with pytest.raises(SQLAlchemyError):
                database.exec_driver_sql(statement)
    validate(fixture)


def test_retained_result_tampering_is_rejected(effects):
    fixture, service, _, connection = effects
    execute(service, connection)
    with fixture.unit_of_work.engine.begin() as database:
        database.exec_driver_sql("DROP TRIGGER ai_external_finish_only")
        database.exec_driver_sql(
            "UPDATE ai_external_operations SET result_json=?",
            (json.dumps({"status": "completed", "secret": "forbidden"}),),
        )
        from app.modules.ai_governance.infrastructure.sqlalchemy_models import EXTERNAL_TRIGGERS

        database.exec_driver_sql(EXTERNAL_TRIGGERS["ai_external_finish_only"])
    with pytest.raises(MigrationSchemaError, match="external"):
        validate(fixture)


@pytest.mark.parametrize("tamper", ["partial_index", "trigger", "correlation"])
def test_retained_external_schema_and_audit_tampering_is_rejected(effects, tamper):
    fixture, service, _, connection = effects
    execute(service, connection)
    with fixture.unit_of_work.engine.begin() as database:
        if tamper == "partial_index":
            database.exec_driver_sql("DROP INDEX ai_external_pending_connection")
            database.exec_driver_sql(
                "CREATE UNIQUE INDEX ai_external_pending_connection ON ai_external_operations(connection_id) WHERE result_json IS NULL OR action='connection_probe'"
            )
        elif tamper == "trigger":
            database.exec_driver_sql("DROP TRIGGER ai_external_finish_only")
            database.exec_driver_sql(
                "CREATE TRIGGER ai_external_finish_only BEFORE UPDATE ON ai_external_operations BEGIN SELECT 1; END"
            )
        else:
            triggers = database.exec_driver_sql(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events'"
            ).all()
            for name, _ in triggers:
                database.exec_driver_sql(f'DROP TRIGGER "{name}"')
            database.exec_driver_sql(
                "UPDATE audit_events SET correlation_id=? WHERE entity_type='ai_external_operation'",
                (str(uuid4()),),
            )
            for _, sql in triggers:
                database.exec_driver_sql(sql)
    with pytest.raises(MigrationSchemaError):
        validate(fixture)
