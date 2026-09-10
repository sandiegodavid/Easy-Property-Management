"""Portfolio-owned context projection for FIN-001 composition."""
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel

class SQLitePortfolioFinanceOperations:
    def context_for_space(self, connection, space_id):
        space = connection.execute(SpaceModel.__table__.select().where(SpaceModel.id == space_id)).mappings().first()
        if not space: return None
        property_record = connection.execute(PropertyModel.__table__.select().where(PropertyModel.id == space["property_id"])).mappings().first()
        if not property_record: return None
        return {"property_id": property_record["id"], "space_id": space["id"], "time_zone": property_record["time_zone"]}
    def contexts_for_spaces(self, connection, space_ids):
        if not space_ids:
            return {}
        statement = SpaceModel.__table__.select().join(
            PropertyModel.__table__, SpaceModel.property_id == PropertyModel.id,
        ).with_only_columns(
            SpaceModel.id.label("space_id"),
            PropertyModel.id.label("property_id"),
            PropertyModel.time_zone,
        ).where(SpaceModel.id.in_(space_ids))
        return {
            row["space_id"]: {
                "property_id": row["property_id"],
                "space_id": row["space_id"],
                "time_zone": row["time_zone"],
            }
            for row in connection.execute(statement).mappings()
        }
