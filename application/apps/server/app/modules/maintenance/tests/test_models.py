from unittest import TestCase
from app.modules.maintenance.domain.models import AppointmentCreate, CostCreate, IssueCreate, MaintenanceError

class MaintenanceCommandTests(TestCase):
    property_id="00000000-0000-4000-8000-000000000001"
    def test_issue_normalizes_and_requires_other_detail(self):
        item=IssueCreate(self.property_id,None,"  Leak ","  Water under sink ","plumbing",None,"high","2026-09-20T10:00:00-07:00")
        self.assertEqual(item.summary,"Leak")
        with self.assertRaises(MaintenanceError): IssueCreate(self.property_id,None,"x","x","other",None,"normal","2026-09-20T10:00:00+00:00")
    def test_appointment_and_cost_invariants(self):
        with self.assertRaises(MaintenanceError): AppointmentCreate("2026-09-20T10:00:00+00:00","2026-09-20T10:00:00+00:00","visit")
        self.assertEqual(CostCreate("operator_estimate","Plumber","12.34","2026-09-20").amount,1234)
        with self.assertRaises(MaintenanceError): CostCreate("operator_estimate","Plumber","12.3","2026-09-20")
