from sqlalchemy import inspect, text
from app.platform.migration_errors import MigrationSchemaError
from .sqlalchemy_models import OwnerConcernFollowUpOperationModel, OwnerConcernModel

def validate_owner_concern_schema(connection):
    inspector=inspect(connection)
    for model in (OwnerConcernModel,OwnerConcernFollowUpOperationModel):
        if not inspector.has_table(model.__tablename__): raise MigrationSchemaError("Owner-management schema is missing.")
        if {item["name"] for item in inspector.get_columns(model.__tablename__)} != {item.name for item in model.__table__.columns}: raise MigrationSchemaError("Owner-management columns are incompatible.")
    triggers={row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='owner_concern_follow_up_operations'"))}
    if triggers!={"owner_concern_follow_up_operations_no_update","owner_concern_follow_up_operations_no_delete"}: raise MigrationSchemaError("Owner-management operation triggers are incompatible.")
    checks=(
      ("SELECT 1 FROM owner_concerns c WHERE c.status IN ('open','in_progress') AND NOT EXISTS(SELECT 1 FROM properties p WHERE p.id=c.property_id) LIMIT 1","Owner concern property references are invalid."),
      ("SELECT 1 FROM owner_concerns c WHERE c.replaces_concern_id=c.id OR (c.replaces_concern_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM owner_concerns source WHERE source.id=c.replaces_concern_id)) LIMIT 1","Owner concern replacement lineage is invalid."),
      ("SELECT 1 FROM owner_concern_follow_up_operations o LEFT JOIN owner_concerns c ON c.id=o.concern_id LEFT JOIN tasks t ON t.id=o.task_id WHERE c.id IS NULL OR (o.task_id IS NOT NULL AND (t.id IS NULL OR t.related_entity_type!='owner_concern' OR t.related_entity_id!=o.concern_id)) LIMIT 1","Owner concern follow-up references are invalid."),
      ("SELECT 1 FROM owner_concerns c WHERE NOT EXISTS(SELECT 1 FROM audit_events e WHERE e.entity_type='owner_concern' AND e.entity_id=c.id AND e.action='created') LIMIT 1","Owner concern audit history is incomplete."),
      ("SELECT 1 FROM owner_concern_follow_up_operations o WHERE NOT EXISTS(SELECT 1 FROM audit_events e WHERE e.entity_type='owner_concern_follow_up_operation' AND e.entity_id=o.id AND e.action='created' AND e.correlation_id=o.correlation_id) LIMIT 1","Owner concern follow-up audit history is incomplete."),
    )
    for query,message in checks:
        if connection.execute(text(query)).first(): raise MigrationSchemaError(message)
