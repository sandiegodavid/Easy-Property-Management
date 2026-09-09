"""Focused INSP-001 contract regressions."""
from __future__ import annotations
import ast
from datetime import datetime
from pathlib import Path
import unittest
from pydantic import ValidationError
from app.modules.inspections.api.router import ComparisonItemResponse, ObservationResponse, TemplateItemResponse
from app.modules.files.application.errors import FileError
from app.modules.files.application.service import FileService
from app.modules.inspections.application.service import AreaInput, InspectionConflictError, InspectionService, ObservationInput


class _Transaction:
    def __init__(self):
        self.lease_data = {"id": "lease", "space_id": "space", "status": "executed", "occupancy_starts_on": "2099-01-01", "actual_move_out_on": None}
        self.reports_by_id = {}; self.areas_by_report = {}; self.observations_by_area = {}; self.acks_by_report = {}; self.events = []
    def lease(self, item_id): return self.lease_data if item_id == "lease" else None
    def termination_accepted(self, lease_id): return False
    def report(self, item_id): return self.reports_by_id.get(item_id)
    def reports(self, lease_id): return list(self.reports_by_id.values())
    def participants(self, lease_id): return []
    def areas(self, report_id): return self.areas_by_report.get(report_id, [])
    def observations(self, area_id): return self.observations_by_area.get(area_id, [])
    def observation_context(self, observation_id): return None
    def has_evidence(self, report_id): return False
    def acknowledgments(self, report_id): return self.acks_by_report.get(report_id, [])
    def comparisons(self, lease_id): return []
    def template(self, item_id): return None
    def template_items(self, template_id): return []
    def template_name_exists(self, *args, **kwargs): return False
    def insert_report(self, item): self.reports_by_id[item.id] = item
    def replace_report(self, item): self.reports_by_id[item.id] = item
    def insert_area(self, item): self.areas_by_report.setdefault(item.condition_report_id, []).append(item)
    def insert_observation(self, item): self.observations_by_area.setdefault(item.condition_area_id, []).append(item)
    def insert_acknowledgment(self, item): self.acks_by_report.setdefault(item.condition_report_id, []).append(item)
    def delete_report_children(self, report_id): self.areas_by_report[report_id] = []
    def record_change(self, **change): self.events.append(change)
    def report_view(self, item_id): return self.reports_by_id[item_id].to_dict()


class _UnitOfWork:
    def __init__(self): self.tx = _Transaction()
    def write(self, operation): return operation(self.tx)
    def report_view(self, report_id): return None if report_id not in self.tx.reports_by_id else self.tx.report_view(report_id)
    def report_views(self, lease_id): return [item.to_dict() for item in self.tx.reports_by_id.values()]
    def lease_summary(self, lease_id): return self.tx.lease(lease_id)
    def lease_exists(self, lease_id): return self.tx.lease(lease_id) is not None
    def template_views(self): return []
    def template_view(self, template_id): return None


class InspectionContractTests(unittest.TestCase):
    def test_observation_response_rejects_invalid_condition_state(self):
        with self.assertRaises(ValidationError):
            ObservationResponse.model_validate({"id":"o", "conditionAreaId":"a", "itemName":"Wall", "normalizedName":"wall", "conditionState":"broken_enum", "cleanlinessState":None, "observedOn":"2026-01-01", "isCompleted":True, "completedAt":"2026-01-01T00:00:00Z", "notes":None, "sortOrder":0, "files":[]})

    def test_nested_contract_requires_timestamps_and_report_pair(self):
        with self.assertRaises(ValidationError):
            ComparisonItemResponse.model_validate({"id":"c", "leaseId":"l", "preObservationId":None, "postObservationId":"o", "comparisonState":"unchanged", "operatorNotes":None, "createdAt":"invalid", "updatedAt":"invalid"})
        with self.assertRaises(ValidationError):
            TemplateItemResponse.model_validate({"id":"t", "templateId":"x", "areaDisplayName":"Kitchen", "areaNormalizedName":"kitchen", "itemName":"Floor", "itemNormalizedName":"floor", "sortOrder":0})

    def test_application_has_no_sqlalchemy_or_infrastructure_imports(self):
        source = Path(__file__).parents[1] / "application" / "service.py"
        tree = ast.parse(source.read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name.startswith("sqlalchemy") or ".infrastructure" in name for name in imports))

    def test_generic_file_service_rejects_inspection_observation_links(self):
        class Workspace:
            def open(self): pass
        service = FileService(Workspace(), object(), object())
        with self.assertRaises(FileError):
            service.add(Path(__file__), "evidence.txt", "text/plain", entity_type="condition_observation", entity_id="observation", purpose="condition_photo")

    def test_pre_report_finalization_and_current_report_uniqueness(self):
        service = InspectionService(_UnitOfWork())
        checklist = (AreaInput("Kitchen", (ObservationInput("Floor", "good", is_completed=True),)),)
        first = service.create("lease", report_kind="pre_move_in", walkthrough_on="2099-01-01", conducted_by="Operator", areas=checklist)
        second = service.create("lease", report_kind="pre_move_in", walkthrough_on="2099-01-01", conducted_by="Operator", areas=checklist)
        service.finalize(first["id"], confirmed=True)
        with self.assertRaises(InspectionConflictError): service.finalize(second["id"], confirmed=True)
