"""Portfolio-approved location labels and related client-owner recognition."""

from sqlalchemy import literal, select, func

from app.modules.portfolio.application.owner_read_ports import (
    OwnerContextReader,
    OwnerDirectoryQuery,
)
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.platform.context_reads import ReadPage
from app.platform.sql_metadata_search import metadata_page


class SQLiteLocationSearchReader:
    def __init__(self, kind: str):
        if kind not in {"property", "space"}:
            raise ValueError("Unsupported Portfolio search type.")
        self.kind = kind

    def search(self, connection, term, window):
        p = PropertyModel.__table__
        address = (
            p.c.address_line_1
            + literal(" ")
            + func.coalesce(p.c.address_line_2, "")
            + literal(" ")
            + p.c.city
            + literal(" ")
            + func.coalesce(p.c.region, "")
            + literal(" ")
            + func.coalesce(p.c.postal_code, "")
        )
        if self.kind == "property":
            selection = select(
                p.c.id,
                p.c.display_name.label("label"),
                address.label("context"),
                (p.c.status == "archived").label("archived"),
                literal("property").label("entity_type"),
            )
        else:
            s = SpaceModel.__table__
            selection = select(
                s.c.id,
                s.c.display_name.label("label"),
                (p.c.display_name + literal(" · ") + address).label("context"),
                ((s.c.status == "archived") | (p.c.status == "archived")).label("archived"),
                literal("space").label("entity_type"),
            ).join(p, s.c.property_id == p.c.id)
        return metadata_page(connection, selection, term, window)


class SQLiteOwnerSearchReader:
    def __init__(self, owners: OwnerContextReader):
        self.owners = owners

    def search(self, connection, term, window):
        page = self.owners.owners(
            connection,
            OwnerDirectoryQuery(
                text=term.text,
                archive_state="all" if term.include_archived else "active",
                relationship_scope="all" if term.include_archived else "current",
                property_state="all" if term.include_archived else "active",
                limit=window.limit,
            ),
            as_of=window.as_of,
            after=window.after,
        )
        return ReadPage(
            page.total,
            [
                {
                    "id": row["id"],
                    "label": row["display_name"],
                    "context": " · ".join(p["display_name"] for p in row["properties"]),
                    "archived": row["archived_at"] is not None,
                    "entity_type": "owner",
                }
                for row in page.items
            ],
            page.next_key,
        )
