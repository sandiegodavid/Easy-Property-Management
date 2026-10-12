"""Declared DASH sources, grouping rules and collection failure dependencies."""

from dataclasses import dataclass
from types import MappingProxyType

from app.modules.operator.application.home_vocabulary import Collection, SourceKind


@dataclass(frozen=True)
class SourceDefinition:
    owner: str
    action: str
    collections: frozenset[Collection]
    reasons: frozenset[str]


def _definition(owner, action, collections, reasons):
    return SourceDefinition(owner, action, frozenset(collections), frozenset(reasons))


PRIMARY = (Collection.NEEDS_ACTION, Collection.WAITING, Collection.UPCOMING)
SOURCE_REGISTRY = MappingProxyType(
    {
        SourceKind.TASK: _definition(
            "tasks",
            "review_task",
            PRIMARY,
            (
                "overdue",
                "due_today",
                "follow_up_due",
                "reminder_due",
                "undated",
                "waiting",
                "follow_up_unscheduled",
                "scheduled",
            ),
        ),
        SourceKind.RENT: _definition(
            "finance",
            "record_payment",
            (Collection.NEEDS_ACTION, Collection.UPCOMING),
            ("overdue", "due_today", "scheduled"),
        ),
        SourceKind.ISSUE: _definition(
            "maintenance",
            "review_issue",
            PRIMARY,
            (
                "emergency",
                "urgent",
                "unresolved",
                "waiting",
                "overdue",
                "due_today",
                "follow_up_due",
                "reminder_due",
                "undated",
                "follow_up_unscheduled",
                "scheduled",
            ),
        ),
        SourceKind.REPORT: _definition(
            "owner_accounting",
            "review_report",
            (Collection.NEEDS_ACTION,),
            ("pending_verification",),
        ),
        SourceKind.CONCERN: _definition(
            "owner_management",
            "review_concern",
            PRIMARY,
            (
                "unresolved",
                "waiting",
                "overdue",
                "due_today",
                "follow_up_due",
                "reminder_due",
                "undated",
                "follow_up_unscheduled",
                "scheduled",
            ),
        ),
        SourceKind.LEASE: _definition(
            "leases",
            "review_lease",
            (Collection.NEEDS_ACTION, Collection.UPCOMING),
            ("lease_review", "continued_occupancy"),
        ),
        SourceKind.APPOINTMENT: _definition(
            "maintenance",
            "review_appointment",
            (Collection.NEEDS_ACTION, Collection.UPCOMING, Collection.APPOINTMENTS),
            ("outcome_review", "scheduled"),
        ),
        SourceKind.COVERAGE: _definition(
            "operator",
            "review_coverage",
            (Collection.INFORMATION_REVIEW,),
            ("missing_required", "needs_review"),
        ),
    }
)
COLLECTION_DEPENDENCIES = MappingProxyType(
    {
        collection: frozenset(
            kind
            for kind, definition in SOURCE_REGISTRY.items()
            if collection in definition.collections
        )
        for collection in Collection
    }
)
SECTION_DEPENDENCIES = MappingProxyType(
    {
        **{
            collection.value: frozenset(SOURCE_REGISTRY[source].owner for source in sources)
            for collection, sources in COLLECTION_DEPENDENCIES.items()
        },
        "inventory": frozenset({"portfolio"}),
        "money": frozenset({"finance"}),
    }
)
GROUP_PARENTS = MappingProxyType(
    {
        "issue_follow_up": SourceKind.ISSUE,
        "concern_follow_up": SourceKind.CONCERN,
        "task_reminder": SourceKind.TASK,
    }
)
REASON_PRIORITIES = MappingProxyType(
    {
        "emergency": {"urgent"},
        "urgent": {"urgent"},
        "overdue": {"overdue"},
        "due_today": {"today"},
        "follow_up_due": {"today"},
        "reminder_due": {"today", "overdue"},
        "undated": {"review"},
        "unresolved": {"review"},
        "pending_verification": {"review"},
        "lease_review": {"review", "future"},
        "continued_occupancy": {"review"},
        "outcome_review": {"review"},
        "waiting": {"waiting"},
        "follow_up_unscheduled": {"waiting"},
        "scheduled": {"future", "waiting"},
        "missing_required": {"information"},
        "needs_review": {"information"},
    }
)
COLLECTION_PRIORITIES = MappingProxyType(
    {
        Collection.NEEDS_ACTION: {"urgent", "overdue", "today", "review"},
        Collection.WAITING: {"waiting"},
        Collection.UPCOMING: {"future"},
        Collection.APPOINTMENTS: {"future"},
        Collection.INFORMATION_REVIEW: {"information"},
    }
)


def canonical_key(source):
    suffix = f":{source.subject_kind}:{source.area}" if source.kind == SourceKind.COVERAGE else ""
    return f"{source.kind}:{source.id}{suffix}"


def validate_item(item):
    definition = SOURCE_REGISTRY[item.source.kind]
    if (
        item.provenance.owner != definition.owner
        or item.provenance.source_revision != item.source_revision
    ):
        raise ValueError("Provenance must identify the owning source revision.")
    if (
        item.key != canonical_key(item.source)
        or item.collection not in definition.collections
        or item.next_action.kind != definition.action
        or item.next_action.target.source != item.source
    ):
        raise ValueError("Unregistered source, action, collection or target pairing.")
    if any(reason.code not in definition.reasons for reason in item.reasons):
        raise ValueError("Reason is not registered for this source.")
    if any(reason.priority not in REASON_PRIORITIES[reason.code] for reason in item.reasons):
        raise ValueError("Reason has an invalid priority band.")
    if not any(
        reason.priority in COLLECTION_PRIORITIES[item.collection] for reason in item.reasons
    ):
        raise ValueError("Collection requires a qualifying reason.")
    if item.collection != Collection.NEEDS_ACTION and any(
        reason.priority in COLLECTION_PRIORITIES[Collection.NEEDS_ACTION] for reason in item.reasons
    ):
        raise ValueError("Actionable reasons take precedence over Waiting and Upcoming.")
    if item.child_count < len(item.children) or (
        item.child_count and item.child_detail_target is None
    ):
        raise ValueError("Children require exact counts and a bounded detail target.")
    for link in item.group_links:
        nested_reminder = (
            link.relation == "task_reminder"
            and link.parent.kind == SourceKind.TASK
            and any(child.kind == "task" and child.id == link.parent.id for child in item.children)
        )
        if not nested_reminder and (
            link.parent != item.source or GROUP_PARENTS[link.relation] != item.source.kind
        ):
            raise ValueError("Grouping requires a declared owning relation.")
    if len({(link.relation, link.child_id) for link in item.group_links}) != len(item.group_links):
        raise ValueError("Grouping links must be unique.")
    if len({child.id for child in item.children}) != len(item.children):
        raise ValueError("Child previews must be unique.")
    if item.child_detail_target is not None and item.child_detail_target.source != item.source:
        raise ValueError("Child detail target must be the owning source.")
    child_ids = {child.id for child in item.children}
    if any(link.child_id not in child_ids for link in item.group_links):
        raise ValueError("Grouping links must identify previewed children.")
    for reason in item.reasons:
        if reason.source != item.source and (
            reason.source.kind != SourceKind.TASK or reason.source.id not in child_ids
        ):
            raise ValueError("Foreign reasons require an explicit child relation.")
    for child in item.children:
        relation = (
            "task_reminder"
            if child.kind == "reminder"
            else (
                "issue_follow_up" if item.source.kind == SourceKind.ISSUE else "concern_follow_up"
            )
        )
        if not any(
            link.child_id == child.id and link.relation == relation for link in item.group_links
        ):
            raise ValueError("Child previews require explicit grouping links.")
        reminder_link = next(
            (
                link
                for link in item.group_links
                if link.child_id == child.id and link.relation == "task_reminder"
            ),
            None,
        )
        expected_target = (
            reminder_link.parent if child.kind == "reminder" and reminder_link is not None else None
        )
        if (expected_target is not None and child.target.source != expected_target) or (
            child.kind == "task"
            and (child.target.source.kind != SourceKind.TASK or child.target.source.id != child.id)
        ):
            raise ValueError("Child target does not identify its owning action.")
    if item.source.kind == SourceKind.RENT:
        if item.outstanding_minor is None or item.currency is None:
            raise ValueError("Rent attention requires exact outstanding USD cents.")
    elif item.outstanding_minor is not None or item.currency is not None:
        raise ValueError("Only rent attention carries outstanding money.")


def home_ready(adapters):
    """Missing core projections cannot advertise Home capability."""
    return set(adapters) == set(SourceKind) and all(
        callable(getattr(adapter, "attention", None)) for adapter in adapters.values()
    )
