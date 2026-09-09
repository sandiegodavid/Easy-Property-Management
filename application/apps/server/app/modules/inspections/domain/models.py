"""Immutable INSP-001 records."""

from __future__ import annotations

from dataclasses import asdict, dataclass


def _camel(values: dict[str, object]) -> dict[str, object]:
    return {"".join((parts[0], *(part.title() for part in parts[1:]))): value
            for key, value in values.items() for parts in (key.split("_"),)}


@dataclass(frozen=True)
class ConditionReport:
    id: str; lease_id: str; space_id: str; report_kind: str; status: str; walkthrough_on: str
    conducted_by: str; tenant_presence: str; supersedes_report_id: str | None; correction_reason: str | None
    timing_exception_reason: str | None; general_notes: str | None; finalized_at: str | None; created_at: str; updated_at: str
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))


@dataclass(frozen=True)
class ConditionArea:
    id: str; condition_report_id: str; display_name: str; normalized_name: str; sort_order: int; notes: str | None
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))


@dataclass(frozen=True)
class ConditionObservation:
    id: str; condition_area_id: str; item_name: str; normalized_name: str; condition_state: str; cleanliness_state: str | None
    observed_on: str; is_completed: bool; completed_at: str | None; notes: str | None; sort_order: int
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))


@dataclass(frozen=True)
class ConditionAcknowledgment:
    id: str; condition_report_id: str; lease_participant_id: str; status: str; acknowledged_on: str | None; notes: str | None
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))


@dataclass(frozen=True)
class ConditionComparison:
    id: str; lease_id: str; pre_report_id: str; post_report_id: str; pre_observation_id: str | None; post_observation_id: str | None; comparison_state: str; operator_notes: str | None; created_at: str; updated_at: str
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))


@dataclass(frozen=True)
class ConditionChecklistTemplate:
    id: str; display_name: str; normalized_name: str; applicability: str; notes: str | None; archived_at: str | None; created_at: str; updated_at: str
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))


@dataclass(frozen=True)
class ConditionChecklistTemplateItem:
    id: str; template_id: str; area_display_name: str; area_normalized_name: str; item_name: str; item_normalized_name: str; sort_order: int; created_at: str
    def to_dict(self) -> dict[str, object]: return _camel(asdict(self))
