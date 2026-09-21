from app.modules.files.application.ports import FileLink
class MaintenanceFileLinkValidator:
    entity_types=frozenset({"maintenance_issue","maintenance_appointment","maintenance_cost_context","maintenance_quote","maintenance_assignment","maintenance_work_journal_entry"})
    _rules={"maintenance_issue":({"issue_photo","inspection_report","supporting_document"},50),"maintenance_appointment":({"appointment_document","access_document"},10),"maintenance_cost_context":({"estimate_document","work_report_document","supporting_document"},10),"maintenance_quote":({"quote_document","supporting_document"},10),"maintenance_assignment":({"assignment_document","supporting_document"},10),"maintenance_work_journal_entry":({"completion_photo","work_report","supporting_document"},20)}
    def __init__(self,operations):self.operations=operations
    def validate_create(self,connection,link:FileLink):
        purposes,limit=self._rules[link.entity_type]
        if link.purpose not in purposes:raise ValueError("File-link purpose is not allowed for maintenance evidence.")
        if not self.operations.exists(connection,link.entity_type,link.entity_id):raise ValueError("Maintenance evidence target was not found.")
        if link.entity_type == "maintenance_work_journal_entry":
            effective_kind = self.operations.work_journal_effective_kind(connection, link.entity_id)
            if effective_kind is None:
                raise ValueError("Evidence cannot be attached to a superseded work-journal entry.")
            if link.purpose == "completion_photo" and effective_kind != "work_completed":
                raise ValueError("completion_photo requires a completed-work journal entry.")
        if self.operations.active_link_count(connection,link.entity_type,link.entity_id)>=limit:raise ValueError("Maintenance evidence-link limit has been reached.")
    def validate_archive(self,connection,link):
        if not self.operations.exists(connection,link.entity_type,link.entity_id):raise ValueError("Maintenance evidence target was not found.")
