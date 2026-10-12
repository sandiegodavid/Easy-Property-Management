"""Communication-owned links project their retained source locations set-wise."""

from sqlalchemy import select, literal, and_

from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationLinkModel
from app.modules.tasks.application.attention_ports import TaskAttentionRelations


class SQLiteCommunicationTaskLocations:
    def __init__(self, references: TaskAttentionRelations):
        self.references = references

    def task_locations(self):
        references = self.references.locations(None)
        links = CommunicationLinkModel.__table__
        return (
            select(
                literal("communication").label("entity_type"),
                links.c.communication_id.label("entity_id"),
                references.c.property_id,
                references.c.space_id,
                references.c.property_archived,
                literal(None).label("group_kind"),
                literal(False).label("parent_active"),
            )
            .select_from(
                links.join(
                    references,
                    and_(
                        links.c.entity_type == references.c.entity_type,
                        links.c.entity_id == references.c.entity_id,
                    ),
                )
            )
            .distinct()
            .subquery("communication_task_locations")
        )
