"""Portfolio projections used inside FIN-002 transactions."""

from sqlalchemy import and_, or_, select

from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    PropertyOwnershipModel,
    SpaceModel,
)


class SQLitePortfolioExpenseOperations:
    def expense_context(self, connection, property_id, space_id, paid_on):
        property_row = connection.execute(
            PropertyModel.__table__.select().where(PropertyModel.id == property_id)
        ).mappings().first()
        if property_row is None:
            return None
        space_row = None
        if space_id is not None:
            space_row = connection.execute(
                SpaceModel.__table__.select().where(SpaceModel.id == space_id)
            ).mappings().first()
            if space_row is None or space_row["property_id"] != property_id:
                return None
        return {
            "propertyId": property_row["id"],
            "propertyName": property_row["display_name"],
            "propertyArchived": property_row["status"] == "archived",
            "timeZone": property_row["time_zone"],
            "spaceId": None if space_row is None else space_row["id"],
            "spaceName": None if space_row is None else space_row["display_name"],
            "spaceArchived": False if space_row is None else space_row["status"] == "archived",
        }

    def party_owned_property_on(self, connection, property_id, party_id, paid_on):
        return connection.execute(
            select(PropertyOwnershipModel.id).where(
                PropertyOwnershipModel.property_id == property_id,
                PropertyOwnershipModel.owner_kind == "client_owner",
                PropertyOwnershipModel.party_id == party_id,
                PropertyOwnershipModel.starts_on <= paid_on,
                or_(PropertyOwnershipModel.ends_on.is_(None), PropertyOwnershipModel.ends_on > paid_on),
            ).limit(1)
        ).first() is not None

    def expense_contexts(self, connection, expenses):
        if not expenses:
            return {}
        property_ids = {item.property_id for item in expenses}
        space_ids = {item.space_id for item in expenses if item.space_id is not None}
        properties = {
            row["id"]: row
            for row in connection.execute(
                PropertyModel.__table__.select().where(PropertyModel.id.in_(property_ids))
            ).mappings()
        }
        spaces = {
            row["id"]: row
            for row in connection.execute(
                SpaceModel.__table__.select().where(SpaceModel.id.in_(space_ids))
            ).mappings()
        } if space_ids else {}
        result = {}
        for item in expenses:
            property_row = properties.get(item.property_id)
            space_row = spaces.get(item.space_id) if item.space_id is not None else None
            if property_row is None or (
                item.space_id is not None
                and (space_row is None or space_row["property_id"] != item.property_id)
            ):
                continue
            result[item.id] = {
                "propertyId": property_row["id"],
                "propertyName": property_row["display_name"],
                "propertyArchived": property_row["status"] == "archived",
                "timeZone": property_row["time_zone"],
                "spaceId": None if space_row is None else space_row["id"],
                "spaceName": None if space_row is None else space_row["display_name"],
                "spaceArchived": False if space_row is None else space_row["status"] == "archived",
            }
        return result
