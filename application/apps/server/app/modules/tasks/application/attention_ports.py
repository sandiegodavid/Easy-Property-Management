"""Source-owned DASH-001 attention projection contract."""

from typing import Protocol
from uuid import UUID
from sqlalchemy.sql.selectable import FromClause

from app.platform.attention_reads import AttentionReader, AttentionWindow, AttentionPage
from app.platform.attention_reads import AttentionFact


class TaskAttentionReader(AttentionReader, Protocol):
    """Filter and group source facts before bounded candidate selection."""

    def standalone_attention(
        self, connection: object, window: AttentionWindow, grouped_tasks: FromClause
    ) -> AttentionPage:
        """Exclude explicitly grouped active children before counts and LIMIT."""
        ...

    def facts(self, connection: object, window: AttentionWindow) -> FromClause:
        """SQL-filterable active Task facts for grouping before merged pagination.

        Includes declared parent relations, source timing/ordering, collection,
        exact due-reminder count and next transition. Contains no Task notes or
        outcome text. Source owns classification and SQL; composition may group
        on relation identity without importing Task persistence models.
        """
        ...

    def hydrate(
        self, connection: object, identities: tuple[UUID, ...], window: AttentionWindow
    ) -> tuple[AttentionFact, ...]:
        """Bounded selected follow-up facts (at most 303), with reminder previews."""
        ...


class TaskAttentionRelations(Protocol):
    def locations(self, property_id: UUID | None) -> FromClause:
        """Source-owned SQL relation for Task-related identities.

        Columns: entity_type, entity_id, property_id, space_id, property_archived,
        group_kind (issue_follow_up/concern_follow_up or NULL), parent_active.
        Include retained archived locations; a property filter selects only that
        property's relations. Multiple contextual locations must not duplicate
        Tasks. Generic property/lease context never establishes grouping.
        """
        ...


class TaskAttentionLocationSource(Protocol):
    def task_locations(self) -> FromClause:
        """Retained source identity/location/lifecycle for Task context."""
        ...
