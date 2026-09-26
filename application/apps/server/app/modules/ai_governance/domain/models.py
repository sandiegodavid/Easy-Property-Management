"""Portable values and fail-closed policies for governed AI work."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

_SECRET = re.compile(r"(?:access|refresh|client)?_?(?:token|secret|password|passphrase|api_?key|credential|account_?number)", re.I)
_SECRET_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|(?:api[_ -]?key|token|password|account[_ -]?number)\s*[:=]\s*\S+|\b\d{8,19}\b)", re.I)


class AiGovernanceError(RuntimeError):
    code = "ai_governance_error"


class AiConflictError(AiGovernanceError):
    code = "ai_conflict"


class AiNotFoundError(AiGovernanceError):
    code = "ai_not_found"


class AiValidationError(AiGovernanceError):
    code = "ai_validation"


@dataclass(frozen=True)
class RedactionRule:
    mode: str
    limit: int | None = None
    transformer: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class RedactionProfile:
    name: str
    version: int
    fields: Mapping[str, RedactionRule]
    summary: Mapping[str, str]

    def redact(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(candidate, Mapping):
            raise AiValidationError("AI candidate input must be an object.")
        unknown = set(candidate) - set(self.fields)
        if unknown:
            raise AiValidationError("AI candidate input contains unregistered fields.")
        result: dict[str, Any] = {}
        for key, rule in self.fields.items():
            if key not in candidate or rule.mode == "drop":
                continue
            value = candidate[key]
            _reject_secret(value, key)
            if rule.mode == "allow":
                result[key] = value
            elif rule.mode == "mask":
                result[key] = "[redacted]"
            elif rule.mode == "truncate":
                if not isinstance(value, str) or rule.limit is None:
                    raise AiValidationError("AI redaction truncation requires bounded text.")
                result[key] = value[:rule.limit]
            elif rule.mode == "transform" and rule.transformer is not None:
                result[key] = rule.transformer(value)
            else:
                raise AiValidationError("AI redaction profile contains an unsupported rule.")
        _reject_secret(result, "$")
        return result


@dataclass(frozen=True)
class ConfidenceContract:
    """Registered, bounded provenance for an optional AI confidence value."""
    labels: frozenset[str]
    calibration_source: str
    required_provenance_fields: frozenset[str] = frozenset()
    numeric_field: str = "score"

    def __post_init__(self) -> None:
        if (not self.labels or not isinstance(self.calibration_source, str)
                or not self.calibration_source.strip() or len(self.calibration_source) > 120):
            raise ValueError("AI confidence contracts require bounded labels and calibration provenance.")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.numeric_field):
            raise ValueError("AI confidence numeric fields must be bounded codes.")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field) for field in self.required_provenance_fields):
            raise ValueError("AI confidence provenance fields must be bounded codes.")

    def validate(self, confidence: Mapping[str, Any] | None) -> None:
        if confidence is None:
            return
        if not isinstance(confidence, Mapping) or set(confidence) != {
            "label", self.numeric_field, "calibration_source", *self.required_provenance_fields,
        }:
            raise AiValidationError("AI confidence does not match its registered provenance contract.")
        if confidence["label"] not in self.labels or confidence["calibration_source"] != self.calibration_source:
            raise AiValidationError("AI confidence provenance is not registered for this action.")
        numeric = confidence[self.numeric_field]
        if type(numeric) not in {int, float} or not 0 <= numeric <= 1:
            raise AiValidationError("AI confidence score must be a number from zero through one.")
        for field in self.required_provenance_fields:
            value = confidence[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 120:
                raise AiValidationError("AI confidence provenance must contain bounded text.")


def qualified_model_identity(adapter_id: str, adapter_version: str, model_identifier: str) -> str:
    """Stable provider/version-qualified identifier persisted in action allowlists."""
    if any(not isinstance(value, str) or not value or len(value) > 80 or any(marker in value for marker in "@:") for value in (adapter_id, adapter_version)):
        raise AiValidationError("AI model identity is invalid.")
    if not isinstance(model_identifier, str) or not model_identifier or len(model_identifier) > 240 or any(character.isspace() for character in model_identifier):
        raise AiValidationError("AI model identity is invalid.")
    return f"{adapter_id}@{adapter_version}:{model_identifier}"


@dataclass(frozen=True)
class AiActionDefinition:
    action_type: str
    owning_module: str
    source_entity_types: frozenset[str]
    redaction_profile: tuple[str, int]
    prompt_template_id: str
    prompt_template_version: int
    output_schema_version: int
    entity_kind: str
    validate_candidate: Callable[[Mapping[str, Any]], None]
    validate_payload: Callable[[Mapping[str, Any]], None]
    validate_provider_request: Callable[[Mapping[str, Any]], None] | None = None
    confidence_contract: ConfidenceContract | None = None
    required_data_classes: frozenset[str] = frozenset()
    # The action declares what it needs; the selected adapter must declare
    # that it can safely provide every one of these capabilities/modalities.
    required_capabilities: frozenset[str] = frozenset()
    required_input_modalities: frozenset[str] = frozenset({"text"})
    permitted_locations: frozenset[str] = frozenset({"on_device", "cloud"})
    allowed_model_identities: frozenset[str] = frozenset()
    max_provider_request_bytes: int = 16_384
    max_prompt_tokens: int = 4_096
    max_completion_tokens: int = 1_024
    max_runs_per_utc_day: int = 100
    approval_effect: str = "advisory_only"
    requires_result_reference: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.action_type):
            raise ValueError("AI action types must be bounded codes.")
        if self.approval_effect not in {"create", "update", "advisory_only"}:
            raise ValueError("Unsupported AI approval effect.")
        if min(self.max_provider_request_bytes, self.max_prompt_tokens, self.max_completion_tokens, self.max_runs_per_utc_day) < 1:
            raise ValueError("AI action limits must be positive.")
        if not self.required_input_modalities:
            raise ValueError("AI actions must declare at least one input modality.")
        if any(not isinstance(identity, str) or not re.fullmatch(r"[^@:\s]{1,80}@[^@:\s]{1,80}:\S{1,240}", identity) for identity in self.allowed_model_identities):
            raise ValueError("AI action model allowlists must use provider/version-qualified identities.")

    def validate_confidence(self, confidence: Mapping[str, Any] | None) -> None:
        if self.confidence_contract is None:
            if confidence is not None:
                raise AiValidationError("AI action does not permit confidence metadata.")
            return
        self.confidence_contract.validate(confidence)


def validate_provider_metadata(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    provider_request_id: str | None,
) -> tuple[int | None, int | None, str | None]:
    """Keep provider-provided metadata bounded and safe to retain."""
    for value in (prompt_tokens, completion_tokens):
        if value is not None and (type(value) is not int or value < 0):
            raise AiValidationError("AI provider usage metadata is invalid.")
    if provider_request_id is not None:
        if (not isinstance(provider_request_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", provider_request_id)
                or _SECRET_VALUE.search(provider_request_id)):
            raise AiValidationError("AI provider request metadata is invalid.")
    return prompt_tokens, completion_tokens, provider_request_id


class AiActionRegistry:
    def __init__(self, definitions: tuple[AiActionDefinition, ...] = ()) -> None:
        self._definitions: dict[str, AiActionDefinition] = {}
        for definition in definitions:
            if definition.action_type in self._definitions:
                raise ValueError("Duplicate AI action type.")
            self._definitions[definition.action_type] = definition

    def require(self, action_type: str) -> AiActionDefinition:
        try:
            return self._definitions[action_type]
        except KeyError as error:
            raise AiValidationError("AI action is not registered.") from error

    def all(self) -> tuple[AiActionDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


class RedactionProfileRegistry:
    def __init__(self, profiles: tuple[RedactionProfile, ...] = ()) -> None:
        self._profiles = {(profile.name, profile.version): profile for profile in profiles}
        if len(self._profiles) != len(profiles):
            raise ValueError("Duplicate AI redaction profile.")

    def require(self, name: str, version: int) -> RedactionProfile:
        try:
            return self._profiles[(name, version)]
        except KeyError as error:
            raise AiValidationError("AI redaction profile is not registered.") from error

    def all(self) -> tuple[RedactionProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))


def canonical_json(value: Any, *, maximum_bytes: int | None = None) -> str:
    _reject_secret(value, "$")
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise AiValidationError("AI values must be canonical JSON.") from error
    if maximum_bytes is not None and len(result.encode()) > maximum_bytes:
        raise AiValidationError("AI value exceeds its registered size limit.")
    return result


def fingerprint(value: Any, *, maximum_bytes: int | None = None) -> str:
    return sha256(canonical_json(value, maximum_bytes=maximum_bytes).encode()).hexdigest()


def validate_uuid(value: str, name: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise AiValidationError(f"{name} must be a UUID.") from error


def _reject_secret(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise AiValidationError("AI JSON keys must be text.")
            if _SECRET.fullmatch(re.sub(r"[^a-z0-9]", "", key.lower())):
                raise AiValidationError("AI input contains a secret field.")
            _reject_secret(child, f"{path}.{key}")
    elif isinstance(value, list):
        for child in value:
            _reject_secret(child, path)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise AiValidationError("AI input contains a secret or account identifier.")
