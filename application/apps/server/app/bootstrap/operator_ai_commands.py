"""Approved AI OPS bindings; never invokes credentials, providers or approvals."""

from app.modules.ai_governance.application.commands import AiCommand
from app.modules.ai_governance.application.external_effects import external_fingerprint
from app.modules.ai_governance.application.registry import ACTION_REGISTRY
from app.modules.ai_governance.domain.models import AiValidationError
from app.modules.ai_governance.infrastructure.recovery_reader import SQLiteAiRecoveryReader
from app.modules.operator.application.ai_forms import AI_SCHEMAS, ai_source_kind
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError


AI_ACTIONS = {
    "ai.settings.update": "settings",
    "ai.connection.create": "connection_create",
    "ai.connection.update": "connection_update",
    "ai.connection.disclosure": "disclosure",
    "ai.action_limit.update": "limit",
    "ai.draft.edit": "edited",
    "ai.draft.approve": "approved",
    "ai.draft.dismiss": "dismissed",
    "ai.connection.credential.set": "credential_set",
    "ai.connection.credential.delete": "credential_delete",
    "ai.connection.probe": "connection_probe",
}
CONNECTION_FIELDS = {
    "label": "label",
    "adapterId": "adapter_id",
    "adapterVersion": "adapter_version",
    "modelIdentifier": "model_identifier",
    "executionLocation": "execution_location",
    "enabled": "enabled",
    "modelArtifactDigest": "model_artifact_digest",
    "quantization": "quantization",
    "runtimeId": "runtime_id",
    "runtimeVersion": "runtime_version",
}


def require_fields(payload, names):
    if any(payload.get(name) is None for name in names):
        raise OperatorError("Complete the AI command fields.")


def ai_request(action, payload):
    if action == "settings":
        return {
            "kill_switch": payload.get("killSwitch"),
            "built_in_enabled": payload.get("builtInEnabled"),
            "default_connection_provided": "defaultConnectionId" in payload,
            "default_connection_id": payload.get("defaultConnectionId"),
        }
    if action.startswith("connection_"):
        if action == "connection_create":
            require_fields(
                payload,
                ("label", "adapterId", "adapterVersion", "modelIdentifier", "executionLocation"),
            )
            result = {name: payload.get(public) for public, name in CONNECTION_FIELDS.items()}
            result["enabled"] = payload.get("enabled", True)
            if type(result["enabled"]) is not bool:
                raise OperatorError("Complete the enabled setting.")
            result["label"] = result["label"].strip()
            if not result["label"]:
                raise OperatorError("Complete the connection label.")
            return result
        return {
            name: payload[public] for public, name in CONNECTION_FIELDS.items() if public in payload
        }
    if action == "disclosure":
        require_fields(payload, ("disclosureVersion", "dataClasses"))
        return {
            "disclosureVersion": payload["disclosureVersion"],
            "dataClasses": sorted(set(payload["dataClasses"])),
        }
    if action == "limit":
        require_fields(
            payload,
            (
                "enabled",
                "maxRunsPerUtcDay",
                "maxPromptTokens",
                "maxCompletionTokens",
                "allowedModels",
            ),
        )
        return {
            "enabled": payload["enabled"],
            "connection_id": payload.get("connectionId"),
            "max_runs_per_utc_day": payload["maxRunsPerUtcDay"],
            "max_prompt_tokens": payload["maxPromptTokens"],
            "max_completion_tokens": payload["maxCompletionTokens"],
            "allowed_models": payload["allowedModels"],
        }
    result = {"operatorNote": payload.get("operatorNote")}
    if action != "approved":
        if action == "edited":
            require_fields(payload, ("draftPayload",))
        result["payload"] = payload.get("draftPayload") if action == "edited" else None
    return result


def ai_fingerprint(action, source, payload, key):
    try:
        if action in {"credential_set", "credential_delete", "connection_probe"}:
            return external_fingerprint(action, source, payload.get("expectedRevision"))
        target = "new" if action == "connection_create" else source
        revision = payload.get(
            "version" if action in {"edited", "approved", "dismissed"} else "expectedRevision"
        )
        return AiCommand(action, target, revision, key, ai_request(action, payload)).fingerprint
    except AiValidationError as error:
        raise OperatorError(str(error)) from error


def compose_ai_forms(actions=ACTION_REGISTRY):
    return {
        key: RecoveryBinding(
            ai_source_kind(key),
            action,
            "ai_external"
            if action in {"credential_set", "credential_delete", "connection_probe"}
            else "ai",
            SQLiteAiRecoveryReader(ai_source_kind(key) or "ai_connection", actions),
            lambda source, payload, attempt, action=action: ai_fingerprint(
                action, source, payload, attempt
            ),
            result_kind=ai_source_kind(key) or "ai_connection",
        )
        for key, action in AI_ACTIONS.items()
        if key in AI_SCHEMAS
    }


def ai_form_state(binding, state):
    if binding.family == "ai_external" and state["external_pending"]:
        return "source_unavailable"
    if binding.source_kind == "ai_draft":
        return "available" if state["status"] in {"proposed", "edited"} else "source_unavailable"
    if binding.action == "disclosure" and state["execution_location"] != "cloud":
        return "source_unavailable"
    return "available"
