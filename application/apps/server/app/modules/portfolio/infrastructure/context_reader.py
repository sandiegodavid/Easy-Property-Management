"""SQLite portfolio context reads for caller-owned transactions."""

from collections.abc import Collection
from typing import Any

from sqlalchemy import or_, select

from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, PropertyOwnershipModel, SpaceModel


class SQLitePortfolioContextReader:
    def context_for_space(self, connection: Any, space_id: str) -> dict[str, object] | None:
        space = connection.execute(SpaceModel.__table__.select().where(SpaceModel.id == space_id)).mappings().first()
        if space is None:
            return None
        property_record = connection.execute(PropertyModel.__table__.select().where(PropertyModel.id == space["property_id"])).mappings().first()
        if property_record is None:
            return None
        return {"property_id": property_record["id"], "space_id": space["id"], "time_zone": property_record["time_zone"]}

    def contexts_for_spaces(self, connection: Any, space_ids: Collection[str]) -> dict[str, dict[str, object]]:
        space_ids = set(space_ids)
        if not space_ids:
            return {}
        statement = SpaceModel.__table__.select().join(
            PropertyModel.__table__, SpaceModel.property_id == PropertyModel.id,
        ).with_only_columns(
            SpaceModel.id.label("space_id"), PropertyModel.id.label("property_id"), PropertyModel.time_zone,
        ).where(SpaceModel.id.in_(space_ids))
        return {row["space_id"]: {"property_id": row["property_id"], "space_id": row["space_id"], "time_zone": row["time_zone"]} for row in connection.execute(statement).mappings()}

    def context_for_property_space(self, connection: Any, property_id: str, space_id: str | None) -> dict[str, object] | None:
        property_row = connection.execute(PropertyModel.__table__.select().where(PropertyModel.id == property_id)).mappings().first()
        if property_row is None:
            return None
        space_row = None
        if space_id is not None:
            space_row = connection.execute(SpaceModel.__table__.select().where(SpaceModel.id == space_id)).mappings().first()
            if space_row is None or space_row["property_id"] != property_id:
                return None
        return _property_space_context(property_row, space_row)

    def contexts_for_property_spaces(self, connection: Any, references: Collection[tuple[str, str | None]]) -> dict[tuple[str, str | None], dict[str, object]]:
        references = set(references)
        if not references:
            return {}
        property_ids = {property_id for property_id, _ in references}
        space_ids = {space_id for _, space_id in references if space_id is not None}
        properties = {row["id"]: row for row in connection.execute(PropertyModel.__table__.select().where(PropertyModel.id.in_(property_ids))).mappings()}
        spaces = {row["id"]: row for row in connection.execute(SpaceModel.__table__.select().where(SpaceModel.id.in_(space_ids))).mappings()} if space_ids else {}
        result = {}
        for property_id, space_id in references:
            property_row = properties.get(property_id)
            space_row = spaces.get(space_id) if space_id is not None else None
            if property_row is None or (space_id is not None and (space_row is None or space_row["property_id"] != property_id)):
                continue
            result[(property_id, space_id)] = _property_space_context(property_row, space_row)
        return result

    def party_owned_property_on(self, connection: Any, property_id: str, party_id: str, on: str) -> bool:
        return connection.execute(select(PropertyOwnershipModel.id).where(
            PropertyOwnershipModel.property_id == property_id, PropertyOwnershipModel.owner_kind == "client_owner",
            PropertyOwnershipModel.party_id == party_id, PropertyOwnershipModel.starts_on <= on,
            or_(PropertyOwnershipModel.ends_on.is_(None), PropertyOwnershipModel.ends_on > on),
        ).limit(1)).first() is not None


def _property_space_context(property_row, space_row) -> dict[str, object]:
    return {
        "property_id": property_row["id"], "property_display_name": property_row["display_name"],
        "property_status": property_row["status"], "time_zone": property_row["time_zone"],
        "space_id": None if space_row is None else space_row["id"],
        "space_display_name": None if space_row is None else space_row["display_name"],
        "space_status": None if space_row is None else space_row["status"],
    }
