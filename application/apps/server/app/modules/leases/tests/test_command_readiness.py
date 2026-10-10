"""SQLite proofs for UI-001 Slice 13 Lease command gates."""

from app.modules.portfolio.tests.commands import inventory_command

import inspect
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event

from app.bootstrap.api import create_app
from app.modules.leases.application.commands import COMMAND_ACTIONS
from app.modules.leases.application.ports import LeaseConflictError
from app.modules.leases.application.service import (
    LeaseError,
    LeaseCreateCommand,
    LeaseNotFoundError,
    LeasePatchCommand,
    ParticipantCommand,
    RenewalCommand,
    RenewalPatchCommand,
    TermCommand,
    TerminationCaseCommand,
    TerminationProposalCommand,
)
from app.modules.leases.tests.commands import lease_command
from app.modules.portfolio.application.service import OwnershipInput, PropertyCreateCommand
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.bootstrap.operator_command_forms import compose_command_forms
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS
from app.modules.operator.application.recovery_schemas import registered_schemas, validate_payload
from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.modules.leases.infrastructure.recovery_reader import SQLiteLeaseRecoveryReader
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.operator.domain.models import OperatorError


@pytest.fixture
def fixture():
    from app.modules.leases.tests.test_leases import LeaseTerminationTests

    case = LeaseTerminationTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def _patch(notes):
    return LeasePatchCommand(notes=notes, supplied_fields=frozenset({"notes"}))


def _vacant_draft(fixture):
    property_record = inventory_command(
        fixture.portfolio,
        "create_property",
        PropertyCreateCommand(
            "Vacant command test home",
            "2 Main Street",
            "Portland",
            "US",
            "single_family_home",
            (OwnershipInput("local_operator"),),
            region="OR",
        ),
    )
    space_id = fixture.portfolio.get_property(property_record.id)["spaces"][0]["id"]
    tomorrow = date.today() + timedelta(days=1)
    return fixture.service.create(
        LeaseCreateCommand(
            space_id,
            "residential",
            tomorrow,
            None,
            tomorrow,
            TermCommand(10000, "USD", "monthly", 1, 0),
            (ParticipantCommand(fixture.tenant_id, "primary_tenant"),),
        ),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )


def test_creation_and_patch_replay_original_response_after_later_edits(fixture):
    draft = fixture._new_draft(starts_on=date.today() + timedelta(days=1))
    key = str(uuid4())
    first = fixture.service.patch(
        draft["id"], _patch("first"), expected_revision=1, idempotency_key=key
    )
    later = fixture.service.patch(
        draft["id"], _patch("later"), expected_revision=2, idempotency_key=str(uuid4())
    )
    assert later["leaseRevision"] == 3
    assert (
        fixture.service.patch(
            draft["id"], _patch("first"), expected_revision=1, idempotency_key=key
        )
        == first
    )
    receipt = fixture.service.get_command_operation(idempotency_key=key, lease_id=draft["id"])
    assert receipt["response"] == first
    assert fixture.service.get_command_operation(operation_id=first["operationId"]) == receipt
    with pytest.raises(LeaseConflictError):
        fixture.service.patch(
            draft["id"], _patch("changed"), expected_revision=1, idempotency_key=key
        )
    with pytest.raises(LeaseNotFoundError):
        fixture.service.get_command_operation(idempotency_key=key, lease_id=fixture.lease["id"])
    with fixture.service.unit_of_work.engine.connect() as connection:
        creation = (
            connection.exec_driver_sql(
                "SELECT * FROM lease_command_operations WHERE lease_id=? AND action='create'",
                (draft["id"],),
            )
            .mappings()
            .one()
        )
        recorded = json.loads(creation["response_json"])
    assert recorded == draft
    validate_latest_schema(fixture.workspace.paths.database)


def test_lease_recovery_forms_are_registered_with_source_owned_bindings():
    class Reader:
        def related_state(self, connection, kind, target_id):
            return None

    bindings = compose_command_forms(Reader(), Reader(), Reader(), Reader())
    lease_forms = {key for key in COMMAND_SCHEMAS if key.startswith("lease.")}
    assert lease_forms == {
        "lease.create",
        "lease.patch",
        "lease.term.replace",
        "lease.participant.add",
        "lease.participant.update",
        "lease.participant.remove",
        "lease.execute",
        "lease.end",
        "lease.terminate",
        "lease.void",
        "lease.renewal.add",
        "lease.renewal.update",
        "lease.renewal.decide",
        "lease.termination.create",
        "lease.termination.proposal.add",
        "lease.termination.proposal.accept",
        "lease.termination.transition",
        "lease.termination.complete",
    }
    assert lease_forms <= set(bindings)
    assert {key for key in registered_schemas() if key.startswith("lease.")} == lease_forms
    assert bindings["lease.create"].source_kind is None
    assert bindings["lease.create"].result_kind == "lease"
    assert bindings["communication.create"].source_kind is None
    assert bindings["communication.create"].result_kind == "communication"
    assert all(bindings[key].source_kind == "lease" for key in lease_forms - {"lease.create"})
    assert all(bindings[key].family == "lease" for key in lease_forms)


def test_lease_recovery_fingerprint_and_lookup_match_original_receipt(fixture):
    draft = fixture._new_draft(starts_on=date.today() + timedelta(days=1))
    key = str(uuid4())
    payload = {"expectedRevision": 1, "notes": "Recovered edit"}
    validate_payload("lease.patch", 1, payload)

    class EmptyReader:
        def related_state(self, connection, kind, target_id):
            return None

    empty_reader = EmptyReader()
    bindings = compose_command_forms(empty_reader, empty_reader, empty_reader, empty_reader)
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=bindings,
    )
    fingerprint_input = {
        "form_key": "lease.patch",
        "payload_json": json.dumps(payload),
        "source_id": draft["id"],
    }
    request_fingerprint = references.attempt_fingerprint(fingerprint_input, key)
    pending = {
        **fingerprint_input,
        "source_kind": "lease",
        "base_source_revision": "1",
    }
    with fixture.service.unit_of_work.engine.connect() as connection:
        assert references.validate(connection, pending) == "available"
    response = fixture.service.patch(
        draft["id"], _patch("Recovered edit"), expected_revision=1, idempotency_key=key
    )
    with fixture.service.unit_of_work.engine.connect() as connection:
        reader = SQLiteLeaseRecoveryReader()
        receipt = reader.outcome(connection, key, family="lease")
        state = reader.state(connection, draft["id"])
        recovered = references.resolve_attempt(
            connection,
            "lease.patch",
            key,
            request_fingerprint,
            source_id=draft["id"],
        )
    assert receipt is not None
    assert receipt.source_id == draft["id"]
    assert receipt.request_fingerprint == request_fingerprint
    assert receipt.result.target_id == draft["id"]
    assert receipt.result.revision == response["leaseRevision"]
    assert state["revision"] == response["leaseRevision"]
    assert recovered["receiptId"] == response["operationId"]
    assert recovered["attemptKey"] == key
    with fixture.service.unit_of_work.engine.connect() as connection:
        assert references.validate(connection, pending) == "source_changed"


@pytest.mark.parametrize("action", ["add", "update"])
@pytest.mark.parametrize("dates", ["start", "end", "both", "omitted", "null"])
def test_participant_form_dates_prepare_and_reconcile_committed_receipt(fixture, action, dates):
    start = date.today() + timedelta(days=1)
    draft = fixture._new_draft(starts_on=start)
    participant_id = draft["participants"][0]["id"]
    if action == "add":
        draft = lease_command(fixture.service, "remove_participant", draft["id"], participant_id)

    class EmptyReader:
        def related_state(self, connection, kind, target_id):
            return None

    reader = EmptyReader()
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_command_forms(reader, reader, reader, reader),
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        fixture.service.unit_of_work.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    fixture.addCleanup(uow.engine.dispose)
    identity = RuntimeIdentity("ready", fixture.workspace.open().workspace_id, str(uuid4()), True)
    support = OperatorService(uow, runtime=lambda: identity)
    payload = {
        "expectedRevision": draft["leaseRevision"],
        "tenantPartyId": fixture.tenant_id,
        "participantRole": "co_tenant",
        "notes": "  participant dates  ",
    }
    if dates in {"start", "both"}:
        payload["startsOn"] = (start + timedelta(days=2)).isoformat()
    if dates in {"end", "both"}:
        payload["endsOn"] = (start + timedelta(days=10)).isoformat()
    if dates == "null":
        payload.update(startsOn=None, endsOn=None)
    if action == "update":
        payload["participantId"] = participant_id
    form_key = "lease.participant." + action
    validate_payload(form_key, 1, payload)
    saved = support.save_recovery(
        str(uuid4()),
        form_key=form_key,
        schema_version=1,
        payload=payload,
        source_kind="lease",
        source_id=draft["id"],
        base_source_revision=str(draft["leaseRevision"]),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key, preparation_key = str(uuid4()), str(uuid4())
    attempt = support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    assert attempt == support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    command = ParticipantCommand(
        fixture.tenant_id,
        "co_tenant",
        starts_on=payload.get("startsOn"),
        ends_on=payload.get("endsOn"),
        notes=payload["notes"],
    )
    arguments = (
        (draft["id"], command) if action == "add" else (draft["id"], participant_id, command)
    )
    mutate = getattr(fixture.service, action + "_participant")
    original = mutate(*arguments, expected_revision=draft["leaseRevision"], idempotency_key=key)
    assert (
        mutate(*arguments, expected_revision=draft["leaseRevision"], idempotency_key=key)
        == original
    )
    participant = original["participants"][0]
    assert participant["startsOn"] == (payload.get("startsOn") or draft["contractStartsOn"])
    assert participant["endsOn"] == (payload.get("endsOn") or draft["contractEndsOn"])
    assert participant["notes"] == "participant dates"
    receipt = fixture.service.get_command_operation(operation_id=original["operationId"])
    assert receipt["requestFingerprint"] == attempt["requestFingerprint"]
    assert receipt["response"] == original
    reconciliation_key = str(uuid4())
    reconciled = support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=reconciliation_key
    )
    assert reconciled == support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=reconciliation_key
    )
    assert reconciled["receipt"]["receiptId"] == original["operationId"]
    assert reconciled["receipt"]["result"]["revision"] == original["leaseRevision"]
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize("notes_case", ["padded", "whitespace", "omitted", "null"])
def test_renewal_decision_notes_match_source_command_and_recovery(fixture, notes_case):
    renewal = lease_command(
        fixture.service,
        "add_renewal_option",
        fixture.lease["id"],
        RenewalCommand(date.today() + timedelta(days=365), notes="Existing renewal notes"),
    )
    option_id = renewal["renewalOptions"][0]["id"]

    class EmptyReader:
        def related_state(self, connection, kind, target_id):
            return None

    reader = EmptyReader()
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_command_forms(reader, reader, reader, reader),
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        fixture.service.unit_of_work.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    fixture.addCleanup(uow.engine.dispose)
    identity = RuntimeIdentity("ready", fixture.workspace.open().workspace_id, str(uuid4()), True)
    support = OperatorService(uow, runtime=lambda: identity)
    payload = {
        "expectedRevision": renewal["leaseRevision"],
        "optionId": option_id,
        "status": "declined",
        "decidedOn": date.today().isoformat(),
    }
    if notes_case != "omitted":
        payload["notes"] = {"padded": "  reviewed  ", "whitespace": " \t\n ", "null": None}[
            notes_case
        ]
    validate_payload("lease.renewal.decide", 1, payload)
    saved = support.save_recovery(
        str(uuid4()),
        form_key="lease.renewal.decide",
        schema_version=1,
        payload=payload,
        source_kind="lease",
        source_id=renewal["id"],
        base_source_revision=str(renewal["leaseRevision"]),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key, preparation_key = str(uuid4()), str(uuid4())
    command = {
        "status": payload["status"],
        "decided_on": payload["decidedOn"],
        **({"notes": payload["notes"]} if "notes" in payload else {}),
        "expected_revision": renewal["leaseRevision"],
        "idempotency_key": key,
    }
    if notes_case == "whitespace":
        before = fixture.service.get(renewal["id"])
        with pytest.raises(OperatorError, match="valid owning command"):
            support.prepare_attempt(
                saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
            )
        with pytest.raises(LeaseError, match="Renewal notes"):
            fixture.service.decide_renewal_option(renewal["id"], option_id, **command)
        assert fixture.service.get(renewal["id"]) == before
        with pytest.raises(LeaseNotFoundError):
            fixture.service.get_command_operation(idempotency_key=key)
        validate_latest_schema(fixture.workspace.paths.database)
        return

    attempt = support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    assert attempt == support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    original = fixture.service.decide_renewal_option(renewal["id"], option_id, **command)
    assert fixture.service.decide_renewal_option(renewal["id"], option_id, **command) == original
    receipt = fixture.service.get_command_operation(operation_id=original["operationId"])
    assert receipt["requestFingerprint"] == attempt["requestFingerprint"]
    assert receipt["response"] == original
    expected_notes = "reviewed" if notes_case == "padded" else None
    with uow.engine.connect() as connection:
        request = json.loads(
            connection.exec_driver_sql(
                "SELECT request_json FROM lease_command_operations WHERE id=?",
                (original["operationId"],),
            ).scalar_one()
        )
    assert request["payload"]["notes"] == expected_notes
    assert request["payload"]["notesSupplied"] is (notes_case == "padded")
    assert original["renewalOptions"][0]["notes"] == (expected_notes or "Existing renewal notes")
    reconciliation_key = str(uuid4())
    reconciled = support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=reconciliation_key
    )
    assert reconciled == support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=reconciliation_key
    )
    assert reconciled["receipt"]["receiptId"] == original["operationId"]
    assert reconciled["receipt"]["result"]["revision"] == original["leaseRevision"]
    validate_latest_schema(fixture.workspace.paths.database)


def test_lease_creation_recovery_fingerprint_matches_persisted_receipt(fixture):
    class EmptyReader:
        def related_state(self, connection, kind, target_id):
            return None

    empty_reader = EmptyReader()
    bindings = compose_command_forms(empty_reader, empty_reader, empty_reader, empty_reader)
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=bindings,
    )
    property_record = inventory_command(
        fixture.portfolio,
        "create_property",
        PropertyCreateCommand(
            "Lease recovery creation test home",
            "3 Main Street",
            "Portland",
            "US",
            "single_family_home",
            (OwnershipInput("local_operator"),),
            region="OR",
        ),
    )
    space_id = fixture.portfolio.get_property(property_record.id)["spaces"][0]["id"]
    start = (date.today() + timedelta(days=2)).isoformat()
    key = str(uuid4())
    payload = {
        "expectedRevision": 0,
        "spaceId": space_id,
        "leaseKind": "residential",
        "contractStartsOn": start,
        "contractEndsOn": None,
        "occupancyStartsOn": start,
        "initialTerm": {
            "baseRentMinor": 250000,
            "currencyCode": "USD",
            "paymentFrequency": "monthly",
            "paymentDueDay": 1,
            "agreedSecurityDepositMinor": 0,
        },
        "participants": [{"tenantPartyId": fixture.tenant_id, "participantRole": "primary_tenant"}],
        "notes": None,
    }
    validate_payload("lease.create", 1, payload)
    pending = {
        "form_key": "lease.create",
        "payload_json": json.dumps(payload),
        "source_id": None,
        "source_kind": None,
        "base_source_revision": None,
    }
    with fixture.service.unit_of_work.engine.connect() as connection:
        assert references.validate(connection, pending) == "available"
    request_fingerprint = references.attempt_fingerprint(
        {"form_key": "lease.create", "payload_json": json.dumps(payload), "source_id": None},
        key,
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        fixture.service.unit_of_work.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    fixture.addCleanup(uow.engine.dispose)
    identity = RuntimeIdentity("ready", fixture.workspace.open().workspace_id, str(uuid4()), True)
    support = OperatorService(uow, runtime=lambda: identity)
    saved = support.save_recovery(
        str(uuid4()),
        form_key="lease.create",
        schema_version=1,
        payload=payload,
        source_kind=None,
        source_id=None,
        base_source_revision=None,
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    preparation_key = str(uuid4())
    attempt = support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    assert attempt == support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    assert attempt["requestFingerprint"] == request_fingerprint
    created = fixture.service.create(
        LeaseCreateCommand(
            space_id,
            "residential",
            start,
            None,
            start,
            TermCommand(250000, "USD", "monthly", 1, 0),
            (ParticipantCommand(fixture.tenant_id, "primary_tenant"),),
        ),
        expected_revision=0,
        idempotency_key=key,
    )
    with fixture.service.unit_of_work.engine.connect() as connection:
        recovered = references.resolve_attempt(
            connection,
            "lease.create",
            key,
            request_fingerprint,
            source_id=None,
        )
    expected_receipt = {
        "sourceKind": "lease",
        "sourceId": created["id"],
        "receiptId": created["operationId"],
        "attemptKey": key,
        "result": {
            "targetId": created["id"],
            "revision": created["leaseRevision"],
            "status": created["status"],
            "operationId": created["operationId"],
        },
    }
    assert recovered == expected_receipt
    reconciliation_key = str(uuid4())
    reconciled = support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=reconciliation_key
    )
    assert reconciled["receipt"] == expected_receipt
    assert reconciled == support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=reconciliation_key
    )
    validate_latest_schema(fixture.workspace.paths.database)


def test_no_op_receipts_preserve_lease_timestamp_and_revision(fixture):
    draft = fixture._new_draft(starts_on=date.today() + timedelta(days=1))
    result = fixture.service.patch(
        draft["id"], _patch(None), expected_revision=1, idempotency_key=str(uuid4())
    )
    assert result["leaseRevision"] == draft["leaseRevision"]
    assert result["updatedAt"] == draft["updatedAt"]
    assert (
        fixture.service.get_command_operation(operation_id=result["operationId"])["effective"]
        is False
    )
    validate_latest_schema(fixture.workspace.paths.database)


def test_term_participant_and_renewal_commands_share_parent_revision(fixture):
    draft = fixture._new_draft(starts_on=date.today() + timedelta(days=1))
    replaced = lease_command(
        fixture.service,
        "replace_initial_term",
        draft["id"],
        TermCommand(230000, "USD", "monthly", 1, 0),
    )
    assert replaced["leaseRevision"] == 2
    participant_id = replaced["participants"][0]["id"]
    changed = lease_command(
        fixture.service,
        "update_participant",
        draft["id"],
        participant_id,
        ParticipantCommand(fixture.tenant_id, "primary_tenant", notes="occupant"),
    )
    assert changed["leaseRevision"] == 3
    with pytest.raises(LeaseConflictError) as conflict:
        fixture.service.patch(
            draft["id"], _patch("stale"), expected_revision=2, idempotency_key=str(uuid4())
        )
    assert conflict.value.current_status["leaseRevision"] == 3
    removed = lease_command(fixture.service, "remove_participant", draft["id"], participant_id)
    assert removed["participants"] == []
    added = lease_command(
        fixture.service,
        "add_participant",
        draft["id"],
        ParticipantCommand(fixture.tenant_id, "primary_tenant"),
    )
    assert added["leaseRevision"] == 5
    renewal = lease_command(
        fixture.service,
        "add_renewal_option",
        fixture.lease["id"],
        RenewalCommand(date.today() + timedelta(days=365)),
    )
    option_id = renewal["renewalOptions"][0]["id"]
    edited = lease_command(
        fixture.service,
        "update_renewal_option",
        fixture.lease["id"],
        option_id,
        RenewalPatchCommand(notes="review", supplied_fields=frozenset({"notes"})),
    )
    decided = lease_command(
        fixture.service,
        "decide_renewal_option",
        fixture.lease["id"],
        option_id,
        status="declined",
        decided_on=date.today(),
    )
    assert decided["leaseRevision"] == edited["leaseRevision"] + 1
    assert (
        fixture.service.get_command_operation(operation_id=renewal["operationId"])["response"]
        == renewal
    )
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize(
    ("reason", "end_reason"),
    [
        ("job_relocation", "early_termination"),
        ("military", "early_termination"),
        ("habitability", "early_termination"),
        ("mutual", "mutual_termination"),
        ("other", "other"),
    ],
)
def test_termination_completion_attempt_recovers_source_derived_reason(fixture, reason, end_reason):
    case = lease_command(
        fixture.service,
        "create_termination_case",
        fixture.lease["id"],
        TerminationCaseCommand(reason, date.today(), date.today(), date.today()),
    )
    lease_command(fixture.service, "transition_termination_case", case["id"], status="under_review")
    proposal = lease_command(
        fixture.service,
        "add_termination_proposal",
        case["id"],
        TerminationProposalCommand(date.today(), date.today()),
    )
    accepted = lease_command(
        fixture.service,
        "accept_termination_proposal",
        case["id"],
        proposal["proposals"][0]["id"],
        accepted_on=date.today(),
        confirmed=True,
    )

    class EmptyReader:
        def related_state(self, connection, kind, target_id):
            return None

    reader = EmptyReader()
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_command_forms(reader, reader, reader, reader),
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        fixture.service.unit_of_work.recorder,
        references,
        SQLiteAuditReadMarker(),
    )
    fixture.addCleanup(uow.engine.dispose)
    identity = RuntimeIdentity("ready", fixture.workspace.open().workspace_id, str(uuid4()), True)
    support = OperatorService(uow, runtime=lambda: identity)
    tomorrow = date.today() + timedelta(days=1)
    payload = {
        "caseId": case["id"],
        "actualMoveOutOn": tomorrow.isoformat(),
        "confirmed": True,
        "expectedRevision": accepted["leaseRevision"],
        "expectedSpaceRevision": fixture.portfolio.get_space_status(fixture.space_id)["revision"],
    }
    validate_payload("lease.termination.complete", 1, payload)
    saved = support.save_recovery(
        str(uuid4()),
        form_key="lease.termination.complete",
        schema_version=1,
        payload=payload,
        source_kind="lease",
        source_id=fixture.lease["id"],
        base_source_revision=str(accepted["leaseRevision"]),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key, preparation_key = str(uuid4()), str(uuid4())
    attempt = support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )
    assert attempt == support.prepare_attempt(
        saved["id"], attempt_key=key, expected_revision=1, idempotency_key=preparation_key
    )

    class CompletionDate(date):
        @classmethod
        def today(cls):
            return tomorrow

    with patch("app.modules.leases.application.service.date", CompletionDate):
        original = fixture.service.complete_termination_case(
            case["id"],
            actual_move_out_on=payload["actualMoveOutOn"],
            confirmed=True,
            expected_revision=payload["expectedSpaceRevision"],
            expected_lease_revision=payload["expectedRevision"],
            idempotency_key=key,
        )
    assert original["endReason"] == end_reason
    receipt = fixture.service.get_command_operation(operation_id=original["operationId"])
    assert receipt["response"] == original
    assert receipt["requestFingerprint"] == attempt["requestFingerprint"]
    reconciled = support.reconcile_recovery(
        saved["id"], expected_revision=2, idempotency_key=str(uuid4())
    )
    assert reconciled["receipt"]["receiptId"] == original["operationId"]
    assert reconciled["receipt"]["result"]["revision"] == original["leaseRevision"]

    with uow.engine.connect() as connection:
        for source_id, case_id in (
            (fixture.lease["id"], str(uuid4())),
            (str(uuid4()), case["id"]),
        ):
            with pytest.raises(OperatorError, match="belonging to this Lease"):
                references.attempt_fingerprint(
                    {
                        "form_key": "lease.termination.complete",
                        "source_id": source_id,
                        "payload_json": json.dumps({**payload, "caseId": case_id}),
                    },
                    str(uuid4()),
                    connection=connection,
                )
    validate_latest_schema(fixture.workspace.paths.database)


def test_negotiation_commands_and_completion_replay_original_results(fixture):
    case = lease_command(
        fixture.service,
        "create_termination_case",
        fixture.lease["id"],
        TerminationCaseCommand("mutual", date.today(), date.today(), date.today()),
    )
    review = lease_command(
        fixture.service, "transition_termination_case", case["id"], status="under_review"
    )
    proposal = lease_command(
        fixture.service,
        "add_termination_proposal",
        case["id"],
        TerminationProposalCommand(date.today(), date.today()),
    )
    accepted = lease_command(
        fixture.service,
        "accept_termination_proposal",
        case["id"],
        proposal["proposals"][0]["id"],
        accepted_on=date.today(),
        confirmed=True,
    )
    before_space = fixture.portfolio.get_space_status(fixture.space_id)["revision"]
    key = str(uuid4())
    tomorrow = date.today() + timedelta(days=1)

    class CompletionDate(date):
        @classmethod
        def today(cls):
            return tomorrow

    with patch("app.modules.leases.application.service.date", CompletionDate):
        result = fixture.service.complete_termination_case(
            case["id"],
            actual_move_out_on=tomorrow.isoformat(),
            confirmed=True,
            expected_revision=before_space,
            expected_lease_revision=accepted["leaseRevision"],
            idempotency_key=key,
        )
        replay = fixture.service.complete_termination_case(
            case["id"],
            actual_move_out_on=tomorrow.isoformat(),
            confirmed=True,
            expected_revision=before_space,
            expected_lease_revision=accepted["leaseRevision"],
            idempotency_key=key,
        )
    assert replay == result
    assert result["revision"] == before_space + 1
    assert result["leaseRevision"] == accepted["leaseRevision"] + 1
    current_case = fixture.service.get_termination_case(case["id"])
    assert current_case["leaseRevision"] == result["leaseRevision"]
    assert fixture.service.list_termination_cases(fixture.lease["id"]) == [current_case]
    for original in (case, review, proposal, accepted, result):
        assert (
            fixture.service.get_command_operation(operation_id=original["operationId"])["response"]
            == original
        )
    validate_latest_schema(fixture.workspace.paths.database)


def test_timeline_has_distinct_lease_and_space_revisions(fixture):
    # A child change advances Leasing only. It makes an operator's Lease view stale
    # while the Space timeline is still unchanged.
    before_space = fixture.portfolio.get_space_status(fixture.space_id)["revision"]
    lease_command(
        fixture.service,
        "add_renewal_option",
        fixture.lease["id"],
        RenewalCommand(date.today() + timedelta(days=365)),
    )
    assert fixture.portfolio.get_space_status(fixture.space_id)["revision"] == before_space
    with pytest.raises(LeaseConflictError) as conflict:
        fixture.service.end(
            fixture.lease["id"],
            actual_move_out_on=date.today(),
            confirmed=True,
            expected_revision=before_space,
            expected_lease_revision=fixture.lease["leaseRevision"],
            idempotency_key=str(uuid4()),
        )
    assert conflict.value.current_status["leaseRevision"] == fixture.lease["leaseRevision"] + 1
    replay = fixture.service.execute(
        fixture.lease["id"],
        executed_on=date.today(),
        confirmed=True,
        expected_revision=fixture._execute_revision,
        expected_lease_revision=1,
        idempotency_key=fixture._execute_key,
    )
    assert replay == fixture.lease


def test_receipt_audit_failure_rolls_back_lease_and_portfolio(fixture):
    draft = _vacant_draft(fixture)
    before_status = fixture.portfolio.get_space_status(draft["spaceId"])
    key = str(uuid4())
    repository = fixture.service.unit_of_work.recorder.repository
    append = repository.append

    def fail_receipt(connection, audit):
        if audit.entity_type == "lease_command_operation":
            raise RuntimeError("receipt audit failed")
        return append(connection, audit)

    with (
        patch.object(repository, "append", side_effect=fail_receipt),
        pytest.raises(RuntimeError, match="receipt audit failed"),
    ):
        fixture.service.execute(
            draft["id"],
            executed_on=date.today(),
            confirmed=True,
            expected_revision=before_status["revision"],
            expected_lease_revision=1,
            idempotency_key=key,
        )
    assert fixture.service.get(draft["id"])["status"] == "draft"
    assert fixture.service.get(draft["id"])["leaseRevision"] == 1
    after_status = fixture.portfolio.get_space_status(draft["spaceId"])
    assert {key: value for key, value in after_status.items() if key != "asOf"} == {
        key: value for key, value in before_status.items() if key != "asOf"
    }
    with pytest.raises(LeaseNotFoundError):
        fixture.service.get_command_operation(idempotency_key=key)
    validate_latest_schema(fixture.workspace.paths.database)


def test_read_only_recovery_is_one_query_and_does_not_hydrate_current_state(fixture):
    engine = fixture.service.unit_of_work.engine
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        receipt = fixture.service.get_command_operation(idempotency_key=fixture._execute_key)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert receipt["response"] == fixture.lease
    assert len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]) == 1
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )


def test_public_contracts_require_concurrency_and_reject_boolean_revisions(fixture):
    for action in COMMAND_ACTIONS - {"ended", "terminated"} | {"end", "terminate"}:
        signature = inspect.signature(getattr(fixture.service, action))
        assert signature.parameters["idempotency_key"].default is inspect.Parameter.empty
        revision = (
            "expected_lease_revision"
            if action in {"execute", "end", "terminate", "void", "complete_termination_case"}
            else "expected_revision"
        )
        assert signature.parameters[revision].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        fixture.service.patch(fixture.lease["id"], _patch("missing metadata"))
    for revision in (True, -1, "1", None):
        with pytest.raises(LeaseError):
            fixture.service.patch(
                fixture.lease["id"],
                _patch("invalid"),
                expected_revision=revision,
                idempotency_key=str(uuid4()),
            )


def test_http_create_receipt_recovery_and_stale_conflict_are_typed(fixture):
    payload = {
        "spaceId": fixture.space_id,
        "leaseKind": "residential",
        "contractStartsOn": date.today().isoformat(),
        "occupancyStartsOn": date.today().isoformat(),
        "initialTerm": {
            "baseRentMinor": 10000,
            "currencyCode": "USD",
            "paymentFrequency": "monthly",
            "paymentDueDay": 1,
            "agreedSecurityDepositMinor": 0,
        },
        "participants": [{"tenantPartyId": fixture.tenant_id, "participantRole": "primary_tenant"}],
        "expectedLeaseRevision": 0,
        "idempotencyKey": str(uuid4()),
    }
    with TestClient(create_app(fixture.workspace.config.config_path)) as client:
        result = client.post("/api/leases", json=payload)
        assert result.status_code == 201, result.text
        first = result.json()
        assert first["leaseRevision"] == 1
        assert client.post("/api/leases", json=payload).json() == first
        endpoint = f"/api/leases/{first['id']}/operations/by-key"
        assert (
            client.get(endpoint, params={"idempotencyKey": payload["idempotencyKey"]}).json()[
                "response"
            ]
            == first
        )
        assert (
            client.get(f"/api/leases/operations/{first['operationId']}").json()["response"] == first
        )
        changed = client.patch(
            f"/api/leases/{first['id']}",
            json={"notes": "edit", "expectedLeaseRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert changed.status_code == 200, changed.text
        stale = client.patch(
            f"/api/leases/{first['id']}",
            json={"notes": "stale", "expectedLeaseRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["currentStatus"]["leaseRevision"] == 2
        assert client.get("/api/leases/operations/not-a-uuid").status_code == 422
        paths = client.get("/openapi.json").json()["paths"]
        assert (
            paths["/api/leases/operations/{operation_id}"]["get"]["operationId"]
            == "getLeaseCommandOperation"
        )
        assert (
            paths["/api/leases/{lease_id}/operations/by-key"]["get"]["operationId"]
            == "getLeaseCommandOperationByKey"
        )


def test_schema_rejects_changed_receipt_and_broken_revision_history(fixture):
    database = fixture.workspace.paths.database
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE lease_command_operations SET response_json='{}'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM lease_command_operations")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT OR REPLACE INTO lease_command_operations SELECT * FROM lease_command_operations LIMIT 1"
            )
        connection.execute(
            "UPDATE leases SET lease_revision=lease_revision+1 WHERE id=?", (fixture.lease["id"],)
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(database)


def test_concurrent_creation_commits_one_receipt_and_original_response(fixture):
    command = LeaseCreateCommand(
        fixture.space_id,
        "residential",
        date.today(),
        None,
        date.today(),
        TermCommand(10000, "USD", "monthly", 1, 0),
        (ParticipantCommand(fixture.tenant_id, "primary_tenant"),),
    )
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _index: fixture.service.create(
                    command,
                    expected_revision=0,
                    idempotency_key=key,
                ),
                range(2),
            )
        )
    assert results[0] == results[1]
    with fixture.service.unit_of_work.engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM lease_command_operations WHERE idempotency_key=?",
                (key,),
            ).scalar_one()
            == 1
        )
    validate_latest_schema(fixture.workspace.paths.database)


def test_commit_failure_rolls_back_command_and_timeline(fixture):
    draft = _vacant_draft(fixture)
    before = fixture.portfolio.get_space_status(draft["spaceId"])
    key = str(uuid4())
    engine = fixture.service.unit_of_work.engine

    def fail_commit(_connection):
        raise RuntimeError("commit failed")

    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            fixture.service.execute(
                draft["id"],
                executed_on=date.today(),
                confirmed=True,
                expected_revision=before["revision"],
                expected_lease_revision=1,
                idempotency_key=key,
            )
    finally:
        event.remove(engine, "commit", fail_commit)
    assert fixture.service.get(draft["id"])["leaseRevision"] == 1
    assert fixture.service.get(draft["id"])["status"] == "draft"
    assert fixture.portfolio.get_space_status(draft["spaceId"])["revision"] == before["revision"]
    with pytest.raises(LeaseNotFoundError):
        fixture.service.get_command_operation(idempotency_key=key)
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize("tampering", ["receipt_audit", "source_result", "participant"])
def test_retained_history_rejects_tampering_with_exact_schema_preserved(fixture, tampering):
    database = fixture.workspace.paths.database
    with sqlite3.connect(database) as connection:
        if tampering == "receipt_audit":
            triggers = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='audit_events_no_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER audit_events_no_update")
            connection.execute(
                "UPDATE audit_events SET after_snapshot='{}' WHERE entity_type='lease_command_operation' AND entity_id=?",
                (fixture.lease["operationId"],),
            )
            connection.execute(triggers)
        elif tampering == "source_result":
            triggers = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='space_status_operations_conditional_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER space_status_operations_conditional_update")
            connection.execute(
                "UPDATE space_status_operations SET result_snapshot=json_set(result_snapshot, '$.consumerResult.notes', 'rewritten') WHERE id=?",
                (fixture.lease["operationId"],),
            )
            connection.execute(triggers)
        else:
            connection.execute(
                "UPDATE lease_participants SET notes='rewritten' WHERE lease_id=?",
                (fixture.lease["id"],),
            )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(database)
