from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy
class MaintenanceActivitySnapshotPolicy(DefaultAuditSnapshotPolicy):
    def redact(self,snapshot):
        result=dict(snapshot or {})
        for key in ("description","instructions","outcomeNote","sourceNote","resolutionSummary","cancellationReason","archiveReason","voidReason","operatorNarrative","taskId","reporterPartyId","reporterDisplayNameSnapshot","historicalSelectionReason","scopeSummary","termsNotes","selectionReason","avoidOverrideReason","withdrawalReason","endReason","detail","outcomeSummary","correctionReason"): result.pop(key,None)
        return result
MAINTENANCE_ACTIVITY_POLICY=MaintenanceActivitySnapshotPolicy()
