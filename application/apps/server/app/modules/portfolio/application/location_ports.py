"""Read-only SQL composition boundary for retained portfolio locations.

Relations have one row per retained property/space, including archived rows.
Consumers may select/join/filter them only on their caller-owned read connection.
No financial facts, sessions, or arbitrary SQL are accepted by this contract.
"""

from typing import Protocol

from sqlalchemy.sql.selectable import FromClause


class PortfolioLocationRelations(Protocol):
    def properties(self) -> FromClause:
        """Columns: property_id, property_name, property_state, time_zone."""
        ...

    def spaces(self) -> FromClause:
        """Columns: space_id, property_id; includes every retained space."""
        ...
