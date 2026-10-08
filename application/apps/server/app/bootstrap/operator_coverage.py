"""Single explicit composition of source-owned coverage readers."""

from app.modules.operator.application.coverage_sources import CoverageSources
from app.modules.portfolio.infrastructure.coverage_reader import SQLitePortfolioCoverageReader
from app.modules.leases.infrastructure.coverage_reader import SQLiteLeaseCoverageReader
from app.modules.finance.infrastructure.coverage_reader import SQLiteFinanceCoverageReader
from app.modules.maintenance.infrastructure.coverage_reader import SQLiteMaintenanceCoverageReader
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker


def compose_coverage_sources():
    marker = SQLiteAuditReadMarker()
    return CoverageSources(
        SQLitePortfolioCoverageReader(),
        SQLiteLeaseCoverageReader(),
        SQLiteFinanceCoverageReader(marker),
        SQLiteMaintenanceCoverageReader(marker),
    )
