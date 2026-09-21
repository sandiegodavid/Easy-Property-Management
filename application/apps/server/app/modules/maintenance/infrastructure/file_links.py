from sqlalchemy import select
from .sqlalchemy_models import MaintenanceIssueModel,MaintenanceAppointmentModel,MaintenanceCostContextModel,MaintenanceQuoteModel,MaintenanceAssignmentModel
class SQLiteMaintenanceFileLinkOperations:
 def __init__(self,file_reader):self.file_reader=file_reader
 def exists(self,connection,entity_type,entity_id):
  model={"maintenance_issue":MaintenanceIssueModel,"maintenance_appointment":MaintenanceAppointmentModel,"maintenance_cost_context":MaintenanceCostContextModel,"maintenance_quote":MaintenanceQuoteModel,"maintenance_assignment":MaintenanceAssignmentModel}[entity_type]
  return connection.execute(select(model.id).where(model.id==entity_id)).first() is not None
 def active_link_count(self,connection,entity_type,entity_id):return self.file_reader.active_link_count(connection,entity_type,entity_id)
