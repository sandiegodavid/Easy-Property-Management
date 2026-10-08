"""Source-owned operational coverage facts, not domain approvals."""

from dataclasses import dataclass
from typing import Literal
import hashlib
import json

CoverageArea = Literal["occupancy", "lease", "rent", "deposit", "maintenance"]
CoverageCause = Literal[
    "occupancy_unknown_or_conflicting",
    "availability_unknown",
    "lease_context_missing",
    "lease_context_ambiguous_or_missing_term",
    "no_applicable_lease",
    "no_current_executed_lease",
    "no_deposit_terms",
    "rent_expectations_missing",
    "rent_synchronization_required",
    "deposit_account_missing",
    "deposit_terms_changed",
    "source_changed",
    "review_date_reached",
    "manual_review_required",
]
AREAS = ("occupancy", "lease", "rent", "deposit", "maintenance")
MAX_COVERAGE_SUBJECTS = 500
COVERAGE_PREVIEW_LIMIT = 5


def bounded_subjects(values):
    unique = tuple(dict.fromkeys(values))
    if len(unique) > MAX_COVERAGE_SUBJECTS:
        raise ValueError("Coverage batches permit at most 500 distinct subjects.")
    return unique


def evidence_revision(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class CoverageSubject:
    kind: Literal["property", "space"]
    id: str


@dataclass(frozen=True)
class CoverageFacts:
    area: CoverageArea
    revision: str
    time_zone: str
    missing: tuple[CoverageCause, ...] = ()
    needs_review: tuple[CoverageCause, ...] = ()
    not_applicable_reason: CoverageCause | None = None
    requires_manual_review: bool = False
    lease_id: str | None = None
