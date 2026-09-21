from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect, text
from app.platform.migration_errors import MigrationSchemaError
from .sqlalchemy_models import OwnerRentReportModel, OwnerRentReportOperationModel

MODELS=(OwnerRentReportModel,OwnerRentReportOperationModel)
def validate_owner_accounting_schema(connection):
    inspector=inspect(connection)
    for model in MODELS:
        table=model.__table__
        if not inspector.has_table(table.name):raise MigrationSchemaError("Owner-accounting schema is missing.")
        columns={item["name"]:item for item in inspector.get_columns(table.name)}
        if set(columns)!={column.name for column in table.columns}:raise MigrationSchemaError("Owner-accounting columns are incompatible.")
        expected_fks={(tuple(element.parent.name for element in item.elements),item.elements[0].column.table.name,tuple(element.column.name for element in item.elements)) for item in table.constraints if isinstance(item,ForeignKeyConstraint)}
        actual_fks={(tuple(item["constrained_columns"]),item["referred_table"],tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table.name)}
        if actual_fks!=expected_fks:raise MigrationSchemaError("Owner-accounting foreign keys are incompatible.")
        expected_indexes={item.name:(tuple(column.name for column in item.columns),bool(item.unique)) for item in table.indexes};actual_indexes={item["name"]:(tuple(item["column_names"]),bool(item.get("unique"))) for item in inspector.get_indexes(table.name)}
        if actual_indexes!=expected_indexes:raise MigrationSchemaError("Owner-accounting indexes are incompatible.")
        expected_unique={tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item,UniqueConstraint)};actual_unique={tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        if actual_unique!=expected_unique:raise MigrationSchemaError("Owner-accounting unique constraints are incompatible.")
        expected_checks={_normalise(item.sqltext.text) for item in table.constraints if isinstance(item,CheckConstraint)};actual_checks={_normalise(item.get("sqltext") or "") for item in inspector.get_check_constraints(table.name)}
        if expected_checks!=actual_checks:raise MigrationSchemaError("Owner-accounting checks are incompatible.")
    triggers={name:_normalise(sql) for name,sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='owner_rent_report_operations'")}
    expected={"owner_rent_report_operations_no_update":_normalise("CREATE TRIGGER owner_rent_report_operations_no_update BEFORE UPDATE ON owner_rent_report_operations BEGIN SELECT RAISE(ABORT, 'owner rent report operations are immutable'); END"),"owner_rent_report_operations_no_delete":_normalise("CREATE TRIGGER owner_rent_report_operations_no_delete BEFORE DELETE ON owner_rent_report_operations BEGIN SELECT RAISE(ABORT, 'owner rent report operations are immutable'); END")}
    if triggers!=expected:raise MigrationSchemaError("Owner-accounting operation triggers are incompatible.")
    bad=connection.execute(text("""SELECT 1 FROM owner_rent_reports report
        LEFT JOIN rent_receipts receipt ON receipt.id=report.verified_receipt_id
        WHERE (report.status='verified' AND (receipt.id IS NULL OR report.lease_id!=receipt.lease_id OR report.owner_party_id!=receipt.received_by_party_id OR report.received_on!=receipt.received_on OR report.amount_minor!=receipt.amount_minor OR report.currency_code!=receipt.currency_code OR report.payment_method_kind!=receipt.payment_method_kind OR COALESCE(report.payment_method_label,'')!=COALESCE(receipt.payment_method_label,'') OR COALESCE(report.masked_reference,'')!=COALESCE(receipt.masked_reference,'') OR COALESCE(report.other_payment_method_note,'')!=COALESCE(receipt.other_payment_method_note,''))) LIMIT 1""")).first()
    if bad:raise MigrationSchemaError("Owner-accounting receipt links are incompatible.")
    # The mutable report rows are not the source of truth for workflow history.
    # A restored workspace must retain both its append-only operation retry
    # record and the correlated audit evidence for every state transition.
    checks=(
        ("""SELECT 1 FROM owner_rent_report_operations operation LEFT JOIN audit_events event
             ON event.entity_type='owner_rent_report_operation' AND event.entity_id=operation.id
             AND event.correlation_id=operation.correlation_id AND event.action='recorded'
             WHERE event.id IS NULL LIMIT 1""", "Owner-accounting operation audit history is incomplete."),
        ("""SELECT 1 FROM owner_rent_report_operations operation
             LEFT JOIN audit_events report_event ON report_event.entity_type='owner_rent_report'
             AND report_event.entity_id=operation.report_id
             AND report_event.correlation_id=operation.correlation_id
             AND report_event.action=CASE operation.action
                WHEN 'create' THEN 'created' WHEN 'patch' THEN 'patched'
                WHEN 'verify' THEN 'verified' WHEN 'reject' THEN 'rejected' END
             WHERE report_event.id IS NULL LIMIT 1""", "Owner-accounting report audit correlation is incomplete."),
        ("""SELECT 1 FROM owner_rent_reports report WHERE NOT EXISTS (
             SELECT 1 FROM owner_rent_report_operations operation
             WHERE operation.report_id=report.id AND operation.action='create'
           ) LIMIT 1""", "Owner-accounting creation history is incomplete."),
        ("""WITH RECURSIVE chain(start_id, id, path, cycle) AS (
             SELECT id, replaces_report_id, ',' || id || ',', 0 FROM owner_rent_reports
             UNION ALL
             SELECT chain.start_id, report.replaces_report_id, chain.path || report.id || ',',
                    instr(chain.path, ',' || report.id || ',') > 0
             FROM chain JOIN owner_rent_reports report ON report.id=chain.id
             WHERE chain.id IS NOT NULL AND cycle=0
           ) SELECT 1 FROM chain WHERE cycle=1 LIMIT 1""", "Owner-accounting report replacement chain is cyclic."),
        ("""SELECT 1 FROM owner_rent_report_operations operation
             LEFT JOIN owner_rent_reports report ON report.id=operation.report_id
             WHERE report.id IS NULL OR (operation.action='verify' AND operation.result_receipt_id IS NULL)
             OR (operation.action!='verify' AND operation.result_receipt_id IS NOT NULL) LIMIT 1""", "Owner-accounting operation records are incompatible."),
        ("""SELECT 1 FROM owner_rent_reports replacement
             JOIN owner_rent_reports predecessor ON predecessor.id=replacement.replaces_report_id
             LEFT JOIN rent_receipts old_receipt ON old_receipt.id=predecessor.verified_receipt_id
             LEFT JOIN rent_receipts new_receipt ON new_receipt.id=replacement.verified_receipt_id
             WHERE replacement.status='verified' AND predecessor.status='verified'
             AND (old_receipt.voided_at IS NULL OR new_receipt.replaces_receipt_id!=old_receipt.id) LIMIT 1""", "Owner-accounting replacement receipt lineage is incompatible."),
        ("""SELECT 1 FROM owner_rent_reports report WHERE report.status='verified' AND NOT EXISTS (
             SELECT 1 FROM owner_rent_report_operations operation
             JOIN audit_events event ON event.entity_type='owner_rent_report'
             AND event.entity_id=report.id AND event.action='verified'
             AND event.correlation_id=operation.correlation_id
             JOIN json_each(event.after_snapshot, '$.verificationEvidence') evidence
             WHERE operation.report_id=report.id AND operation.action='verify'
             AND json_extract(evidence.value,'$.active')=1
             AND json_extract(evidence.value,'$.available')=1
             AND json_extract(evidence.value,'$.linkId') IS NOT NULL
             AND json_extract(evidence.value,'$.fileId') IS NOT NULL
           ) LIMIT 1""", "Owner-accounting verified evidence history is incomplete."),
        ("""SELECT 1 FROM owner_rent_report_operations operation
             WHERE operation.action='verify' AND operation.receipt_created=1 AND NOT EXISTS (
               SELECT 1 FROM audit_events event
               WHERE event.entity_type='rent_receipt' AND event.entity_id=operation.result_receipt_id
               AND event.action='recorded' AND event.correlation_id=operation.correlation_id
             ) LIMIT 1""", "Owner-accounting created receipt audit history is incomplete."),
        ("""SELECT 1 FROM owner_rent_report_operations operation
             JOIN rent_receipt_allocations allocation ON allocation.receipt_id=operation.result_receipt_id
             LEFT JOIN audit_events event ON event.entity_type='rent_receipt_allocation'
             AND event.entity_id=allocation.id AND event.action='created'
             AND event.correlation_id=operation.correlation_id
             WHERE operation.action='verify' AND operation.receipt_created=1 AND event.id IS NULL LIMIT 1""", "Owner-accounting created receipt allocation audit history is incomplete."),
    )
    for query, message in checks:
        if connection.execute(text(query)).first(): raise MigrationSchemaError(message)
def _normalise(value):return " ".join(str(value).replace('"','').replace('`','').lower().split())
