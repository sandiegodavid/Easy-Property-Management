"""Inspection recovery registration; never dispatches commands or publishes bytes."""

from app.modules.files.application.errors import normalize_filename, normalize_media_type
from app.modules.inspections.application.commands import fingerprint, InspectionRecoveryReader
from app.modules.inspections.application.service import AreaInput, ObservationInput
from app.modules.inspections.infrastructure.recovery_reader import SQLiteInspectionRecoveryReader
from app.modules.operator.application.inspection_forms import (
    INSPECTION_SCHEMAS,
    inspection_source_kind,
)
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError


def areas(values):
    return tuple(
        AreaInput(
            area["displayName"],
            tuple(
                ObservationInput(
                    item["itemName"],
                    item["conditionState"],
                    item.get("cleanlinessState"),
                    item.get("observedOn"),
                    item.get("isCompleted", False),
                    item.get("notes"),
                )
                for item in area.get("observations", ())
            ),
            area.get("notes"),
        )
        for area in (values or ())
    )


def text(value):
    return " ".join(value.split()) if isinstance(value, str) else value


def report_payload(payload, correction):
    return {
        "report_kind": payload["reportKind"],
        "walkthrough_on": payload["walkthroughOn"],
        "conducted_by": text(payload["conductedBy"]),
        "tenant_presence": payload.get("tenantPresence") or "not_recorded",
        "general_notes": payload.get("generalNotes"),
        "areas": areas(payload.get("areas")),
        "template_id": None if correction else payload.get("templateId"),
        "correction_of": correction,
        "correction_reason": payload.get("correctionReason"),
        "timing_exception_reason": None,
    }


def template_payload(payload, patch):
    return {
        "display_name": payload.get("displayName") if patch else text(payload["displayName"]),
        "applicability": payload.get("applicability")
        if patch
        else payload.get("applicability") or "any",
        "notes": payload.get("notes"),
        "areas": areas(payload.get("areas"))
        if not patch or payload.get("areas") is not None
        else None,
        **({"notes_provided": "notes" in payload} if patch else {}),
    }


def command_payload(action, payload):
    if action == "report.patch":
        return {
            "walkthrough_on": payload.get("walkthroughOn"),
            "conducted_by": payload.get("conductedBy"),
            "tenant_presence": payload.get("tenantPresence"),
            "general_notes": payload.get("generalNotes"),
            "general_notes_provided": "generalNotes" in payload,
        }
    if action == "report.areas":
        return {"areas": areas(payload["areas"])}
    if action == "report.acknowledge":
        return {
            "acknowledgments": {
                key: {"status": value["status"], "notes": value.get("notes")}
                for key, value in payload["acknowledgments"].items()
            }
        }
    if action == "report.finalize":
        if payload.get("confirmed") is not True:
            raise OperatorError("Confirm report finalization.")
        return {"confirmed": True, "timing_exception_reason": payload.get("timingExceptionReason")}
    if action == "evidence.attach":
        return {
            "original_name": normalize_filename(payload["originalName"]),
            "media_type": normalize_media_type(payload["mediaType"]),
            "purpose": payload["purpose"],
            "content_sha256": payload["contentSha256"],
            "size_bytes": payload["sizeBytes"],
        }
    return {
        "values": [
            {
                "pre_observation_id": item.get("preObservationId"),
                "post_observation_id": item.get("postObservationId"),
                "comparison_state": item["comparisonState"],
                "operator_notes": item.get("operatorNotes"),
            }
            for item in payload["comparisons"]
        ]
    }


def inspection_fingerprint(form, action, source, payload, key):
    del key
    required = {
        "report.create": ("reportKind", "walkthroughOn", "conductedBy"),
        "template.create": ("displayName",),
        "report.areas": ("areas",),
        "report.acknowledge": ("acknowledgments",),
        "comparison.review": ("comparisons",),
        "evidence.attach": ("originalName", "mediaType", "contentSha256", "sizeBytes", "purpose"),
    }
    if any(
        payload.get(field) is None
        or (isinstance(payload.get(field), str) and not payload[field].strip())
        for field in required.get(action, ())
    ):
        raise OperatorError("Complete the owning Inspection command.")
    kind = "report"
    target = source
    if form.endswith("template.create") or form.endswith("template.patch"):
        kind = "template"
        patch = action == "template.patch"
        if not patch and payload["expectedRevision"] != 0:
            raise OperatorError("Template creation requires revision zero.")
        request = template_payload(payload, patch)
    elif action == "report.create":
        kind = "lease"
        correction = source if form.endswith(".correct") else None
        target = payload["leaseId"] if correction else source
        request = report_payload(payload, correction)
        if correction and not text(payload.get("correctionReason")):
            raise OperatorError("Complete the correction reason.")
    else:
        kind = (
            "observation"
            if action == "evidence.attach"
            else "lease"
            if action == "comparison.review"
            else "report"
        )
        request = command_payload(action, payload)
    return fingerprint(
        action,
        {
            "targetKind": kind,
            "targetId": target,
            "expectedRevision": payload["expectedRevision"],
            "payload": request,
        },
    )


def inspection_form_state(form, state, payload):
    if form == "inspection.report.create":
        kind = payload.get("reportKind")
        allowed = {"executed"} if kind == "pre_move_in" else {"executed", "ended", "terminated"}
    elif form == "inspection.comparison.review":
        allowed = {"executed", "ended", "terminated"}
    elif form.endswith("template.patch"):
        allowed = {"active"}
    else:
        allowed = {"finalized"} if form.endswith(".correct") else {"draft"}
    return "available" if state["status"] in allowed else "source_unavailable"


def compose_inspection_forms():
    actions = {
        "inspection.report.areas.replace": "report.areas",
        "inspection.report.correct": "report.create",
    }
    result = {}
    for form in INSPECTION_SCHEMAS:
        kind = inspection_source_kind(form)
        reader: InspectionRecoveryReader = SQLiteInspectionRecoveryReader(kind)
        action = actions.get(form, form.removeprefix("inspection."))
        result[form] = RecoveryBinding(
            kind,
            action,
            "inspection",
            reader,
            lambda source, payload, key, form=form, action=action: inspection_fingerprint(
                form,
                action,
                source,
                payload,
                key,
            ),
            kind or "condition_template",
            fingerprint_payload=reader.correction_payload if form.endswith(".correct") else None,
        )
    return result
