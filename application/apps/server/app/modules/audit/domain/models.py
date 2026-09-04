"""Portable audit event values and snapshot safety policies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Protocol, Sequence
from uuid import uuid4

ActorKind = Literal["local_operator", "system", "connector", "ai_assistant"]
ACTOR_KINDS = frozenset({"local_operator", "system", "connector", "ai_assistant"})
AUDIT_ACTIONS = frozenset({
    "created", "updated", "deleted", "restored", "status_changed", "approved", "rejected", "imported",
    "ingested", "ai_draft_created", "ai_reviewed", "migration_applied", "operation_summary",
})
_SENSITIVE_FIELD = re.compile(r"(?:access|refresh|client)?_?(?:token|secret)|password|passphrase|api_?key|account_?number|credentials?", re.I)
_MISSING = object()


class AuditSnapshotPolicy(Protocol):
    """A domain-owned boundary for auditable fields and history presentation."""

    schema_version: int

    def validate(self, snapshot: Mapping[str, Any] | None) -> None: ...

    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class DefaultAuditSnapshotPolicy:
    """Conservative shared policy until a domain supplies a narrower allowlist."""
    schema_version: int = 1

    def validate(self, snapshot: Mapping[str, Any] | None) -> None:
        _validate_value(snapshot, "$")
        if snapshot is not None:
            try:
                json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
            except (TypeError, ValueError) as error:
                raise ValueError("Audit snapshots must be portable JSON values.") from error

    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        return None if snapshot is None else _redact_value(snapshot)


DEFAULT_SNAPSHOT_POLICY = DefaultAuditSnapshotPolicy()


class AuditPresentationPolicyError(RuntimeError):
    """A persisted snapshot cannot safely be rendered without its owning policy."""


class AuditSnapshotPolicyRegistry:
    """Selects the owning domain's presentation policy for persisted snapshots."""

    def __init__(self, policies: Mapping[tuple[str, int], AuditSnapshotPolicy] | None = None) -> None:
        self._policies = dict(policies or {})

    def policy_for(self, entity_type: str, schema_version: int) -> AuditSnapshotPolicy:
        try:
            return self._policies[(entity_type, schema_version)]
        except KeyError as error:
            raise AuditPresentationPolicyError(
                f"No audit presentation policy is registered for {entity_type} schema version {schema_version}."
            ) from error


@dataclass(frozen=True)
class AuditEvent:
    id: str
    occurred_at: datetime
    entity_type: str
    entity_id: str
    action: str
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None
    changed_fields: tuple[str, ...]
    reason: str | None
    actor_kind: ActorKind
    actor_reference: str | None
    correlation_id: str
    schema_version: int = 1

    @classmethod
    def change(cls, *, entity_type: str, entity_id: str, action: str, before_snapshot: dict[str, Any] | None,
               after_snapshot: dict[str, Any] | None, actor_kind: ActorKind = "local_operator", reason: str | None = None,
               actor_reference: str | None = None, correlation_id: str | None = None,
               snapshot_policy: AuditSnapshotPolicy = DEFAULT_SNAPSHOT_POLICY) -> "AuditEvent":
        _validate_classification(entity_type, entity_id, action, actor_kind)
        snapshot_policy.validate(before_snapshot); snapshot_policy.validate(after_snapshot)
        return cls(str(uuid4()), datetime.now(UTC), entity_type, entity_id, action, before_snapshot, after_snapshot,
                   changed_paths(before_snapshot, after_snapshot), reason, actor_kind, actor_reference,
                   correlation_id or str(uuid4()), snapshot_policy.schema_version)

    def to_dict(self, snapshot_policy: AuditSnapshotPolicy) -> dict[str, Any]:
        return {"id": self.id, "occurredAt": self.occurred_at.isoformat(), "entityType": self.entity_type,
                "entityId": self.entity_id, "action": self.action, "before": snapshot_policy.redact(self.before_snapshot),
                "after": snapshot_policy.redact(self.after_snapshot), "changedFields": list(self.changed_fields),
                "reason": self.reason, "actorKind": self.actor_kind, "actorReference": self.actor_reference,
                "correlationId": self.correlation_id, "schemaVersion": self.schema_version}


def changed_paths(before: Any, after: Any, prefix: str = "") -> tuple[str, ...]:
    if before is _MISSING or after is _MISSING: return (prefix or "$",)
    if before == after: return ()
    if isinstance(before, dict) and isinstance(after, dict):
        return tuple(path for key in sorted(set(before) | set(after)) for path in changed_paths(
            before.get(key, _MISSING), after.get(key, _MISSING), f"{prefix}.{key}" if prefix else key))
    return (prefix or "$",)


def validate_snapshot(snapshot: dict[str, Any] | None, path: str = "") -> None:
    """Compatibility wrapper for the default domain policy."""
    DEFAULT_SNAPSHOT_POLICY.validate(snapshot)


def _validate_classification(entity_type: str, entity_id: str, action: str, actor_kind: str) -> None:
    if not all(isinstance(value, str) and value.strip() for value in (entity_type, entity_id, action)):
        raise ValueError("Audit entity type, entity ID, and action must be non-empty strings.")
    if actor_kind not in ACTOR_KINDS:
        raise ValueError(f"Unsupported audit actor kind: {actor_kind}")
    if action not in AUDIT_ACTIONS and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", action):
        raise ValueError(f"Unsupported audit action: {action}")


def _validate_value(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"Audit snapshot key must be a string at {path}")
            child_path = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if _SENSITIVE_FIELD.fullmatch(normalized) or normalized.endswith(("token", "secret", "apikey", "accountnumber")):
                raise ValueError(f"Audit snapshots must not contain secret field: {child_path}")
            _validate_value(child, child_path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value): _validate_value(child, f"{path}[{index}]")


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): ("[redacted]" if _SENSITIVE_FIELD.fullmatch(re.sub(r"[^a-z0-9]", "", str(key).lower())) else _redact_value(child)) for key, child in value.items()}
    if isinstance(value, list): return [_redact_value(child) for child in value]
    return value
