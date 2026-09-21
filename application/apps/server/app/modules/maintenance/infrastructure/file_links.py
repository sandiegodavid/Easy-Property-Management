from sqlalchemy import exists, select
from .sqlalchemy_models import MaintenanceIssueModel,MaintenanceAppointmentModel,MaintenanceCostContextModel,MaintenanceQuoteModel,MaintenanceAssignmentModel,MaintenanceWorkJournalEntryModel
class SQLiteMaintenanceFileLinkOperations:
 def __init__(self,file_reader):self.file_reader=file_reader
 def exists(self,connection,entity_type,entity_id):
  model={"maintenance_issue":MaintenanceIssueModel,"maintenance_appointment":MaintenanceAppointmentModel,"maintenance_cost_context":MaintenanceCostContextModel,"maintenance_quote":MaintenanceQuoteModel,"maintenance_assignment":MaintenanceAssignmentModel,"maintenance_work_journal_entry":MaintenanceWorkJournalEntryModel}[entity_type]
  return connection.execute(select(model.id).where(model.id==entity_id)).first() is not None
 def active_link_count(self,connection,entity_type,entity_id):return self.file_reader.active_link_count(connection,entity_type,entity_id)
 def work_journal_effective_kind(self,connection,entry_id):
  corrected=MaintenanceWorkJournalEntryModel.__table__.alias("journal_correction")
  row=connection.execute(select(MaintenanceWorkJournalEntryModel.entry_kind,MaintenanceWorkJournalEntryModel.corrected_entry_kind).where(MaintenanceWorkJournalEntryModel.id==entry_id,~exists(select(corrected.c.id).where(corrected.c.corrects_entry_id==MaintenanceWorkJournalEntryModel.id)))).mappings().first()
  return None if row is None else row["corrected_entry_kind"] or row["entry_kind"]
