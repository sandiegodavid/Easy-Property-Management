from app.modules.files.application.ports import FileLink

class OwnerRentReportFileLinkValidator:
    entity_types=frozenset({"owner_rent_report"})
    purposes=frozenset({"owner_statement","payment_confirmation","deposit_confirmation","correspondence","supporting_document"})
    def __init__(self, operations): self.operations=operations
    def validate_create(self, connection, link: FileLink):
        if link.purpose not in self.purposes: raise ValueError("File-link purpose is not allowed for owner rent report evidence.")
        if not self.operations.exists(connection, link.entity_id): raise ValueError("Owner rent report evidence target was not found.")
        if self.operations.active_link_count(connection,"owner_rent_report",link.entity_id)>=20: raise ValueError("Owner rent report evidence-link limit has been reached.")
    def validate_archive(self, connection, link: FileLink):
        report=self.operations.report(connection, link.entity_id)
        if report is None: raise ValueError("Owner rent report evidence target was not found.")
        if report.status=="verified" and self.operations.link_is_active_available(connection,link.id) and self.operations.active_available_count(connection,link.entity_id)<=1: raise ValueError("Verified owner rent reports must retain one active available evidence file.")
