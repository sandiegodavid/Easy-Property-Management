"""DASH grouping, live parity and query bounds over the real composed SQLite ports."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import event, update, text, select
from sqlalchemy.exc import DBAPIError

from app.bootstrap.operator_home import compose_home_sources
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.maintenance.tests import test_attention_reader as maintenance
from app.modules.tasks.tests import test_attention_reader as tasks
from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceIssueModel
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel
from app.modules.operator.application.home_contracts import (
    HomeQuery,
    AttentionQuery,
    CollectionQuery,
    HomeScope,
)
from app.modules.operator.application.home_service import HomeCompositionService
from app.modules.operator.application.home_vocabulary import Collection, SourceKind
from app.modules.operator.domain.models import (
    OperatorSectionUnavailable,
    OperatorStorageFailure,
    OperatorUnavailable,
)
from app.modules.finance.application.money_models import MoneyBusy
from app.modules.operator.infrastructure.home_unit_of_work import SQLiteHomeUnitOfWork
from app.modules.operator.tests import test_directories as fixtures
from app.modules.portfolio.application.attention_ports import PortfolioAttentionNotFound
from app.modules.finance.tests import test_money_summary as finance_fixtures
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.owner_management.tests import test_attention_reader as owners
from app.modules.parties.application.service import PartyCreateCommand
from app.modules.communications.infrastructure.sqlalchemy_models import (
    CommunicationModel,
    CommunicationLinkModel,
)
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.product_migrations import validate_latest_schema
from app.modules.portfolio.application.service import PortfolioService
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver

NOW = maintenance.NOW


@pytest.fixture
def context(tmp_path):
    base = fixtures.directory.__wrapped__(tmp_path)
    workspace, portfolio, _, support, _ = next(base)
    property_record = fixtures.property_record(portfolio)
    sources = compose_home_sources()
    uow = SQLiteHomeUnitOfWork(
        workspace.paths.database,
        sources,
        SQLiteAuditReadMarker(),
    )
    service = HomeCompositionService(uow, runtime=support.runtime, now=lambda: NOW)
    with uow.engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchall()
    yield service, sources, property_record
    uow.engine.dispose()
    next(base, None)


def home_query(**values):
    return HomeQuery(from_on="2026-10-01", through_on="2026-10-31", **values)


def populate(context, count=1, *, links=True):
    service, _, prop = context
    issues = [maintenance.issue(i, property_id=prop.id) for i in range(1, count + 1)]
    followups = [
        maintenance.task(1000 + i, i, due=NOW - timedelta(days=1)) for i in range(1, count + 1)
    ]
    maintenance.seed(service.unit_of_work.engine, issues, tasks=followups, links=links)
    return issues, followups


def test_full_home_live_parity_capture_and_read_only(context):
    service, _, _ = context
    populate(context)
    with service.unit_of_work.engine.begin() as connection:
        before = connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
    home = service.home(home_query())
    live = service.attention(AttentionQuery())
    assert home.needs_action == live.needs_action
    assert home.needs_action.matching_total == 1
    assert home.needs_action.items[0].property_name is not None
    assert live.priority_totals == {"overdue": 1}
    assert set(home.supported_sources) == set(SourceKind)
    assert home.money.status == home.inventory.status == "available"
    for section in Collection:
        assert getattr(home, section.value).capture.as_of == NOW
    assert home.money.capture.as_of == home.inventory.capture.as_of == NOW
    assert "PRIVATE" not in home.model_dump_json()
    with service.unit_of_work.engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == before


def test_all_source_streams_and_sections_respect_query_budgets(record_property):
    fixture = finance_fixtures.MoneySummaryTests()
    fixture.setUp()
    try:
        fixture.record_sources()
        sources = compose_home_sources()
        identity = RuntimeIdentity("ready", *fixture.identity, True)
        uow = SQLiteHomeUnitOfWork(fixture.db, sources, SQLiteAuditReadMarker())
        service = HomeCompositionService(uow, runtime=lambda: identity, now=lambda: NOW)
        owner = fixture.portfolio.create_party(PartyCreateCommand("individual", "Owner"))
        maintenance.seed(
            uow.engine,
            [maintenance.issue(i, property_id=fixture.property_id) for i in (1, 2)],
            appointments=[
                maintenance.appointment(
                    6000, 1, NOW - timedelta(hours=2), NOW - timedelta(hours=1)
                ),
                maintenance.appointment(
                    6001, 1, NOW + timedelta(hours=1), NOW + timedelta(hours=2)
                ),
            ],
            tasks=[
                maintenance.task(1001, 1, due=NOW - timedelta(days=1)),
                maintenance.task(1002, 2, waiting=True),
            ],
        )
        owners.seed(
            uow.engine,
            concerns=[
                owners.concern(i, property_id=fixture.property_id, owner_party_id=owner.id)
                for i in (3, 4)
            ],
            tasks=[
                owners.task(
                    1003, 3, due_at_utc=(NOW - timedelta(days=1)).isoformat(), due_timezone="UTC"
                ),
                owners.task(1004, 4, **owners.wait()),
            ],
            links=[(3, 1003), (4, 1004)],
            reports=[
                owners.report(
                    5,
                    owner_party_id=owner.id,
                    property_id=fixture.property_id,
                    space_id=fixture.lease["spaceId"],
                    lease_id=fixture.lease["id"],
                )
            ],
        )
        with uow.engine.begin() as connection:
            connection.execute(
                TaskModel.__table__.insert(),
                tasks.task(
                    1005,
                    related_entity_type="property",
                    related_entity_id=fixture.property_id,
                    due_at_utc=(NOW + timedelta(days=2)).isoformat(),
                    due_timezone="UTC",
                ),
            )
            connection.execute(
                update(LeaseModel).values(
                    contract_ends_on=(NOW.date() + timedelta(days=20)).isoformat()
                )
            )
        scope = HomeScope(kind="property", property_id=fixture.property_id)
        statements = []

        def collect(_connection, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(uow.engine, "before_cursor_execute", collect)
        home = service.home(home_query(scope=scope, limit_per_section=10))
        home_count = len(statements)
        assert all(getattr(home, name.value).status == "available" for name in Collection)
        assert home_count <= 64, home_count
        record_property("mixed_home_selects", home_count)
        assert {item.source.kind for item in home.needs_action.items} >= {
            "rent_expectation",
            "maintenance_issue",
            "maintenance_appointment",
            "owner_concern",
            "owner_rent_report",
            "lease",
        }
        assert home.waiting.matching_total == 2
        assert home.upcoming.matching_total == 2 and home.appointments.matching_total == 1
        statements.clear()
        live = service.attention(AttentionQuery(scope=scope, limit=10))
        assert live.needs_action == home.needs_action
        assert len(statements) <= 24, len(statements)
        record_property("mixed_live_selects", len(statements))
        assert home_count + len(statements) <= 88
        all_items, after = [], None
        while True:
            page = service.collection(
                CollectionQuery(scope=scope, collection="needs_action", limit=1),
                as_of=NOW,
                after=after,
            )
            all_items.extend(item.key for item in page.result.items)
            assert page.result.matching_total == home.needs_action.matching_total
            if page.next_key is None:
                break
            after = page.next_key
        assert all_items == [item.key for item in home.needs_action.items]
        event.remove(uow.engine, "before_cursor_execute", collect)
        uow.engine.dispose()
    finally:
        fixture.doCleanups()


def test_rollback_keeps_attention_unchanged(context):
    service, _, _ = context
    populate(context)
    before = service.attention(AttentionQuery())
    with service.unit_of_work.engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            update(TaskModel).values(status="completed", completed_at_utc=NOW.isoformat())
        )
        transaction.rollback()
    assert service.attention(AttentionQuery()) == before


def test_encrypted_restore_reconstructs_the_same_complete_home(tmp_path):
    fixture = finance_fixtures.MoneySummaryTests()
    fixture.setUp()
    try:
        fixture.record_sources()
        identity = RuntimeIdentity("ready", *fixture.identity, True)
        uow = SQLiteHomeUnitOfWork(fixture.db, compose_home_sources(), SQLiteAuditReadMarker())
        original = HomeCompositionService(uow, runtime=lambda: identity, now=lambda: NOW)
        before = original.home(home_query())
        validate_latest_schema(fixture.db)
        backup = BackupService(
            fixture.workspace,
            AuditRecorder(SQLiteAuditRepository(fixture.db)),
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        target = tmp_path / "restored-home"
        with fast_backup_encryption():
            archive = backup.create_backup(
                "home composition passphrase", output_path=tmp_path / "home.epmbackup"
            )
            backup.restore(archive.archive_path, "home composition passphrase", target)
        restored = WorkspacePaths(target).database
        validate_latest_schema(restored)
        new_identity = replace(identity, epoch=tasks.identity(99999))
        restored_uow = SQLiteHomeUnitOfWork(
            restored,
            compose_home_sources(),
            SQLiteAuditReadMarker(),
        )
        after = HomeCompositionService(
            restored_uow, runtime=lambda: new_identity, now=lambda: NOW
        ).home(home_query())
        for collection in Collection:
            restored_section, original_section = (
                getattr(after, collection.value),
                getattr(before, collection.value),
            )
            assert restored_section == original_section.model_copy(
                update={
                    "capture": original_section.capture.model_copy(
                        update={"source_revision": restored_section.capture.source_revision}
                    )
                }
            )
        for name in ("inventory", "money"):
            restored_section, original_section = getattr(after, name), getattr(before, name)
            assert restored_section == original_section.model_copy(
                update={
                    "capture": original_section.capture.model_copy(
                        update={"source_revision": restored_section.capture.source_revision}
                    )
                }
            )
        assert after.source_revision != before.source_revision
        assert after.runtime_epoch != before.runtime_epoch
        restored_uow.engine.dispose()
        uow.engine.dispose()
    finally:
        fixture.doCleanups()


def test_one_ten_fifty_properties_and_thousand_tasks_have_fixed_cost(context, record_property):
    service, _, prop = context
    sources = service.unit_of_work.sources
    statements = []

    def collect(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    # Source records use real persistent IDs; attention does not reload each Task/property.
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(
            TaskModel.__table__.insert(),
            [
                tasks.task(30000 + i, related_entity_type="property", related_entity_id=prop.id)
                for i in range(1000)
            ],
        )
    portfolio = sources.portfolio
    # Reuse the supported property fixture's service to create additional inventory.
    base_database = service.unit_of_work.engine.url.database
    portfolio_service = PortfolioService(
        SQLitePortfolioUnitOfWork(
            Path(base_database), AuditRecorder(SQLiteAuditRepository(Path(base_database)))
        ),
        time_zone_resolver=BundledAddressTimeZoneResolver(),
        now=lambda: NOW,
    )
    budgets = []
    for property_count in (1, 10, 50):
        while True:
            with service.unit_of_work.engine.connect() as connection:
                current = len(connection.execute(select(portfolio.properties())).all())
            if current >= property_count:
                break
            fixtures.property_record(portfolio_service, f"Property {current}")
        with service.unit_of_work.engine.begin() as connection:
            property_ids = [
                row.property_id for row in connection.execute(select(portfolio.properties()))
            ]
            connection.execute(
                text("UPDATE tasks SET related_entity_id=:property_id WHERE id=:task_id"),
                [
                    {
                        "property_id": property_ids[index % len(property_ids)],
                        "task_id": tasks.identity(30000 + index),
                    }
                    for index in range(1000)
                ],
            )
        event.listen(service.unit_of_work.engine, "before_cursor_execute", collect)
        try:
            statements.clear()
            home = service.home(home_query())
            assert home.needs_action.matching_total == 1000
            budgets.append(len(statements))
            record_property(f"home_selects_{property_count}_properties", len(statements))
        finally:
            event.remove(service.unit_of_work.engine, "before_cursor_execute", collect)
    assert len(set(budgets)) == 1 and budgets[0] <= 64


def test_grouping_before_limits_nested_reminders_and_terminal_fallback(context):
    service, _, _ = context
    issues, followups = populate(context, 12)
    engine = service.unit_of_work.engine
    with engine.begin() as connection:
        connection.execute(
            TaskReminderModel.__table__.insert(),
            [tasks.reminder(4000 + i, 1001, NOW - timedelta(minutes=i)) for i in range(1, 5)],
        )
    first = service.collection(CollectionQuery(collection="needs_action", limit=1))
    assert first.result.matching_total == 12
    seen, page = [], first
    while True:
        seen.extend(item.key for item in page.result.items)
        if page.next_key is None:
            break
        page = service.collection(
            CollectionQuery(collection="needs_action", limit=1), as_of=NOW, after=page.next_key
        )
        assert page.result.matching_total == 12
    assert len(seen) == len(set(seen)) == 12
    grouped = service.attention(AttentionQuery(limit=10)).needs_action
    item = next(item for item in grouped.items if item.source.id == UUID(issues[0]["id"]))
    child = item.children[0]
    assert child.child_count == 4 and len(child.children) == 3
    assert all(reminder.target == child.target for reminder in child.children)
    with engine.begin() as connection:
        connection.execute(
            update(MaintenanceIssueModel)
            .where(MaintenanceIssueModel.id == issues[0]["id"])
            .values(status="resolved", resolved_at=NOW.isoformat(), resolution_summary="Fixed")
        )
    result = service.collection(CollectionQuery(collection="needs_action", limit=100)).result
    assert result.matching_total == 12
    fallback = next(item for item in result.items if item.source.kind == "task")
    assert str(fallback.source.id) == followups[0]["id"] and fallback.child_count == 4
    assert fallback.related_source.source.id == UUID(issues[0]["id"])
    assert fallback.related_source.active is False


def test_multiple_followups_keep_actionable_children_ahead_of_waiting_preview(context):
    service, _, prop = context
    maintenance.seed(
        service.unit_of_work.engine,
        [maintenance.issue(1, property_id=prop.id)],
        tasks=[maintenance.task(1000 + i, 1, waiting=True) for i in range(1, 5)]
        + [maintenance.task(1005, 1, due=NOW - timedelta(days=1))],
    )
    result = service.attention(AttentionQuery())
    assert result.needs_action.matching_total == 1
    item = result.needs_action.items[0]
    assert item.child_count == 5 and len(item.children) == 3
    assert item.children[0].id == UUID(tasks.identity(1005))
    assert item.children[0].reasons[0].code == "overdue"
    assert item.child_detail_target == item.next_action.target


def test_invalid_source_discriminator_fails_collection_instead_of_double_counting(context):
    service, sources, _ = context
    populate(context)
    with service.unit_of_work.engine.begin() as connection:
        page = sources.tasks.attention(connection, tasks.window())
    with patch.object(sources.rent, "attention", return_value=page):
        home = service.home(home_query())
    assert home.needs_action.reason_code == "source_contract_invalid"
    assert home.waiting.status == "available"


def test_generic_context_does_not_group_and_property_scope_excludes_unlinked(context):
    service, _, prop = context
    populate(context, links=False)
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(TaskModel.__table__.insert(), tasks.task(5000))
    assert service.attention(AttentionQuery()).needs_action.matching_total == 3
    scoped = AttentionQuery(scope=HomeScope(kind="property", property_id=prop.id))
    assert service.attention(scoped).needs_action.matching_total == 2
    with pytest.raises(PortfolioAttentionNotFound):
        service.attention(
            AttentionQuery(scope=HomeScope(kind="property", property_id=UUID(int=9000)))
        )


def test_communication_task_membership_uses_source_links_without_grouping(context):
    service, _, prop = context
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(
            CommunicationModel.__table__.insert(),
            dict(
                id=tasks.identity(6000),
                direction="inbound",
                channel="email",
                subject="Message",
                body="PRIVATE BODY",
                occurred_at_utc=NOW.isoformat(),
                occurred_timezone="UTC",
                status="recorded",
                recorded_at=NOW.isoformat(),
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
                revision=1,
            ),
        )
        connection.execute(
            CommunicationLinkModel.__table__.insert(),
            dict(
                id=tasks.identity(6001),
                communication_id=tasks.identity(6000),
                entity_type="property",
                entity_id=prop.id,
            ),
        )
        connection.execute(
            TaskModel.__table__.insert(),
            tasks.task(
                6002, related_entity_type="communication", related_entity_id=tasks.identity(6000)
            ),
        )
    result = service.attention(
        AttentionQuery(scope=HomeScope(kind="property", property_id=prop.id))
    )
    assert result.needs_action.matching_total == 1
    assert result.needs_action.items[0].source.kind == "task"
    assert result.needs_action.items[0].property_id == UUID(prop.id)
    assert "PRIVATE BODY" not in result.model_dump_json()


def test_source_failure_dependencies_and_live_omits_expensive_sections(context):
    service, sources, _ = context
    with patch.object(
        sources.coverage, "attention", side_effect=OperatorSectionUnavailable("offline")
    ):
        home = service.home(home_query())
        assert home.information_review.status == "unavailable"
        assert home.needs_action.status == "available"
        with patch.object(sources.money, "summary", side_effect=AssertionError("money read")):
            assert service.attention(AttentionQuery()).needs_action.status == "available"
    with patch.object(
        sources.maintenance, "attention", side_effect=OperatorSectionUnavailable("offline")
    ):
        home = service.home(home_query())
        assert (
            home.needs_action.status == home.waiting.status == home.upcoming.status == "unavailable"
        )
        assert (
            home.information_review.status
            == home.money.status
            == home.inventory.status
            == "available"
        )
        assert home.appointments.status == "unavailable"
    service.unit_of_work.sources = replace(sources, rent=None)
    home = service.home(home_query())
    assert home.needs_action.reason_code == "adapter_missing"
    assert home.waiting.status == home.appointments.status == "available"


def test_storage_failure_is_whole_request_failure(context):
    service, sources, _ = context
    with patch.object(
        sources.tasks,
        "standalone_attention",
        side_effect=DBAPIError("select", {}, Exception("broken")),
    ):
        with pytest.raises(OperatorStorageFailure):
            service.home(home_query())


def test_money_wrapped_database_failure_is_whole_request_failure(context):
    service, sources, _ = context
    failure = MoneyBusy("Workspace storage is busy.")
    failure.__cause__ = DBAPIError("select", {}, Exception("database is locked"))
    with patch.object(sources.money, "summary", side_effect=failure):
        with pytest.raises(OperatorUnavailable):
            service.home(home_query())


def test_composition_passes_the_captured_runtime_identity_to_money(context):
    service, _, _ = context
    before = service.home(home_query())
    next_identity = replace(service.runtime(), epoch=tasks.identity(77777))
    service.runtime = lambda: next_identity
    after = service.home(home_query())
    assert after.runtime_epoch == UUID(next_identity.epoch)
    assert after.money.metrics == before.money.metrics
    assert after.money.capture.source_revision != before.money.capture.source_revision


def test_counts_rows_and_status_share_snapshot_during_concurrent_write(context):
    service, _, _ = context
    issues, _ = populate(context)
    marker = service.unit_of_work.marker
    original = marker.marker

    def change_after_capture(connection):
        result = original(connection)
        with service.unit_of_work.engine.begin() as writer:
            writer.execute(
                update(TaskModel).values(status="completed", completed_at_utc=NOW.isoformat())
            )
            writer.execute(
                update(MaintenanceIssueModel)
                .where(MaintenanceIssueModel.id == issues[0]["id"])
                .values(status="resolved", resolved_at=NOW.isoformat(), resolution_summary="Done")
            )
        return result

    with patch.object(marker, "marker", side_effect=change_after_capture):
        result = service.attention(AttentionQuery())
    assert result.needs_action.matching_total == 1
    assert result.needs_action.items[0].children[0].source_status == "open"
    assert service.attention(AttentionQuery()).needs_action.matching_total == 0


def test_query_cost_constant_and_bounded_for_grouped_pages(context):
    service, _, _ = context
    statements = []

    def collect(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    populate(context)
    event.listen(service.unit_of_work.engine, "before_cursor_execute", collect)
    try:
        service.attention(AttentionQuery())
        one_live = len(statements)
        statements.clear()
        service.home(home_query())
        one_home = len(statements)
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", collect)
    # Insert a second, larger set without reusing logical identities.
    _, _, prop = context
    maintenance.seed(
        service.unit_of_work.engine,
        [maintenance.issue(i, property_id=prop.id) for i in range(2, 52)],
        tasks=[maintenance.task(1000 + i, i, due=NOW - timedelta(days=1)) for i in range(2, 52)],
    )
    event.listen(service.unit_of_work.engine, "before_cursor_execute", collect)
    try:
        statements.clear()
        live = service.attention(AttentionQuery())
        assert live.needs_action.matching_total == 51
        assert len(statements) == one_live <= 24
        statements.clear()
        service.home(home_query())
        assert len(statements) == one_home <= 64
        statements.clear()
        service.collection(CollectionQuery(collection="needs_action", limit=100))
        assert len(statements) <= 24
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", collect)
