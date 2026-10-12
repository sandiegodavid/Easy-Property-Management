"""Coverage review recovery on the caller's database snapshot."""

from datetime import UTC, datetime
import json
from sqlalchemy import select
from app.platform.coverage import CoverageSubject
from app.modules.operator.application.coverage_models import CoverageReview
from app.modules.operator.application.coverage_sources import CoverageSources
from app.modules.operator.domain.models import fingerprint, OperatorConflict, OperatorError
from app.modules.operator.infrastructure.sqlalchemy_models import OperatorCoverageReviewModel
from app.modules.operator.infrastructure.sqlalchemy_models import OperatorRecoveryModel
from app.platform.migration_errors import MigrationSchemaError


class SQLiteCoverageRecoveryReader:
    def __init__(self, sources: CoverageSources):
        self.sources = sources

    def validate(self, connection, payload):
        kind, area = payload["subjectKind"], payload["area"]
        if kind != ("property" if area == "maintenance" else "space"):
            return "unsupported_source"
        facts = self.sources.facts(
            connection,
            CoverageSubject(kind, payload["subjectId"]),
            area,
            as_of=datetime.now(UTC),
        )
        if facts is None:
            return "source_missing"
        return (
            "available"
            if facts.revision == payload["expectedEvidenceRevision"]
            else "source_changed"
        )

    @staticmethod
    def fingerprint(payload, key):
        try:
            command = CoverageReview(
                subject_kind=payload["subjectKind"],
                subject_id=payload["subjectId"],
                area=payload["area"],
                expected_evidence_revision=payload["expectedEvidenceRevision"],
                basis=payload.get("basis", "acknowledged"),
                reason=payload.get("reason") or "",
                next_review_on=payload.get("nextReviewOn"),
                idempotency_key=key,
            )
        except ValueError as error:
            raise OperatorError(
                "Complete a valid coverage review before starting an attempt."
            ) from error
        if not command.reason.strip():
            raise OperatorError("A review reason is required.")
        return fingerprint(command.model_dump(mode="json", exclude={"idempotency_key"}))

    @staticmethod
    def outcome(connection, key, digest):
        table = OperatorCoverageReviewModel.__table__
        row = (
            connection.execute(select(table).where(table.c.idempotency_key == key))
            .mappings()
            .first()
        )
        if row is None:
            return None
        if row["request_fingerprint"] != digest:
            raise OperatorConflict("Review receipt belongs to a different request.")
        return {
            "sourceKind": row["subject_kind"],
            "sourceId": row["subject_id"],
            "receiptId": row["id"],
            "attemptKey": key,
        }


def validate_coverage_recovery(connection):
    table = OperatorRecoveryModel.__table__
    try:
        for row in connection.execute(
            select(table).where(table.c.form_key == "coverage.review")
        ).mappings():
            if any(
                row[key] is not None for key in ("source_kind", "source_id", "base_source_revision")
            ):
                raise ValueError("Invalid coverage recovery identity.")
            if row["attempt_key"] is None:
                continue
            digest = SQLiteCoverageRecoveryReader.fingerprint(
                json.loads(row["payload_json"]), row["attempt_key"]
            )
            if digest != row["request_fingerprint"]:
                raise ValueError("Invalid coverage recovery fingerprint.")
            if row["receipt_json"] is not None and json.loads(
                row["receipt_json"]
            ) != SQLiteCoverageRecoveryReader.outcome(connection, row["attempt_key"], digest):
                raise ValueError("Coverage recovery lost its owning receipt.")
    except (ValueError, TypeError, KeyError, OperatorError) as error:
        raise MigrationSchemaError("Retained coverage recovery is invalid.") from error
