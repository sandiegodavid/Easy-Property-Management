"""INSP-001 report, acknowledgement, and comparison workflows."""
from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import uuid4
from pathlib import Path
from app.modules.inspections.application.ports import InspectionEvidenceStore, InspectionTransaction, InspectionUnitOfWork
from app.modules.inspections.domain.models import ConditionAcknowledgment, ConditionArea, ConditionChecklistTemplate, ConditionChecklistTemplateItem, ConditionComparison, ConditionObservation, ConditionReport

REPORT_KINDS = {"pre_move_in", "post_move_out"}; STATES = {"good", "fair", "poor", "damaged", "missing", "not_tested", "not_applicable"}; CLEAN = {"clean", "needs_cleaning", "not_assessed"}; ACKS = {"acknowledged", "disputed", "declined", "not_requested", "pending"}; COMPARES = {"unchanged", "improved", "normal_wear", "possible_tenant_damage", "maintenance_needed", "not_comparable"}
class InspectionError(ValueError): pass
class InspectionNotFoundError(InspectionError): pass
class InspectionConflictError(InspectionError): pass

def _date(value, label):
    try: return date.fromisoformat(str(value)).isoformat()
    except ValueError as error: raise InspectionError(f"{label} must be an ISO date.") from error
def _text(value, label, maximum=4000, required=False):
    if value is None: return None
    if not isinstance(value, str): raise InspectionError(f"{label} must be text.")
    value = " ".join(value.split())
    if required and not value: raise InspectionError(f"{label} is required.")
    if value and len(value) > maximum: raise InspectionError(f"{label} is too long.")
    return value or None
def _normalized(value, label): return _text(value, label, 160, True).casefold()
def _now(): return datetime.now(UTC).isoformat()

@dataclass(frozen=True)
class ObservationInput:
    item_name: str; condition_state: str; cleanliness_state: str | None = None; observed_on: str | None = None; is_completed: bool = False; notes: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "item_name", _text(self.item_name, "Item name", 160, True))
        if self.condition_state not in STATES: raise InspectionError("Unsupported condition state.")
        if self.cleanliness_state is not None and self.cleanliness_state not in CLEAN: raise InspectionError("Unsupported cleanliness state.")
        if type(self.is_completed) is not bool: raise InspectionError("Completion must be a boolean.")
        object.__setattr__(self, "notes", _text(self.notes, "Observation notes"))

@dataclass(frozen=True)
class AreaInput:
    display_name: str; observations: tuple[ObservationInput, ...]; notes: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "display_name", _text(self.display_name, "Area name", 160, True)); object.__setattr__(self, "notes", _text(self.notes, "Area notes"))
        if not isinstance(self.observations, tuple) or any(not isinstance(x, ObservationInput) for x in self.observations): raise InspectionError("Area observations must be valid.")


class InspectionService:
    def __init__(self, unit_of_work: InspectionUnitOfWork, files: InspectionEvidenceStore | None = None) -> None: self.unit_of_work = unit_of_work; self.files = files
    def get(self, report_id):
        value = self.unit_of_work.report_view(report_id)
        if value is None: raise InspectionNotFoundError("Condition report was not found.")
        return value
    def list_for_lease(self, lease_id):
        lease = self.unit_of_work.lease_summary(lease_id)
        if lease is None: raise InspectionNotFoundError("Lease was not found.")
        reports = self.unit_of_work.report_views(lease_id); current = {(item["reportKind"], item["status"]) for item in reports}; today = date.today().isoformat()
        return {"reports": reports, "attention": {"preMoveIn": "complete" if ("pre_move_in", "finalized") in current else ("overdue" if lease["status"] == "executed" and lease["occupancy_starts_on"] < today else ("due" if lease["status"] == "executed" else "not_due")), "postMoveOut": "complete" if ("post_move_out", "finalized") in current else ("due" if lease["actual_move_out_on"] else "not_due")}}
    def attention_for_lease(self, lease_id): return self.list_for_lease(lease_id)["attention"]
    def list_templates(self): return self.unit_of_work.template_views()
    def create_template(self, *, display_name, applicability="any", notes=None, areas=()):
        name = _text(display_name, "Template name", 160, True)
        if applicability not in {"residential", "office", "any"}: raise InspectionError("Unsupported checklist applicability.")
        if not isinstance(areas, tuple) or any(not isinstance(x, AreaInput) for x in areas): raise InspectionError("Areas must be valid.")
        correlation = str(uuid4())
        def write(tx):
            if tx.template_name_exists(name.casefold()): raise InspectionConflictError("A checklist template already uses this name.")
            now = _now(); template = ConditionChecklistTemplate(str(uuid4()), name, name.casefold(), applicability, _text(notes, "Template notes"), None, now, now); tx.insert_template(template); self._audit(tx, "condition_checklist_template", template.id, "created", None, template.to_dict(), correlation)
            position = 0; seen = set()
            for area in areas:
                area_name = _normalized(area.display_name, "Area name")
                for observation in area.observations:
                    key = (area_name, _normalized(observation.item_name, "Item name"))
                    if key in seen: raise InspectionError("Template items must be unique.")
                    seen.add(key); item = ConditionChecklistTemplateItem(str(uuid4()), template.id, area.display_name, area_name, observation.item_name, key[1], position, now); position += 1; tx.insert_template_item(item); self._audit(tx, "condition_checklist_template_item", item.id, "created", None, item.to_dict(), correlation)
            return template.id
        return self.unit_of_work.template_view(self.unit_of_work.write(write))
    def patch_template(self, template_id, *, display_name=None, applicability=None, notes=None, notes_provided=False, areas=None):
        correlation = str(uuid4())
        def write(tx):
            template = tx.template(template_id)
            if template is None or template.archived_at is not None: raise InspectionNotFoundError("Checklist template was not found.")
            name = template.display_name if display_name is None else _text(display_name, "Template name", 160, True)
            kind = template.applicability if applicability is None else applicability
            if kind not in {"residential", "office", "any"}: raise InspectionError("Unsupported checklist applicability.")
            updated = replace(template, display_name=name, normalized_name=name.casefold(), applicability=kind, notes=template.notes if not notes_provided else _text(notes, "Template notes"), updated_at=_now())
            if tx.template_name_exists(updated.normalized_name, excluding_id=template.id): raise InspectionConflictError("A checklist template already uses this name.")
            tx.replace_template(updated); self._audit(tx, "condition_checklist_template", template.id, "updated", template.to_dict(), updated.to_dict(), correlation)
            if areas is not None:
                for existing in tx.template_items(template_id): self._audit(tx, "condition_checklist_template_item", existing.id, "removed", existing.to_dict(), None, correlation)
                tx.delete_template_items(template_id); position = 0
                for area in areas:
                    for item in area.observations:
                        entry = ConditionChecklistTemplateItem(str(uuid4()), template_id, area.display_name, _normalized(area.display_name,"Area name"), item.item_name, _normalized(item.item_name,"Item name"), position, _now()); position += 1; tx.insert_template_item(entry); self._audit(tx,"condition_checklist_template_item",entry.id,"created",None,entry.to_dict(),correlation)
            return updated.id
        return self.unit_of_work.template_view(self.unit_of_work.write(write))
    def create(self, lease_id, *, report_kind, walkthrough_on, conducted_by, tenant_presence="not_recorded", general_notes=None, areas=(), template_id=None, correction_of=None, correction_reason=None, timing_exception_reason=None):
        if report_kind not in REPORT_KINDS: raise InspectionError("Unsupported report kind.")
        walkthrough = _date(walkthrough_on, "Walkthrough date"); conducted_by = _text(conducted_by, "Conducted by", 160, True)
        if tenant_presence not in {"present", "not_present", "declined", "not_recorded"}: raise InspectionError("Unsupported tenant presence.")
        if not isinstance(areas, tuple) or any(not isinstance(x, AreaInput) for x in areas): raise InspectionError("Areas must be valid.")
        correlation = str(uuid4())
        def write(tx):
            lease = tx.lease(lease_id)
            if not lease: raise InspectionNotFoundError("Lease was not found.")
            if lease["status"] == "void" or (correction_of is None and ((report_kind == "pre_move_in" and lease["status"] != "executed") or (report_kind == "post_move_out" and lease["status"] not in {"executed", "ended", "terminated"}))): raise InspectionConflictError("The lease lifecycle does not permit this report.")
            source = None if correction_of is None else tx.report(correction_of)
            if correction_of is not None and source is None: raise InspectionNotFoundError("The corrected report was not found.")
            if source is not None and (source.status != "finalized" or source.lease_id != lease_id or source.report_kind != report_kind): raise InspectionConflictError("A correction must supersede its matching finalized report.")
            if correction_of is not None and not _text(correction_reason, "Correction reason", 1000, True): raise InspectionError("A correction reason is required.")
            copied_areas = areas
            if template_id is not None:
                template = tx.template(template_id)
                if template is None or template.archived_at is not None: raise InspectionNotFoundError("Checklist template was not found.")
                grouped = {}
                for item in tx.template_items(template_id): grouped.setdefault(item.area_display_name, []).append(ObservationInput(item.item_name, "not_tested"))
                copied_areas = tuple(AreaInput(name, tuple(items)) for name, items in grouped.items())
            now = _now(); report = ConditionReport(str(uuid4()), lease_id, lease["space_id"], report_kind, "draft", walkthrough, conducted_by, tenant_presence, correction_of, _text(correction_reason, "Correction reason", 1000), _text(timing_exception_reason, "Timing exception", 1000), _text(general_notes, "General notes"), None, now, now)
            tx.insert_report(report); self._audit(tx, "condition_report", report.id, "created", None, report.to_dict(), correlation)
            self._replace_areas(tx, report, copied_areas, correlation); self._ensure_acknowledgments(tx, report, correlation)
            return tx.report_view(report.id)
        return self.unit_of_work.write(write)
    def replace_areas(self, report_id, areas):
        if not isinstance(areas, tuple) or any(not isinstance(x, AreaInput) for x in areas): raise InspectionError("Areas must be valid.")
        correlation = str(uuid4())
        def write(tx):
            report = self._draft(tx, report_id)
            if tx.has_evidence(report.id): raise InspectionConflictError("Evidence-linked observations cannot be removed from a checklist.")
            for area in tx.areas(report.id):
                for observation in tx.observations(area.id): self._audit(tx, "condition_observation", observation.id, "removed", observation.to_dict(), None, correlation)
                self._audit(tx, "condition_area", area.id, "removed", area.to_dict(), None, correlation)
            tx.delete_report_children(report.id); self._replace_areas(tx, report, areas, correlation); return tx.report_view(report.id)
        return self.unit_of_work.write(write)
    def patch_report(self, report_id, *, walkthrough_on=None, conducted_by=None, tenant_presence=None, general_notes=None, general_notes_provided=False):
        correlation = str(uuid4())
        def write(tx):
            report = self._draft(tx, report_id)
            if walkthrough_on is None and conducted_by is None and tenant_presence is None and not general_notes_provided: return tx.report_view(report.id)
            updated = replace(report, walkthrough_on=report.walkthrough_on if walkthrough_on is None else _date(walkthrough_on, "Walkthrough date"), conducted_by=report.conducted_by if conducted_by is None else _text(conducted_by, "Conducted by", 160, True), tenant_presence=report.tenant_presence if tenant_presence is None else tenant_presence, general_notes=report.general_notes if not general_notes_provided else _text(general_notes, "General notes"), updated_at=_now())
            if updated.tenant_presence not in {"present", "not_present", "declined", "not_recorded"}: raise InspectionError("Unsupported tenant presence.")
            tx.replace_report(updated); self._audit(tx, "condition_report", report.id, "updated", report.to_dict(), updated.to_dict(), correlation); return tx.report_view(report.id)
        return self.unit_of_work.write(write)
    def acknowledge(self, report_id, acknowledgments):
        correlation = str(uuid4())
        def write(tx):
            report = self._draft(tx, report_id); participants = {x["id"] for x in tx.participants(report.lease_id) if x["starts_on"] <= report.walkthrough_on and (x["ends_on"] is None or x["ends_on"] > report.walkthrough_on)}
            if set(acknowledgments) != participants: raise InspectionError("Acknowledgments must include every active lease participant.")
            for existing in tx.acknowledgments(report.id):
                tx.delete_acknowledgment(existing.id); self._audit(tx, "condition_report_acknowledgment", existing.id, "replaced", existing.to_dict(), None, correlation)
            for participant_id, value in acknowledgments.items():
                status = value.get("status"); notes = _text(value.get("notes"), "Acknowledgment notes")
                if status not in ACKS: raise InspectionError("Unsupported acknowledgment status.")
                item = ConditionAcknowledgment(str(uuid4()), report.id, participant_id, status, _now() if status != "pending" else None, notes); tx.insert_acknowledgment(item); self._audit(tx, "condition_report_acknowledgment", item.id, "recorded", None, item.to_dict(), correlation)
            return tx.report_view(report.id)
        return self.unit_of_work.write(write)
    def finalize(self, report_id, *, confirmed, timing_exception_reason=None):
        if confirmed is not True: raise InspectionError("Finalization requires explicit confirmation.")
        correlation = str(uuid4())
        def write(tx):
            report = self._draft(tx, report_id); lease = tx.lease(report.lease_id)
            if report.report_kind == "post_move_out" and not lease["actual_move_out_on"]: raise InspectionConflictError("Post-move-out finalization requires confirmed move-out.")
            normal = report.walkthrough_on <= lease["occupancy_starts_on"] if report.report_kind == "pre_move_in" else report.walkthrough_on >= lease["actual_move_out_on"]
            reason = _text(timing_exception_reason, "Timing exception", 1000)
            if not normal and not reason: raise InspectionError("An out-of-window walkthrough requires a timing exception reason.")
            observations = [o for a in tx.areas(report.id) for o in tx.observations(a.id)]
            if not observations or any(not o.is_completed for o in observations): raise InspectionError("Every observation must be completed before finalization.")
            active = {x["id"] for x in tx.participants(report.lease_id) if x["starts_on"] <= report.walkthrough_on and (x["ends_on"] is None or x["ends_on"] > report.walkthrough_on)}
            if active != {x.lease_participant_id for x in tx.acknowledgments(report.id) if x.status != "pending"}: raise InspectionError("Every active participant must acknowledge or decline the report.")
            current = [item for item in tx.reports(report.lease_id) if item.report_kind == report.report_kind and item.status == "finalized" and item.id != report.supersedes_report_id]
            if current: raise InspectionConflictError("A current finalized report of this kind already exists.")
            now = _now(); final = replace(report, status="finalized", finalized_at=now, timing_exception_reason=reason, updated_at=now)
            if report.supersedes_report_id:
                source = tx.report(report.supersedes_report_id)
                if source is None or source.status != "finalized": raise InspectionConflictError("The corrected source is no longer current.")
                superseded = replace(source, status="superseded", updated_at=now); tx.replace_report(superseded); self._audit(tx, "condition_report", source.id, "superseded", source.to_dict(), superseded.to_dict(), correlation)
            tx.replace_report(final)
            self._audit(tx, "condition_report", report.id, "finalized", report.to_dict(), final.to_dict(), correlation); return tx.report_view(report.id)
        return self.unit_of_work.write(write)
    def comparison(self, lease_id):
        if not self.unit_of_work.lease_exists(lease_id): raise InspectionNotFoundError("Lease was not found.")
        reports = self.unit_of_work.report_views(lease_id); current = {item["reportKind"]: item for item in reports if item["status"] == "finalized"}
        comparisons = [item.to_dict() for item in self.unit_of_work.write(lambda tx: tx.comparisons(lease_id)) if item.pre_report_id == (current.get("pre_move_in") or {}).get("id") and item.post_report_id == (current.get("post_move_out") or {}).get("id")]
        return {"preReport": current.get("pre_move_in"), "postReport": current.get("post_move_out"), "comparisons": comparisons, "requiresFreshReview": bool(current) and not comparisons}
    def save_comparisons(self, lease_id, values):
        correlation = str(uuid4())
        def write(tx):
            if not tx.lease(lease_id): raise InspectionNotFoundError("Lease was not found.")
            reports = [item for item in tx.reports(lease_id) if item.status == "finalized"]
            if {item.report_kind for item in reports} != REPORT_KINDS: raise InspectionConflictError("Finalized pre- and post-move-out reports are required.")
            pair = {item.report_kind: item.id for item in reports}
            seen_pre, seen_post = set(), set()
            for value in values:
                for key, kind, seen in (("pre_observation_id", "pre_move_in", seen_pre), ("post_observation_id", "post_move_out", seen_post)):
                    observation_id = value.get(key)
                    if observation_id is None: continue
                    if observation_id in seen: raise InspectionError("An observation can appear only once in a comparison.")
                    seen.add(observation_id); context = tx.observation_context(observation_id)
                    if context is None or context["lease_id"] != lease_id or context["report_kind"] != kind or context["status"] != "finalized": raise InspectionConflictError("Comparisons must use current finalized observations of the matching kind.")
            for existing in tx.comparisons(lease_id):
                if existing.pre_report_id == pair["pre_move_in"] and existing.post_report_id == pair["post_move_out"]:
                    tx.delete_comparison(existing.id); self._audit(tx, "condition_comparison", existing.id, "replaced", existing.to_dict(), None, correlation)
            now = _now(); result = []
            for value in values:
                state = value["comparison_state"]; notes = _text(value.get("operator_notes"), "Comparison notes")
                if state not in COMPARES: raise InspectionError("Unsupported comparison state.")
                if state in {"possible_tenant_damage", "not_comparable"} and not notes: raise InspectionError("This comparison requires notes.")
                item = ConditionComparison(str(uuid4()), lease_id, pair["pre_move_in"], pair["post_move_out"], value.get("pre_observation_id"), value.get("post_observation_id"), state, notes, now, now); tx.insert_comparison(item); self._audit(tx, "condition_comparison", item.id, "classified", None, item.to_dict(), correlation); result.append(item.to_dict())
            return result
        return self.unit_of_work.write(write)
    def attach_evidence(self, observation_id: str, source: Path, original_name: str, media_type: str, purpose: str):
        if self.files is None: raise InspectionError("Inspection evidence storage is not configured.")
        if purpose not in {"condition_photo", "supporting_document"}: raise InspectionError("Unsupported evidence purpose.")
        correlation = str(uuid4())
        staged_content = []
        def attach(tx):
            context = tx.observation_context(observation_id)
            if context is None: raise InspectionNotFoundError("Condition observation was not found.")
            if context["status"] != "draft": raise InspectionConflictError("Evidence can be attached only to a draft report.")
            item, content = self.files.add_in_transaction(tx.file_transaction(), source, original_name, media_type, entity_type="condition_observation", entity_id=observation_id, purpose=purpose, correlation_id=correlation)
            staged_content.append(content)
            self._audit(tx, "condition_observation", observation_id, "evidence_attached", None, {"fileId": item.id, "purpose": purpose}, correlation)
            return item, content
        try:
            item, content = self.unit_of_work.write(attach)
        except Exception:
            if staged_content: staged_content[0].rollback()
            raise
        try: content.commit()
        except OSError: pass
        return self.files.get(item.id).to_dict()
    def _draft(self, tx, report_id):
        report = tx.report(report_id)
        if report is None: raise InspectionNotFoundError("Condition report was not found.")
        if report.status != "draft": raise InspectionConflictError("Finalized or superseded reports are immutable.")
        return report
    def _replace_areas(self, tx, report, areas, correlation):
        seen = set()
        for area_index, source in enumerate(areas):
            normalized = _normalized(source.display_name, "Area name")
            if normalized in seen: raise InspectionError("Area names must be unique.")
            seen.add(normalized); area = ConditionArea(str(uuid4()), report.id, source.display_name, normalized, area_index, source.notes); tx.insert_area(area); self._audit(tx, "condition_area", area.id, "created", None, area.to_dict(), correlation)
            items = set()
            for item_index, source_item in enumerate(source.observations):
                name = _normalized(source_item.item_name, "Item name")
                if name in items: raise InspectionError("Item names must be unique within an area.")
                items.add(name); observed = _date(source_item.observed_on or report.walkthrough_on, "Observed date"); completed_at = _now() if source_item.is_completed else None
                observation = ConditionObservation(str(uuid4()), area.id, source_item.item_name, name, source_item.condition_state, source_item.cleanliness_state, observed, source_item.is_completed, completed_at, source_item.notes, item_index); tx.insert_observation(observation); self._audit(tx, "condition_observation", observation.id, "created", None, observation.to_dict(), correlation)
    def _ensure_acknowledgments(self, tx, report, correlation):
        for participant in tx.participants(report.lease_id):
            if participant["starts_on"] <= report.walkthrough_on and (participant["ends_on"] is None or participant["ends_on"] > report.walkthrough_on):
                item = ConditionAcknowledgment(str(uuid4()), report.id, participant["id"], "pending", None, None); tx.insert_acknowledgment(item); self._audit(tx, "condition_report_acknowledgment", item.id, "requested", None, item.to_dict(), correlation)
    def _audit(self, tx, entity_type, entity_id, action, before, after, correlation): tx.record_change(entity_type=entity_type, entity_id=entity_id, action=action, before=before, after=after, reason="inspection_workflow", correlation_id=correlation)
