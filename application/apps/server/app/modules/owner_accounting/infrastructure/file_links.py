from sqlalchemy import select
from .sqlalchemy_models import OwnerRentReportModel
class SQLiteOwnerRentReportFileLinkOperations:
    def __init__(self,file_reader):self.file_reader=file_reader
    def report(self,connection,report_id):
        return connection.execute(select(OwnerRentReportModel.__table__).where(OwnerRentReportModel.id==report_id)).mappings().first()
    def active_link_count(self,connection,entity_type,entity_id):return self.file_reader.active_link_count(connection,entity_type,entity_id)
    def active_available_count(self,connection,report_id): return self.file_reader.active_available_link_count(connection,"owner_rent_report",report_id)
    def link_is_active_available(self,connection,link_id): return self.file_reader.link_is_active_available(connection,link_id)
    # Validators call this with no connection for target existence in the common
    # file API; keep the target read tied to the supplied validation connection.
    def exists(self,connection,report_id):return connection.execute(select(OwnerRentReportModel.id).where(OwnerRentReportModel.id==report_id)).first() is not None
