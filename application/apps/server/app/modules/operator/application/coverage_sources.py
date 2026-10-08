"""Coverage derivation over source-owned application facts on a caller snapshot."""

from dataclasses import dataclass
from collections.abc import Collection, Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.portfolio.application.coverage_ports import PortfolioCoverageReader
from app.modules.leases.application.coverage_ports import LeaseCoverageReader
from app.modules.finance.application.coverage_ports import FinanceCoverageReader
from app.modules.maintenance.application.coverage_ports import MaintenanceCoverageReader
from app.platform.coverage import (
    CoverageArea,
    CoverageSubject,
    CoverageFacts,
    bounded_subjects,
    evidence_revision,
)


@dataclass(frozen=True)
class CoverageSources:
    portfolio: PortfolioCoverageReader
    leases: LeaseCoverageReader
    finance: FinanceCoverageReader
    maintenance: MaintenanceCoverageReader

    def facts(self, connection, subject, area, *, as_of):
        return self.facts_for_subjects(connection, [(subject, area)], as_of=as_of).get(
            (subject, area)
        )

    def facts_for_subjects(
        self,
        connection,
        references: Collection[tuple[CoverageSubject, CoverageArea]],
        *,
        as_of: datetime,
    ) -> Mapping[tuple[CoverageSubject, CoverageArea], CoverageFacts]:
        references = tuple(dict.fromkeys(references))
        subjects = bounded_subjects(subject for subject, _ in references)
        locations = self.portfolio.locations(connection, subjects, as_of=as_of)
        dates = {
            subject.id: as_of.astimezone(ZoneInfo(locations[subject].time_zone)).date().isoformat()
            for subject, area in references
            if subject in locations and area not in {"maintenance", "occupancy"}
        }
        leases = self.leases.relevant_contexts(connection, dates)
        maintenance = self.maintenance.evidence_revisions(
            connection,
            [
                locations[subject].property_id
                for subject, area in references
                if subject in locations and area == "maintenance"
            ],
        )
        results, finance_contexts, finance_areas = {}, {}, set()
        for subject, area in references:
            location = locations.get(subject)
            if location is None:
                continue
            lease = leases.get(subject.id)
            result = self._derive(area, location, lease, maintenance)
            if result is not None:
                results[subject, area] = result
            else:
                finance_contexts[subject.id] = (lease, location.time_zone, dates[subject.id])
                finance_areas.add((subject.id, area))
        finance = self.finance.facts_for_contexts(connection, finance_contexts, finance_areas)
        for subject, area in references:
            if (subject.id, area) in finance:
                results[subject, area] = finance[subject.id, area]
        return results

    @staticmethod
    def _derive(area, location, lease, maintenance):
        if area == "maintenance":
            return CoverageFacts(
                area,
                evidence_revision(
                    {
                        "source": maintenance[location.property_id],
                        "zone": location.time_zone,
                    }
                ),
                location.time_zone,
                requires_manual_review=True,
            )
        if area == "occupancy":
            missing = tuple(
                code
                for condition, code in (
                    (
                        location.occupancy in ("unknown", "conflicting"),
                        "occupancy_unknown_or_conflicting",
                    ),
                    (location.availability == "unknown", "availability_unknown"),
                )
                if condition
            )
            return CoverageFacts(area, location.revision, location.time_zone, missing=missing)
        revision = evidence_revision(
            {
                "lease": lease,
                "zone": location.time_zone,
                "required_source": location.occupancy_source_id
                if location.occupancy_source == "lease"
                else None,
            }
        )
        if lease is None:
            required = location.occupancy == "occupied" and location.occupancy_source == "lease"
            return CoverageFacts(
                area,
                revision,
                location.time_zone,
                missing=("lease_context_missing",) if required else (),
                not_applicable_reason=None if required else "no_applicable_lease",
            )
        if lease["ambiguous"] or lease["term_id"] is None:
            return CoverageFacts(
                area,
                revision,
                location.time_zone,
                missing=("lease_context_ambiguous_or_missing_term",),
                lease_id=lease["lease_id"],
            )
        if lease["status"] != "executed" and area in ("lease", "rent"):
            required = (
                area == "lease"
                and location.occupancy == "occupied"
                and location.occupancy_source == "lease"
            )
            return CoverageFacts(
                area,
                revision,
                location.time_zone,
                missing=("lease_context_missing",) if required else (),
                not_applicable_reason=None if required else "no_current_executed_lease",
                lease_id=lease["lease_id"],
            )
        if area == "lease":
            return CoverageFacts(area, revision, location.time_zone, lease_id=lease["lease_id"])
        return None
