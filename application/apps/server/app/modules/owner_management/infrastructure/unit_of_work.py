from collections.abc import Callable
from typing import Any, TypeVar
from sqlalchemy import case, select
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.owner_management.domain.models import Concern
from app.modules.owner_management.infrastructure.sqlalchemy_models import OwnerConcernFollowUpOperationModel, OwnerConcernModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")

class SQLiteOwnerConcernUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder, context) -> None:
        self.engine=create_sqlite_engine(database); self.recorder=recorder; self.context=context
    def write(self, operation: Callable[[Any], Result]) -> Result:
        with immediate_transaction(self.engine) as connection: return operation(_Tx(connection,self))
    def read(self, operation: Callable[[Any], Result]) -> Result:
        with self.engine.connect() as connection: return operation(_Tx(connection,self))

class _Tx:
    def __init__(self, connection, owner): self.connection,self.owner=connection,owner
    def concern(self, concern_id):
        row=self.connection.execute(select(OwnerConcernModel.__table__).where(OwnerConcernModel.id==concern_id)).mappings().first()
        return Concern(**dict(row)) if row else None
    def operation(self,key):
        row=self.connection.execute(select(OwnerConcernModel.__table__).where(OwnerConcernModel.idempotency_key==key)).mappings().first()
        return dict(row) if row else None
    def follow_up_operation(self,key):
        row=self.connection.execute(select(OwnerConcernFollowUpOperationModel.__table__).where(OwnerConcernFollowUpOperationModel.idempotency_key==key)).mappings().first()
        return dict(row) if row else None
    def insert_concern(self,item): self.connection.execute(OwnerConcernModel.__table__.insert().values(**item.__dict__))
    def replace_concern(self,item): self.connection.execute(OwnerConcernModel.__table__.update().where(OwnerConcernModel.id==item.id).values(**item.__dict__))
    def insert_follow_up_operation(self,values): self.connection.execute(OwnerConcernFollowUpOperationModel.__table__.insert().values(**values))
    def duplicate_candidates(self, **filters):
        if filters.get("replaces_concern_id"):
            return [str(item) for item in self.connection.execute(select(OwnerConcernModel.id).where(OwnerConcernModel.replaces_concern_id==filters["replaces_concern_id"])).scalars()]
        query=select(OwnerConcernModel.id).where(OwnerConcernModel.owner_party_id==filters["owner_party_id"],OwnerConcernModel.property_id==filters["property_id"],OwnerConcernModel.concern_type==filters["concern_type"],OwnerConcernModel.status.in_(("open","in_progress")))
        for column,key in ((OwnerConcernModel.space_id,"space_id"),(OwnerConcernModel.lease_id,"lease_id"),(OwnerConcernModel.tenant_party_id,"tenant_party_id")):
            if filters.get(key) is not None: query=query.where(column==filters[key])
        return [str(item) for item in self.connection.execute(query.limit(20)).scalars()]
    def concern_page(self, *, limit=101, cursor=None, **filters):
        query=select(OwnerConcernModel)
        for column,key in ((OwnerConcernModel.owner_party_id,"owner_party_id"),(OwnerConcernModel.property_id,"property_id"),(OwnerConcernModel.space_id,"space_id"),(OwnerConcernModel.lease_id,"lease_id"),(OwnerConcernModel.tenant_party_id,"tenant_party_id"),(OwnerConcernModel.concern_type,"concern_type"),(OwnerConcernModel.priority,"priority"),(OwnerConcernModel.status,"status")):
            if filters.get(key) is not None: query=query.where(column==filters[key])
        query=self.owner.context.apply_concern_filters(self.connection,query,filters,OwnerConcernModel)
        order={"urgent":0,"high":1,"normal":2,"low":3}
        # SQLite CASE keeps priority ordering deterministic while raised time remains descending.
        rank = case(order,value=OwnerConcernModel.priority)
        if cursor:
            cursor_rank, cursor_raised, cursor_id = cursor
            query=query.where((rank > cursor_rank) | ((rank == cursor_rank) & ((OwnerConcernModel.raised_at_utc < cursor_raised) | ((OwnerConcernModel.raised_at_utc == cursor_raised) & (OwnerConcernModel.id < cursor_id)))))
        query=query.order_by(rank,OwnerConcernModel.raised_at_utc.desc(),OwnerConcernModel.id.desc()).limit(limit)
        return [Concern(**dict(item)) for item in self.connection.execute(query).mappings()]
    def context(self, **values): return self.owner.context.context(self.connection,**values)
    def active_property(self, property_id): return self.owner.context.active_property(self.connection,property_id)
    def originating_communication(self,*args): return self.owner.context.originating_communication(self.connection,*args)
    def create_task(self,values,*,correlation_id):
        return self.owner.context.create_task(self.connection,values,correlation_id, self.record_change)
    def task_views(self, concern_ids): return self.owner.context.task_views(self.connection,concern_ids)
    def active_task_counts(self, concern_ids): return self.owner.context.active_task_counts(self.connection,concern_ids)
    def communication_counts(self, concern_ids): return self.owner.context.communication_counts(self.connection,concern_ids)
    def detail_projection(self, concern): return self.owner.context.detail_projection(self.connection,concern)
    def record_change(self,**change): self.owner.recorder.record_change(self.connection.connection.driver_connection,**change)

class SQLiteOwnerConcernPropertyArchiveGuard:
    def conflict(self, connection, property_id: str) -> str | None:
        row=connection.execute(select(OwnerConcernModel.id).where(OwnerConcernModel.property_id==property_id,OwnerConcernModel.status.in_(("open","in_progress"))).limit(1)).first()
        return "Unresolved owner concerns prevent property archival." if row else None
