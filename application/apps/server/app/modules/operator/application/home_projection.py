"""Source metadata maps once to the registered Home presentation contract."""

from uuid import UUID

from app.modules.operator.application.home_contracts import (
    SourceTarget,
    HomeItem,
    HomeAction,
    Provenance,
    AttentionReason,
    TemporalFact,
    ChildPreview,
    GroupLink,
    CoverageSource,
    TaskSource,
    RentSource,
    IssueSource,
    ReportSource,
    ConcernSource,
    LeaseSource,
    AppointmentSource,
    RelatedSourceContext,
)
from app.modules.operator.application.home_registry import SOURCE_REGISTRY, canonical_key
from app.modules.operator.application.home_vocabulary import SourceKind

SOURCES = {
    SourceKind.TASK: TaskSource,
    SourceKind.RENT: RentSource,
    SourceKind.ISSUE: IssueSource,
    SourceKind.REPORT: ReportSource,
    SourceKind.CONCERN: ConcernSource,
    SourceKind.LEASE: LeaseSource,
    SourceKind.APPOINTMENT: AppointmentSource,
}


def source_reference(kind, identity):
    return SOURCES[SourceKind(kind)](kind=kind, id=identity)


def temporal(value):
    return TemporalFact(at=value.at, on=value.on, time_zone=value.time_zone) if value else None


def _reason(reason, source=None):
    return AttentionReason(
        code=reason.code,
        priority=reason.priority,
        source=source or source_reference(reason.source_kind, reason.source_id),
        at=reason.date.at if reason.date else None,
        on=reason.date.on if reason.date else None,
        time_zone=reason.date.time_zone if reason.date else None,
    )


def _child_preview(child):
    relation = child.relation
    target = source_reference(
        relation.parent_kind if relation.child_kind == "reminder" else "task",
        relation.parent_id if relation.child_kind == "reminder" else relation.child_id,
    )
    return ChildPreview(
        id=relation.child_id,
        kind=relation.child_kind,
        target=SourceTarget(source=target),
        source_revision=child.revision,
        source_status=child.status,
        reasons=tuple(_reason(reason) for reason in child.reasons),
        children=tuple(_child_preview(item) for item in child.children),
        child_count=child.child_count,
    )


def home_item(fact, collection):
    kind = SourceKind(fact.key.source_kind)
    source = (
        CoverageSource(
            kind=kind,
            id=fact.coverage_resolution.subject_id,
            subject_kind=fact.subject_kind,
            area=fact.coverage_area,
        )
        if kind == SourceKind.COVERAGE
        else source_reference(kind, UUID(fact.key.source_id))
    )
    target = SourceTarget(source=source)
    definition = SOURCE_REGISTRY[kind]
    links, children = [], []
    for child in fact.children:
        relation = child.relation
        parent = source_reference(relation.parent_kind, relation.parent_id)
        links.append(GroupLink(relation=relation.kind, child_id=relation.child_id, parent=parent))
        children.append(_child_preview(child))
    reasons = tuple(
        _reason(
            reason, source if reason.source_kind == kind and reason.source_id == source.id else None
        )
        for reason in fact.reasons
    )
    return HomeItem(
        key=canonical_key(source),
        source=source,
        source_revision=fact.source_revision,
        source_status=fact.status,
        title=fact.title,
        collection=collection,
        property_id=fact.property_id,
        space_id=fact.space_id,
        property_name=fact.property_name,
        space_name=fact.space_name,
        related_source=RelatedSourceContext(
            source=source_reference(fact.related_source.kind, fact.related_source.id),
            active=fact.related_source.active,
        )
        if fact.related_source
        else None,
        property_archived=fact.property_archived,
        reasons=reasons,
        task_deadline=temporal(fact.task_deadline),
        follow_up=temporal(fact.follow_up),
        source_deadline=temporal(fact.source_deadline),
        group_links=tuple(links),
        children=tuple(children),
        child_count=fact.child_count,
        child_detail_target=target if fact.child_count else None,
        next_action=HomeAction(kind=definition.action, target=target),
        provenance=Provenance(
            owner=definition.owner,
            source_revision=fact.source_revision,
            recorded_at=fact.recorded_at,
        ),
        outstanding_minor=fact.outstanding_minor,
        currency=fact.currency,
    )
