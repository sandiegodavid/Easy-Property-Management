"""Filled source graphs prove metadata privacy and composed Finance semantics."""

from app.modules.portfolio.tests.commands import inventory_command

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.modules.finance.tests import test_money_summary as fixtures
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.directory_service import OperatorDirectoryService
from app.modules.operator.application.overview_service import OperatorOverviewService
from app.modules.operator.api.overview_contracts import OverviewResponse
from app.modules.operator.infrastructure.unit_of_work import (
    OperatorReadSources,
    SQLiteOperatorUnitOfWork,
)
from app.modules.operator.infrastructure.overview_sources import OverviewSources
from app.modules.portfolio.infrastructure.directory_reader import SQLitePortfolioDirectoryReader
from app.modules.portfolio.infrastructure.owner_context_reader import SQLiteOwnerContextReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.application.service import PartyCreateCommand, OwnershipInput
from app.modules.parties.infrastructure.identity_relations import SQLitePartyIdentityRelations
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.leases.infrastructure.participant_relations import SQLiteLeaseParticipantRelations
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.leases.infrastructure.summary_reader import SQLiteLeaseSummaryReader
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.finance.infrastructure.money_context_reader import SQLiteMoneyContextReader
from app.modules.finance.infrastructure.expense_context_reader import SQLiteExpenseContextReader
from app.modules.maintenance.infrastructure.summary_reader import SQLiteIssueSummaryReader
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceUnitOfWork
from app.modules.maintenance.application.service import MaintenanceService
from app.modules.maintenance.domain.models import IssueCreate, ReporterAttribution
from app.modules.communications.infrastructure.summary_reader import (
    SQLiteCommunicationSummaryReader,
)
from app.modules.communications.infrastructure.link_reader import SQLiteCommunicationLinkReader
from app.modules.communications.infrastructure.unit_of_work import SQLiteCommunicationUnitOfWork
from app.modules.communications.application.service import (
    CommunicationService,
    CommunicationCommand,
    ParticipantInput,
    LinkInput,
    FollowUpInput,
)
from app.modules.owner_management.infrastructure.summary_reader import (
    SQLiteOwnerConcernSummaryReader,
)
from app.modules.owner_management.infrastructure.unit_of_work import SQLiteOwnerConcernUnitOfWork
from app.modules.owner_management.application.service import OwnerConcernService
from app.modules.owner_management.domain.models import ConcernCreateCommand
from app.modules.tasks.infrastructure.summary_reader import SQLiteTaskSummaryReader
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.application.waiting_service import TaskWaitingService
from app.modules.tasks.application.waiting import WaitingCommand
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.vendors.infrastructure.context_reader import SQLiteProviderContextReader
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.bootstrap.owner_concern_context import SQLiteOwnerConcernContext
from app.platform.product_migrations import validate_latest_schema
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.finance.infrastructure.context_relations import SQLiteFinanceContextRelations
from app.modules.operator.domain.models import OperatorConflict

CONTEXT_COMMUNICATIONS = 2
CONTEXT_TASKS = 2
OVERVIEW_STATEMENT_BUDGET = 50


@pytest.fixture
def populated():
    fixture = fixtures.MoneySummaryTests()
    fixture.setUp()
    fixture.record_sources(deposits=False)
    database = fixture.db
    recorder = AuditRecorder(SQLiteAuditRepository(database))
    captured = datetime(2026, 10, 6, 12, tzinfo=UTC)
    party = fixture.portfolio.create_party(PartyCreateCommand("individual", "Client owner"))
    inventory_command(
        fixture.portfolio,
        "replace_ownerships",
        fixture.property_id,
        (OwnershipInput("client_owner", party.id), OwnershipInput("local_operator")),
        "2026-01-02",
    )
    maintenance = MaintenanceService(
        SQLiteMaintenanceUnitOfWork(
            database,
            recorder,
            SQLitePortfolioContextReader(),
            SQLiteExpenseContextReader(),
            SQLiteTaskContextReader(),
            SQLiteTaskTransactionOperations(),
            SQLiteFileLinkReader(),
            SQLitePartyOperations(database),
            SQLiteLeaseContextReader(),
            SQLiteCommunicationLinkReader(),
            SQLiteProviderContextReader(),
        )
    )
    issue = maintenance.create_issue(
        IssueCreate(
            fixture.property_id,
            None,
            "Repair",
            "Private detailed narrative",
            "plumbing",
            None,
            "high",
            "2026-01-05T20:00:00+00:00",
            ReporterAttribution("manager", "local_operator"),
        ),
        str(uuid4()),
        expected_revision=0,
    )
    communications = CommunicationService(
        SQLiteCommunicationUnitOfWork(
            database,
            recorder,
            SQLiteCommunicationContextOperations(
                SQLiteTaskTransactionOperations(), SQLiteIntakeSourceReader()
            ),
        )
    )
    communication = communications.create(
        CommunicationCommand(
            "inbound",
            "email",
            "Owner update",
            "Private communication body",
            "2026-01-05T20:00:00+00:00",
            "America/Los_Angeles",
            (ParticipantInput(party.id, "sender"),),
            (
                LinkInput("property", fixture.property_id),
                LinkInput("lease", fixture.lease["id"]),
                LinkInput("maintenance_issue", issue["id"]),
            ),
            follow_up=FollowUpInput("Communication follow-up", "Private follow-up notes"),
            record=True,
        ),
        str(uuid4()),
        expected_revision=0,
    )
    communications.create(
        CommunicationCommand(
            "inbound",
            "email",
            "Rent receipt update",
            "Private receipt body",
            "2026-01-06T20:00:00+00:00",
            "America/Los_Angeles",
            (ParticipantInput(fixture.tenant["id"], "sender"),),
            (LinkInput("rent_receipt", fixture.receipt["id"]),),
            record=True,
        ),
        str(uuid4()),
        expected_revision=0,
    )
    concerns = OwnerConcernService(
        SQLiteOwnerConcernUnitOfWork(
            database, recorder, SQLiteOwnerConcernContext(SQLiteTaskTransactionOperations())
        ),
        now=lambda: captured,
    )
    concern = concerns.create(
        ConcernCreateCommand(
            owner_party_id=party.id,
            property_id=fixture.property_id,
            concern_type="general_rental",
            summary="Concern",
            description="Private owner description",
            raised_at_utc="2026-01-05T20:00:00+00:00",
            idempotency_key=str(uuid4()),
        ),
        expected_revision=0,
    )
    tasks = TaskService(SQLiteTaskUnitOfWork(database, recorder), now=lambda: captured)
    task = tasks.create(
        {
            "title": "Follow up",
            "notes": "Private task notes",
            "relatedEntityType": "owner_concern",
            "relatedEntityId": concern["id"],
        }
    )
    waiting = TaskWaitingService(
        tasks.unit_of_work, read_identity=lambda: fixture.identity, now=lambda: captured
    )
    waiting.mutate(
        WaitingCommand(
            task.id,
            "set",
            task.revision,
            str(uuid4()),
            kind="person",
            label="Client owner",
            follow_up_at="2026-10-01T12:00:00+00:00",
            timezone="UTC",
        )
    )
    locations = SQLitePortfolioLocationRelations()
    leases = SQLiteLeaseLocationRelation(locations)
    source_ports = OverviewSources(
        SQLiteOwnerContextReader(SQLitePartyIdentityRelations()),
        locations,
        leases,
        SQLiteLeaseSummaryReader(leases),
        SQLiteIssueSummaryReader(),
        SQLiteCommunicationSummaryReader(),
        SQLiteTaskSummaryReader(),
        SQLiteOwnerConcernSummaryReader(),
        SQLiteFinanceContextRelations(leases),
    )
    uow = SQLiteOperatorUnitOfWork(
        database,
        recorder,
        None,
        SQLiteAuditReadMarker(),
        sources=OperatorReadSources(
            directory=SQLitePortfolioDirectoryReader(
                SQLitePartyIdentityRelations(), SQLiteLeaseParticipantRelations()
            ),
            money=SQLiteMoneyContextReader(locations, leases, SQLiteAuditReadMarker()),
            overview=source_ports,
        ),
    )
    identity = RuntimeIdentity("ready", fixture.identity[0], fixture.identity[1], True)
    overview = OperatorOverviewService(uow, runtime=lambda: identity, now=lambda: captured)
    directory = OperatorDirectoryService(uow, runtime=lambda: identity, now=lambda: captured)
    yield fixture, overview, directory, party, issue, communication, concern, task
    uow.engine.dispose()
    for service in (communications, concerns, tasks):
        service.unit_of_work.engine.dispose()
    fixture.doCleanups()


def test_filled_sections_match_source_money_and_exclude_sensitive_detail(populated):
    fixture, overview, directory, party, issue, communication, concern, task = populated
    response = overview.overview(
        "owner", party.id, from_on=fixture.query.from_on, through_on=fixture.query.through_on
    )
    sections = response["sections"]
    assert sections["leases"]["items"][0]["id"] == fixture.lease["id"]
    assert sections["leases"]["items"][0]["isCurrent"] is True
    assert sections["maintenance"]["items"][0]["id"] == issue["id"]
    assert sections["communications"]["matchingTotal"] == CONTEXT_COMMUNICATIONS
    assert communication["id"] in {item["id"] for item in sections["communications"]["items"]}
    assert sections["concerns"]["items"][0]["id"] == concern["id"]
    assert sections["tasks"]["matchingTotal"] == CONTEXT_TASKS
    waiting_task = next(item for item in sections["tasks"]["items"] if item["id"] == task.id)
    assert waiting_task["followUpActionable"] is True
    assert waiting_task["waitingForKind"] == "person"
    property_response = overview.overview("property", fixture.property_id)
    assert (
        property_response["sections"]["communications"]["matchingTotal"] == CONTEXT_COMMUNICATIONS
    )
    assert property_response["sections"]["tasks"]["matchingTotal"] == CONTEXT_TASKS
    expected = fixture.reader.summary(fixture.query)
    assert (
        sections["money"]["summary"]["operating"]["rent_received"]
        == expected.operating.rent_received
    )
    assert (
        sections["money"]["summary"]["operating"]["expenses_paid"]
        == expected.operating.expenses_paid
    )
    assert "Private" not in str(response)
    assert all(section["asOf"] == response["asOf"] for section in sections.values())
    assert all(
        section["sourceRevision"] == response["sourceRevision"]
        for section in sections.values()
        if section["availability"] == "available"
    )
    OverviewResponse.model_validate(response)
    assert (
        directory.owners(text=fixture.tenant["displayName"])["matchingTotal"] == 0
    )  # Owner search does not index tenant narratives.
    validate_latest_schema(fixture.db)


def test_terminal_sources_only_appear_in_explicit_history(populated):
    fixture, overview, _, party, issue, _, _, task = populated
    service = TaskService(
        SQLiteTaskUnitOfWork(fixture.db, AuditRecorder(SQLiteAuditRepository(fixture.db))),
        now=overview.now,
    )
    try:
        service.transition(task.id, "completed")
        assert (
            overview.overview("owner", party.id, section="tasks")["sections"]["tasks"][
                "matchingTotal"
            ]
            == 1
        )
        history = overview.overview("owner", party.id, relationship_scope="all", section="tasks")
        assert (
            next(item for item in history["sections"]["tasks"]["items"] if item["id"] == task.id)[
                "status"
            ]
            == "completed"
        )
        OverviewResponse.model_validate(history)
    finally:
        service.unit_of_work.engine.dispose()


def test_task_linked_conversation_is_in_property_context(populated):
    fixture, overview, _, _, _, _, _, task = populated
    service = CommunicationService(
        SQLiteCommunicationUnitOfWork(
            fixture.db,
            AuditRecorder(SQLiteAuditRepository(fixture.db)),
            SQLiteCommunicationContextOperations(
                SQLiteTaskTransactionOperations(), SQLiteIntakeSourceReader()
            ),
        )
    )
    try:
        item = service.create(
            CommunicationCommand(
                "inbound",
                "email",
                "Task update",
                "Private body",
                "2026-01-07T20:00:00+00:00",
                "UTC",
                (ParticipantInput(fixture.tenant["id"], "sender"),),
                (LinkInput("task", task.id),),
                record=True,
            ),
            str(uuid4()),
            expected_revision=0,
        )
        section = overview.overview("property", fixture.property_id, section="communications")[
            "sections"
        ]["communications"]
        assert section["matchingTotal"] == CONTEXT_COMMUNICATIONS + 1
        assert item["id"] in {row["id"] for row in section["items"]}
    finally:
        service.unit_of_work.engine.dispose()


def test_populated_context_uses_one_connection_and_indexed_bounded_selections(populated):
    fixture, overview, _, party, _, _, _, _ = populated
    connections, statements = [], []

    def connected(connection):
        connections.append(connection)

    def executed(_conn, _cursor, statement, parameters, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    event.listen(Engine, "engine_connect", connected)
    event.listen(overview.unit_of_work.engine, "before_cursor_execute", executed)
    try:
        response = overview.overview(
            "owner",
            party.id,
            limit=1,
            from_on=fixture.query.from_on,
            through_on=fixture.query.through_on,
        )
    finally:
        event.remove(Engine, "engine_connect", connected)
        event.remove(overview.unit_of_work.engine, "before_cursor_execute", executed)
    assert len(connections) == 1
    assert len(statements) <= OVERVIEW_STATEMENT_BUDGET
    assert response["sections"]["communications"]["matchingTotal"] == CONTEXT_COMMUNICATIONS
    selections = [(sql, params) for sql, params in statements if "LIMIT" in sql]
    assert selections
    with overview.unit_of_work.engine.connect() as connection:
        plans = [
            row[3]
            for sql, params in selections
            for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params)
        ]
    assert any("property_ownerships_party_active" in detail for detail in plans), plans
    assert any("SEARCH communication_links USING COVERING INDEX" in detail for detail in plans)
    assert any("communications_status_occurred" in detail for detail in plans), plans


@fast_backup_encryption()
def test_encrypted_restore_preserves_contexts_and_invalidates_previous_epoch(populated, tmp_path):
    fixture, overview, directory, party, _, _, _, _ = populated
    filters = {"from_on": fixture.query.from_on, "through_on": fixture.query.through_on, "limit": 1}
    before = overview.overview("owner", party.id, **filters)
    old_cursor = before["sections"]["tasks"]["nextCursor"]
    assert old_cursor is not None
    directory_before = directory.owners()
    recorder = AuditRecorder(SQLiteAuditRepository(fixture.db))
    backup = BackupService(
        fixture.workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    passphrase = "a sufficiently long contextual backup passphrase"
    archive = backup.create_backup(passphrase, output_path=tmp_path / "contexts.epm-backup")
    restored = tmp_path / "restored-contexts"
    backup.restore(archive.archive_path, passphrase, restored)
    database = restored / "database" / "property-management.sqlite"
    new_identity = RuntimeIdentity("ready", fixture.identity[0], str(uuid4()), True)
    restored_uow = SQLiteOperatorUnitOfWork(
        database,
        AuditRecorder(SQLiteAuditRepository(database)),
        None,
        SQLiteAuditReadMarker(),
        sources=overview.unit_of_work.sources,
    )
    try:
        restored_overview = OperatorOverviewService(
            restored_uow, runtime=lambda: new_identity, now=overview.now
        )
        restored_directory = OperatorDirectoryService(
            restored_uow, runtime=lambda: new_identity, now=directory.now
        )
        after = restored_overview.overview("owner", party.id, **filters)
        assert after["subject"] == before["subject"]
        assert restored_directory.owners()["items"] == directory_before["items"]
        for name, section in before["sections"].items():
            assert after["sections"][name]["availability"] == section["availability"]
            if "items" in section:
                assert after["sections"][name]["items"] == section["items"]
                assert after["sections"][name]["matchingTotal"] == section["matchingTotal"]
        assert (
            after["sections"]["money"]["summary"]["operating"]
            == before["sections"]["money"]["summary"]["operating"]
        )
        assert after["sourceRevision"] != before["sourceRevision"]
        with pytest.raises(OperatorConflict):
            restored_overview.overview(
                "owner", party.id, section="tasks", cursor=old_cursor, **filters
            )
        validate_latest_schema(database)
    finally:
        restored_uow.engine.dispose()
