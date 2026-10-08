"""One count and one capped communication selection, without duplicate links."""

from sqlalchemy import and_, exists, or_, select, literal
from app.modules.communications.infrastructure.sqlalchemy_models import (
    CommunicationModel,
    CommunicationLinkModel,
    CommunicationParticipantModel,
)
from app.platform.sql_context_reads import bounded_page


class SQLiteCommunicationSummaryReader:
    def references(self, scope):
        c = CommunicationModel.__table__
        return (
            select(literal("communication").label("entity_type"), c.c.id.label("entity_id"))
            .where(_membership(scope), c.c.status.in_(("recorded", "superseded")))
            .subquery("communication_context_references")
        )

    def page(self, connection, scope, window):
        c = CommunicationModel.__table__
        selection = select(
            c.c.id,
            c.c.subject,
            c.c.channel,
            c.c.direction,
            c.c.status,
            c.c.occurred_at_utc,
            c.c.occurred_timezone,
            c.c.occurred_at_utc.label("sort_key"),
        ).where(_membership(scope), c.c.status.in_(("recorded", "superseded")))
        return bounded_page(connection, selection, window, descending=True)


def _membership(scope):
    c, link = CommunicationModel.__table__, CommunicationLinkModel.__table__
    refs = scope.references.c
    linked = exists(
        select(1)
        .select_from(
            link.join(
                scope.references,
                and_(link.c.entity_type == refs.entity_type, link.c.entity_id == refs.entity_id),
            )
        )
        .where(link.c.communication_id == c.c.id)
    )
    if scope.party_id:
        participant = CommunicationParticipantModel.__table__
        linked = or_(
            linked,
            exists(
                select(1).where(
                    participant.c.communication_id == c.c.id,
                    participant.c.party_id == scope.party_id,
                )
            ),
        )
    return linked
