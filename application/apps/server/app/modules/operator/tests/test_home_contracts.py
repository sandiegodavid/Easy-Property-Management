"""Executable Slice 1 examples and fail-closed contract boundaries."""

from datetime import UTC, datetime
from uuid import UUID
from pathlib import Path
import json
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.operator.application.home_contracts import (
    AttentionResponse,
    AvailableCollection,
    Capture,
    Collection,
    CollectionResult,
    CollectionQuery,
    HomeItem,
    HomeQuery,
    HomeScope,
    SourceKind,
    HomeResponse,
    CollectionResponse,
    AttentionQuery,
    SourceReference,
    TemporalFact,
)
from app.modules.operator.application.home_registry import (
    COLLECTION_DEPENDENCIES,
    SOURCE_REGISTRY,
    home_ready,
)
from app.modules.operator.application.home_ports import HomeSources
from app.platform.attention_reads import (
    AttentionWindow,
    AttentionPage,
    AttentionKey,
    AttentionFact,
    AttentionReasonFact,
)

IDENTITY = "00000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
REASONS = (
    "undated",
    "due_today",
    "urgent",
    "pending_verification",
    "unresolved",
    "lease_review",
    "outcome_review",
    "missing_required",
)


def example(kind):
    definition = SOURCE_REGISTRY[kind]
    source = {"kind": kind, "id": IDENTITY}
    if kind == SourceKind.COVERAGE:
        source.update(subjectKind="property", area="occupancy")
    key = f"{kind}:{IDENTITY}" + (":property:occupancy" if kind == SourceKind.COVERAGE else "")
    priority = {
        SourceKind.RENT: "today",
        SourceKind.ISSUE: "urgent",
        SourceKind.COVERAGE: "information",
    }.get(kind, "review")
    payload = {
        "key": key,
        "source": source,
        "sourceRevision": "1",
        "sourceStatus": "active",
        "title": "Recorded source",
        "collection": "information_review" if kind == SourceKind.COVERAGE else "needs_action",
        "reasons": [
            {"code": REASONS[list(SourceKind).index(kind)], "priority": priority, "source": source}
        ],
        "nextAction": {"kind": definition.action, "target": {"kind": "source", "source": source}},
        "provenance": {"owner": definition.owner, "sourceRevision": "1"},
    }
    if kind == SourceKind.RENT:
        payload.update(outstandingMinor=12345, currency="USD")
    return payload


@pytest.mark.parametrize("kind", list(SourceKind))
def test_every_initial_source_has_a_valid_metadata_example(kind):
    item = HomeItem.model_validate(example(kind))
    assert HomeItem.model_validate_json(item.model_dump_json(by_alias=True)) == item
    assert "body" not in item.model_dump()


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "nextAction",
            {"kind": "record_payment", "target": {"source": {"kind": "task", "id": IDENTITY}}},
        ),
        ("collection", "information_review"),
        ("key", "untrusted"),
        ("body", "sensitive evidence"),
        ("childCount", -1),
        ("outstandingMinor", 42),
    ],
)
def test_invalid_source_action_target_and_evidence_fail(field, value):
    payload = example(SourceKind.TASK)
    payload[field] = value
    with pytest.raises(ValidationError):
        HomeItem.model_validate(payload)


def capture():
    return Capture(
        as_of=NOW, source_revision="1", read_mode="live", freshness="checked", checked_at=NOW
    )


def test_unavailable_is_discriminated_and_has_no_fabricated_empty_result():
    payload = {
        "status": "unavailable",
        "collection": "needs_action",
        "capture": Capture(
            as_of=NOW, source_revision="1", read_mode="live", freshness="unavailable"
        ),
        "reasonCode": "adapter_missing",
        "retryTarget": {"collection": "needs_action", "scope": {}},
    }
    adapter = TypeAdapter(CollectionResult)
    assert adapter.validate_python(payload).status == "unavailable"
    for field, value in (("matchingTotal", 0), ("items", [])):
        with pytest.raises(ValidationError):
            adapter.validate_python({**payload, field: value})


def test_live_attention_requires_complete_sources_and_exact_counts():
    section = AvailableCollection(
        collection="needs_action",
        capture=capture(),
        matching_total=0,
        items=(),
        view_all_target={"collection": "needs_action", "scope": {}},
    )
    payload = dict(
        workspace_id=IDENTITY,
        runtime_epoch=IDENTITY,
        scope={},
        as_of=NOW,
        source_revision="1",
        supported_sources=tuple(set(SourceKind) - {SourceKind.COVERAGE}),
        needs_action=section,
        priority_totals={},
        reason_totals={},
    )
    assert AttentionResponse(**payload).needs_action.matching_total == 0
    with pytest.raises(ValidationError):
        AttentionResponse(**{**payload, "supported_sources": (SourceKind.TASK,)})
    with pytest.raises(ValidationError):
        AttentionResponse(**{**payload, "priority_totals": {"urgent": 1}})


def test_request_normalization_bounds_and_utc():
    assert HomeScope(kind="property", property_id=IDENTITY).property_id == UUID(IDENTITY)
    assert HomeQuery(from_on="2026-10-01", through_on="2026-10-31").limit_per_section == 5
    with pytest.raises(ValidationError):
        HomeScope(property_id=IDENTITY)
    with pytest.raises(ValidationError):
        CollectionQuery(collection="waiting", limit=101)
    with pytest.raises(ValidationError):
        HomeQuery(from_on="2026-10-31", through_on="2026-10-01")
    with pytest.raises(ValueError):
        AttentionWindow(NOW, "needs_action", limit=True)
    with pytest.raises(ValidationError):
        Capture(
            as_of=NOW.replace(tzinfo=None), source_revision="1", read_mode="live", freshness="stale"
        )


def test_source_registry_dependencies_and_readiness_fail_closed():
    assert not home_ready({})
    assert not home_ready(dict.fromkeys(SourceKind))

    class Adapter:
        def attention(self, connection, window):
            return AttentionPage(0, ())

    assert not home_ready({kind: object() for kind in SourceKind})
    assert home_ready({kind: Adapter() for kind in SourceKind})
    assert COLLECTION_DEPENDENCIES[Collection.APPOINTMENTS] == {SourceKind.APPOINTMENT}
    assert COLLECTION_DEPENDENCIES[Collection.INFORMATION_REVIEW] == {SourceKind.COVERAGE}
    assert COLLECTION_DEPENDENCIES[Collection.NEEDS_ACTION] == set(SourceKind) - {
        SourceKind.COVERAGE
    }


def test_source_page_contract_rejects_unbounded_and_unordered_candidates():
    window = AttentionWindow(NOW, "needs_action", limit=1)
    key = AttentionKey(0, NOW, "task", IDENTITY)
    fact = AttentionFact(
        key,
        "1",
        "active",
        "Recorded task",
        (AttentionReasonFact("undated", "review", "task", UUID(IDENTITY)),),
    )
    AttentionPage(1, (fact,)).validate_window(window)
    for page in (
        AttentionPage(-1, ()),
        AttentionPage(3, (fact, fact, fact)),
        AttentionPage(2, (fact, fact)),
    ):
        with pytest.raises(ValueError):
            page.validate_window(window)
    with pytest.raises(ValueError):
        AttentionPage(1, (fact,)).validate_window(AttentionWindow(NOW, "needs_action", after=key))


def fixtures():
    return json.loads((Path(__file__).parent / "fixtures" / "home_contracts.json").read_text())


def test_complete_documented_requests_and_responses_round_trip():
    examples = fixtures()
    for name, model in (
        ("home", HomeQuery),
        ("attention", AttentionQuery),
        ("collection", CollectionQuery),
    ):
        model.model_validate(examples["requests"][name])
    for name, model in (
        ("home", HomeResponse),
        ("attention", AttentionResponse),
        ("collection", CollectionResponse),
    ):
        result = model.model_validate(examples[name])
        assert model.model_validate_json(result.model_dump_json(by_alias=True)) == result
    for failure in examples["failures"]:
        assert AttentionResponse.model_validate(failure).needs_action.status == "unavailable"


def test_source_schema_is_discriminated_and_coverage_uses_registered_areas():
    schema = HomeItem.model_json_schema()
    assert schema["properties"]["source"]["discriminator"]["propertyName"] == "kind"
    adapter = TypeAdapter(SourceReference)
    for value in (
        {"kind": "task", "id": IDENTITY, "area": "occupancy"},
        {"kind": "coverage", "id": IDENTITY, "subjectKind": "property", "area": "invented"},
        {"kind": "invented", "id": IDENTITY},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


@pytest.mark.parametrize("collection", ["waiting", "upcoming"])
def test_actionable_reasons_cannot_be_hidden_by_waiting_or_upcoming(collection):
    item = example(SourceKind.ISSUE)
    item["collection"] = collection
    with pytest.raises(ValidationError):
        HomeItem.model_validate(item)


def test_grouped_task_and_reminder_keep_explicit_ownership():
    item = example(SourceKind.ISSUE)
    task_id = "00000000-0000-4000-8000-000000000002"
    reminder_id = "00000000-0000-4000-8000-000000000003"
    task = {"kind": "task", "id": task_id}
    item.update(
        childCount=2,
        childDetailTarget={"source": item["source"]},
        children=[
            {"kind": "task", "id": task_id, "target": {"source": task}},
            {"kind": "reminder", "id": reminder_id, "target": {"source": task}},
        ],
        groupLinks=[
            {"relation": "issue_follow_up", "childId": task_id, "parent": item["source"]},
            {"relation": "task_reminder", "childId": reminder_id, "parent": task},
        ],
    )
    item["reasons"].append({"code": "reminder_due", "priority": "today", "source": task})
    assert HomeItem.model_validate(item).child_count == 2
    broken = deepcopy(item)
    broken["children"][1]["target"]["source"] = item["source"]
    with pytest.raises(ValidationError):
        HomeItem.model_validate(broken)


def test_capture_temporal_and_unavailable_contracts_fail_closed():
    for changes in ({"next_transition_at": NOW}, {"read_mode": "snapshot"}, {"checked_at": None}):
        with pytest.raises(ValidationError):
            Capture.model_validate({**capture().model_dump(), **changes})
    for temporal in (
        {"on": "2026-10-12", "time_zone": "invented"},
        {"on": "2026-10-12", "at": NOW, "time_zone": "UTC"},
    ):
        with pytest.raises(ValidationError):
            TemporalFact.model_validate(temporal)
    result = fixtures()["failures"][0]
    result["needsAction"]["capture"]["freshness"] = "checked"
    with pytest.raises(ValidationError):
        AttentionResponse.model_validate(result)


def test_home_scope_money_format_and_inventory_targets_agree():
    payload = fixtures()["home"]
    payload["scope"] = {"kind": "property", "propertyId": IDENTITY}
    with pytest.raises(ValidationError):
        HomeResponse.model_validate(payload)
    payload = fixtures()["home"]
    payload["inventory"]["vacant"]["target"]["occupancy"] = "unknown"
    with pytest.raises(ValidationError):
        HomeResponse.model_validate(payload)
    payload = fixtures()["home"]
    payload["money"]["metrics"][0]["amount"] = "9.99"
    with pytest.raises(ValidationError):
        HomeResponse.model_validate(payload)


def test_readiness_requires_scope_inventory_and_money_in_addition_to_attention():
    class Reader:
        def attention(self, connection, window):
            return AttentionPage(0, ())

        def validate_scope(self, connection, property_id):
            pass

        def calendars(self, connection, property_ids, as_of, horizon_days):
            return ()

        def inventory(self, connection, property_id, as_of):
            return None

        def inventory_spaces(self, connection, property_id, as_of, occupancy, **window):
            return None

        def summary(self, connection, query, **context):
            return None

        def facts(self, connection, window):
            return None

        def standalone_attention(self, connection, window, grouped_tasks):
            return None

        def hydrate(self, connection, identities, window):
            return ()

        def follow_up_relations(self):
            return None

        def attention_labels(self, connection, properties, spaces):
            return None

    reader = Reader()
    sources = HomeSources(reader, reader, reader, reader, reader, reader, reader, reader, reader)
    assert sources.ready
    assert not HomeSources(
        reader, reader, reader, reader, reader, reader, reader, None, reader
    ).ready
    assert not HomeSources(
        reader, reader, reader, reader, reader, reader, reader, reader, None
    ).ready


@pytest.mark.parametrize(
    "field,value",
    [
        ("asOf", "2026-10-12T13:00:00Z"),
        ("sourceRevision", "changed"),
        ("reasonTotals", {"invented": 1}),
        ("reasonTotals", {"undated": 999}),
        ("supportedSources", ["task", "task"]),
    ],
)
def test_live_attention_rejects_mismatched_envelope_and_breakdowns(field, value):
    payload = fixtures()["attention"]
    payload[field] = value
    with pytest.raises(ValidationError):
        AttentionResponse.model_validate(payload)


def test_missing_dependencies_cannot_produce_available_home_and_collection():
    for name, model in (("home", HomeResponse), ("collection", CollectionResponse)):
        payload = fixtures()[name]
        payload["supportedSources"] = ["task"]
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_bounded_children_dates_and_exact_request_numbers():
    item = example(SourceKind.TASK)
    item["children"] = [
        {"kind": "reminder", "id": IDENTITY, "target": {"source": item["source"]}}
    ] * 4
    with pytest.raises(ValidationError):
        HomeItem.model_validate(item)
    with pytest.raises(ValidationError):
        CollectionQuery(collection="waiting", horizonDays=7.0)
    valid = TemporalFact(on="2026-10-12", time_zone="America/Los_Angeles")
    assert valid.on.isoformat() == "2026-10-12"
