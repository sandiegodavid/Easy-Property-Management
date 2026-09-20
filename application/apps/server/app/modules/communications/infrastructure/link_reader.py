"""Generic communication-link summaries for caller-owned transactions."""

from collections import defaultdict
from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import func, select

from .sqlalchemy_models import CommunicationLinkModel, CommunicationModel


class SQLiteCommunicationLinkReader:
    def summaries_for_entities(self, connection: Any, entity_type: str, entity_ids: Collection[str], limit_per_entity: int = 10) -> Mapping[str, list[Mapping[str, object]]]:
        entity_ids = set(entity_ids)
        if not entity_ids or limit_per_entity <= 0:
            return {}
        ranked = (
            select(
                CommunicationLinkModel.entity_id.label("entity_id"),
                CommunicationModel.id.label("id"),
                CommunicationModel.subject.label("subject"),
                CommunicationModel.channel.label("channel"),
                CommunicationModel.direction.label("direction"),
                CommunicationModel.status.label("status"),
                CommunicationModel.occurred_at_utc.label("occurred_at_utc"),
                CommunicationModel.occurred_timezone.label("occurred_timezone"),
                func.row_number().over(
                    partition_by=CommunicationLinkModel.entity_id,
                    order_by=(CommunicationModel.occurred_at_utc.desc(), CommunicationModel.id.desc()),
                ).label("rank"),
            ).join(CommunicationModel, CommunicationModel.id == CommunicationLinkModel.communication_id)
            .where(CommunicationLinkModel.entity_type == entity_type, CommunicationLinkModel.entity_id.in_(entity_ids))
            .subquery()
        )
        rows = connection.execute(
            select(
                ranked.c.entity_id, ranked.c.id, ranked.c.subject, ranked.c.channel,
                ranked.c.direction, ranked.c.status, ranked.c.occurred_at_utc,
                ranked.c.occurred_timezone,
            ).where(ranked.c.rank <= limit_per_entity).order_by(
                ranked.c.entity_id, ranked.c.occurred_at_utc.desc(), ranked.c.id.desc(),
            )
        ).mappings()
        result: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for row in rows:
            result[row["entity_id"]].append(row)
        return result
