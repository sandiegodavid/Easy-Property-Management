from unittest import TestCase
from app.modules.maintenance.domain.models import AppointmentCreate, CostCreate, IssueCreate, ReporterAttribution, MaintenanceError

class MaintenanceCommandTests(TestCase):
    property_id="00000000-0000-4000-8000-000000000001"
    def test_issue_normalizes_and_requires_other_detail(self):
        reporter=ReporterAttribution("manager","local_operator")
        item=IssueCreate(self.property_id,None,"  Leak ","  Water under sink ","plumbing",None,"high","2026-09-20T10:00:00-07:00",reporter)
        self.assertEqual(item.summary,"Leak")
        with self.assertRaises(MaintenanceError): IssueCreate(self.property_id,None,"x","x","other",None,"normal","2026-09-20T10:00:00+00:00",reporter)
    def test_appointment_and_cost_invariants(self):
        with self.assertRaises(MaintenanceError): AppointmentCreate("2026-09-20T10:00:00+00:00","2026-09-20T10:00:00+00:00","visit")
        self.assertEqual(CostCreate("operator_estimate","Plumber","12.34","2026-09-20").amount,1234)
        with self.assertRaises(MaintenanceError): CostCreate("operator_estimate","Plumber","12.3","2026-09-20")

    def test_local_operator_cannot_claim_historical_party_selection(self):
        with self.assertRaises(MaintenanceError):
            ReporterAttribution(
                "manager", "local_operator", historical_selection_confirmed=True,
                historical_selection_reason="Past operator record",
            )
