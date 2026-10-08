"""Revision-safe review acknowledgment; no source mutation or copied source facts."""

import json
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.operator.application.coverage_models import (
    CoverageReview,
    coverage_view,
    review_audit_snapshot,
)
from app.modules.operator.domain.models import (
    OperatorConflict,
    OperatorError,
    OperatorNotFound,
    OperatorUnavailable,
    OperatorSectionUnavailable,
    canonical,
    fingerprint,
    identifier,
)
from app.platform.coverage import AREAS, CoverageSubject
from app.modules.operator.application.ports import OperatorUnitOfWork


class OperatorCoverageService:
    def __init__(self, unit_of_work: OperatorUnitOfWork, *, runtime, now=lambda: datetime.now(UTC)):
        self.unit_of_work, self.runtime, self.now = unit_of_work, runtime, now

    def _instant(self, write=False):
        runtime = self.runtime()
        if runtime.state != "ready" or write and not runtime.can_write:
            raise OperatorUnavailable("Open and validate the workspace before this operation.")
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise OperatorUnavailable("Coverage clock is unavailable.")
        return instant.astimezone(UTC)

    @staticmethod
    def _subject(kind, subject_id, area):
        identifier(subject_id)
        if area not in AREAS or kind != ("property" if area == "maintenance" else "space"):
            raise OperatorError("Coverage area does not support this subject.")
        return CoverageSubject(kind, subject_id)

    def read(self, kind, subject_id, area):
        subject = self._subject(kind, subject_id, area)
        instant = self._instant()

        def read(tx):
            try:
                facts = tx.coverage_facts(subject, area, as_of=instant)
            except OperatorSectionUnavailable:
                return {
                    "availability": "unavailable",
                    "area": area,
                    "subjectKind": kind,
                    "subjectId": subject_id,
                    "asOf": instant.isoformat(),
                    "state": None,
                    "evidenceRevision": None,
                    "causes": [],
                }
            if facts is None:
                raise OperatorNotFound("Coverage subject was not found.")
            return coverage_view(subject, facts, tx.coverage_review(subject, area), instant)

        return self.unit_of_work.read(read)

    def review(self, command: CoverageReview):
        subject = self._subject(command.subject_kind, str(command.subject_id), command.area)
        if not command.reason.strip():
            raise OperatorError("A review basis is required.")
        instant = self._instant(write=True)
        request = command.model_dump(mode="json", exclude={"idempotency_key"})
        digest = fingerprint(request)

        def write(tx):
            previous = tx.coverage_operation(str(command.idempotency_key))
            if previous:
                if previous["request_fingerprint"] != digest:
                    raise OperatorConflict("Review key was used with different content.")
                return json.loads(previous["result_json"])
            facts = tx.coverage_facts(subject, command.area, as_of=instant)
            if facts is None:
                raise OperatorNotFound("Coverage subject was not found.")
            if facts.revision != command.expected_evidence_revision:
                raise OperatorConflict("Coverage evidence has changed.")
            if command.basis == "not_applicable" and not facts.not_applicable_reason:
                raise OperatorError("Source rules do not permit non-applicability.")
            day = instant.astimezone(ZoneInfo(facts.time_zone)).date()
            if command.next_review_on and command.next_review_on <= day:
                raise OperatorError("Next review must be after the property-local date.")
            row = {
                "id": str(uuid4()),
                "subject_kind": subject.kind,
                "subject_id": subject.id,
                "area": command.area,
                "time_zone": facts.time_zone,
                "evidence_revision": facts.revision,
                "basis": command.basis,
                "reason": command.reason.strip(),
                "next_review_on": command.next_review_on.isoformat()
                if command.next_review_on
                else None,
                "idempotency_key": str(command.idempotency_key),
                "request_fingerprint": digest,
                "request_json": canonical(request),
                "created_at": instant.isoformat(),
                "correlation_id": str(uuid4()),
            }
            result = {**coverage_view(subject, facts, row, instant), "operationId": row["id"]}
            row["result_json"] = canonical(result)
            tx.insert_coverage_review(row)
            tx.record_change(
                entity_type="operator_coverage_review",
                entity_id=row["id"],
                action="recorded",
                before=None,
                after=review_audit_snapshot(row, result),
                correlation_id=row["correlation_id"],
                occurred_at=instant,
            )
            return result

        return self.unit_of_work.write(write)

    def operation(self, key: str):
        identifier(key)
        self._instant()

        def read(tx):
            row = tx.coverage_operation(key)
            if row is None:
                raise OperatorNotFound("Coverage review operation was not found.")
            return json.loads(row["result_json"])

        return self.unit_of_work.read(read)
