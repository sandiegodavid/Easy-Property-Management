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
    allowed_confidence_labels: frozenset[str] = frozenset()
    permits_calibrated_confidence: bool = False
    required_data_classes: frozenset[str] = frozenset()
    permitted_locations: frozenset[str] = frozenset({"on_device", "cloud"})
    allowed_models: frozenset[str] = frozenset()
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
