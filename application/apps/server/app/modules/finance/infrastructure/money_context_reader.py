"""Transaction-aware, source-owned summary adapter for composed read models."""

from sqlalchemy.exc import DBAPIError

from app.modules.audit.application.read_marker import AuditReadMarker
from app.modules.finance.application.money_models import MoneyBusy, MoneyUnavailable
from app.modules.finance.application.money_snapshot import summary_on_snapshot
from app.modules.finance.infrastructure.money_unit_of_work import (
    SQLiteMoneyReadTransaction,
    _local_date,
)
from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations


class SQLiteMoneyContextReader:
    def __init__(
        self,
        portfolio: PortfolioLocationRelations,
        leases: LeaseLocationRelation,
        marker: AuditReadMarker,
    ):
        self.portfolio, self.leases, self.marker = portfolio, leases, marker

    def summary(self, connection, query, *, as_of, identity, property_scope=None):
        # Function registration does not open a session or alter retained data.
        connection.connection.driver_connection.create_function(
            "property_local_date", 2, _local_date, deterministic=True
        )
        try:
            return summary_on_snapshot(
                SQLiteMoneyReadTransaction(
                    connection, self.portfolio, self.leases, self.marker, property_scope
                ),
                query,
                as_of=as_of,
                identity=identity,
            )
        except DBAPIError as error:
            if "locked" in str(error.orig).lower() or "busy" in str(error.orig).lower():
                raise MoneyBusy("The workspace is busy. Retry the money view.") from error
            raise MoneyUnavailable("Recorded money could not be read safely.") from error
