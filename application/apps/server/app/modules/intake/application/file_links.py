"""FILE-001 policy for intake attachments.

Direct generic uploads are deliberately rejected: intake must persist the
immutable revision/file association in the same transaction as its source.
"""
from __future__ import annotations
from sqlalchemy import text
from app.modules.files.application.ports import FileLink


class IntakeSourceFileLinkValidator:
    entity_types = frozenset({"intake_source"})
    allows_generic_upload = False
    _purposes = frozenset({"source_attachment", "raw_source"})
    def validate_create(self, connection, link: FileLink) -> None:
        if link.purpose not in self._purposes: raise ValueError("Intake attachment purpose is invalid.")
        # A new source does not yet exist.  Intake uses owning_workflow=True
        # and writes its immutable revision association before commit.
    def validate_archive(self, connection, link: FileLink) -> None:
        raise ValueError("Intake evidence links cannot be archived.")
    def validate_retained(self, connection, link: FileLink) -> None:
        if link.purpose not in self._purposes: raise ValueError("Intake attachment purpose is invalid.")
        source = connection.execute(text("SELECT id FROM intake_sources WHERE id=:id"), {"id": link.entity_id}).first()
        if source is None: raise ValueError("Intake attachment source is missing.")
        association = connection.execute(text("SELECT 1 FROM intake_revision_file_links r JOIN intake_evidence_revisions e ON e.id=r.revision_id WHERE e.source_id=:source AND r.file_link_id=:link"), {"source": link.entity_id, "link": link.id}).first()
        if association is None: raise ValueError("Intake attachment lacks an immutable revision association.")
