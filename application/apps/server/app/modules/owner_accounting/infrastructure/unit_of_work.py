from __future__ import annotations
from collections.abc import Callable
from typing import TypeVar
from sqlalchemy import and_, or_, select
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.owner_accounting.domain.models import OwnerRentReport
from app.modules.owner_accounting.infrastructure.sqlalchemy_models import OwnerRentReportModel, OwnerRentReportOperationModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")

class SQLiteOwnerRentReportUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder, leases, portfolio, parties, files, receipt_operations):
        self.engine=create_sqlite_engine(database); self.recorder=recorder
        self.leases,self.portfolio,self.parties,self.files=leases,portfolio,parties,files
        self.receipt_operations=receipt_operations
    def write(self, operation: Callable[["_Tx"], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(_Tx(connection, self))
    def read(self, operation: Callable[["_Tx"], Result]) -> Result:
        with self.engine.connect() as connection: return operation(_Tx(connection, self))

class _Tx:
    def __init__(self, connection, owner):
        self.connection,self.owner=connection,owner
        self.finance = owner.receipt_operations.transaction(connection)
    def report(self, report_id):
        row=self.connection.execute(select(OwnerRentReportModel.__table__).where(OwnerRentReportModel.id==report_id)).mappings().first()
        return None if row is None else OwnerRentReport(**dict(row))
    def report_by_operation_key(self,key):
        row=self.connection.execute(select(OwnerRentReportOperationModel.__table__).where(OwnerRentReportOperationModel.idempotency_key==key)).mappings().first()
        return None if row is None else dict(row)
    def insert_report(self,item): self.connection.execute(OwnerRentReportModel.__table__.insert().values(**item.__dict__))
    def replace_report(self,item): self.connection.execute(OwnerRentReportModel.__table__.update().where(OwnerRentReportModel.id==item.id).values(**item.__dict__))
    def insert_operation(self,item): self.connection.execute(OwnerRentReportOperationModel.__table__.insert().values(**item))
    def replacement_exists(self,report_id): return self.connection.execute(select(OwnerRentReportModel.id).where(OwnerRentReportModel.replaces_report_id==report_id)).first() is not None
    def replacement_for_report(self,report_id):
        row=self.connection.execute(select(OwnerRentReportModel.__table__).where(OwnerRentReportModel.replaces_report_id==report_id)).mappings().first()
        return None if row is None else OwnerRentReport(**dict(row))
    def report_for_receipt(self,receipt_id):
        row=self.connection.execute(select(OwnerRentReportModel.__table__).where(OwnerRentReportModel.verified_receipt_id==receipt_id)).mappings().first()
        return None if row is None else OwnerRentReport(**dict(row))
    def report_page(self, *, owner_party_id=None, property_id=None, space_id=None, lease_id=None, received_from=None, received_to=None, status=None, has_evidence=None, receipt_lifecycle=None, cursor=None, limit=101):
        query=select(OwnerRentReportModel.__table__)
        for model,value in ((OwnerRentReportModel.owner_party_id,owner_party_id),(OwnerRentReportModel.property_id,property_id),(OwnerRentReportModel.space_id,space_id),(OwnerRentReportModel.lease_id,lease_id),(OwnerRentReportModel.status,status)):
            if value is not None: query=query.where(model==value)
        if received_from:query=query.where(OwnerRentReportModel.received_on>=received_from)
        if received_to:query=query.where(OwnerRentReportModel.received_on<=received_to)
        if has_evidence is not None:
            linked=self.owner.files.active_link_predicate("owner_rent_report",OwnerRentReportModel.id)
            query=query.where(linked if has_evidence else ~linked)
        if receipt_lifecycle is not None:
            query=query.where(self.owner.receipt_operations.receipt_lifecycle_predicate(
                receipt_lifecycle, OwnerRentReportModel.verified_receipt_id,
            ))
        if cursor: query=query.where(or_(OwnerRentReportModel.received_on > cursor[0], and_(OwnerRentReportModel.received_on == cursor[0], OwnerRentReportModel.id > cursor[1])))
        return [OwnerRentReport(**dict(row)) for row in self.connection.execute(query.order_by(OwnerRentReportModel.received_on,OwnerRentReportModel.id).limit(limit)).mappings()]
    def record_change(self, **change): self.owner.recorder.record_change(self.connection.connection.driver_connection, **change)
    def lease_context(self, lease_id):
        space_id=self.owner.leases.lease_space_id(self.connection,lease_id)
        return None if space_id is None else self.owner.portfolio.context_for_space(self.connection,space_id)
    def owner_party(self,party_id): return self.owner.parties.party(self.connection,party_id)
    def owner_parties(self,party_ids): return self.owner.parties.party_map(self.connection,party_ids)
    def owner_eligible(self,property_id,party_id,on): return self.owner.portfolio.party_owned_property_on(self.connection,property_id,party_id,on)
    def has_evidence(self,report_id): return self.owner.files.has_active_available_link(self.connection,"owner_rent_report",report_id)
    def available_evidence_links(self,report_id): return self.owner.files.active_available_links(self.connection,"owner_rent_report",report_id)
    def evidence_count(self,report_id): return self.owner.files.active_link_count(self.connection,"owner_rent_report",report_id)
    def evidence_counts(self,report_ids): return self.owner.files.active_link_counts_for_entities(self.connection,"owner_rent_report",report_ids)
    def evidence_links(self,report_id): return self.owner.files.links_for_entities(self.connection,"owner_rent_report",[report_id])[report_id]
    def receipt(self,receipt_id): return self.finance.receipt(receipt_id)
    def receipts(self,receipt_ids): return self.owner.receipt_operations.receipt_contexts(self.connection,receipt_ids)
    def receipt_allocations(self,receipt_id): return self.finance.receipt_allocations(receipt_id)
    def receipt_projections(self,receipt_ids): return self.finance.receipt_projection(receipt_ids)
    def record_receipt(self,command,**kwargs): return self.owner.receipt_operations.record_receipt(self.connection,command,**kwargs)
    def replacement_receipt(self,receipt_id): return self.owner.receipt_operations.replacement_receipt(self.connection,receipt_id)
