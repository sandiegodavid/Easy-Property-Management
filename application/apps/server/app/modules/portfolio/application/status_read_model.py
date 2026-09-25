"""Shared portfolio space-status projection."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.portfolio.domain.models import Property, Space, SpaceAvailability, SpaceOccupancyPeriod


def space_status_snapshot(
    space: Space,
    property: Property,
    periods: list[SpaceOccupancyPeriod],
    availability: SpaceAvailability | None,
    as_of: datetime,
) -> dict[str, object]:
    """Return the same temporal status shape exposed by the space-status read API."""
    effective_on = as_of.astimezone(ZoneInfo(property.time_zone)).date().isoformat()
    return {
        **space_status_view(space, periods, availability, effective_on=effective_on),
        "asOf": as_of.isoformat(),
        "effectiveLocalDate": effective_on,
    }


def space_status_view(
    space: Space,
    periods: list[SpaceOccupancyPeriod],
    availability: SpaceAvailability | None,
    *,
    effective_on: str,
) -> dict[str, object]:
    current = next((item for item in periods if item.record_state == "valid" and item.starts_on <= effective_on and (item.ends_on is None or item.ends_on > effective_on)), None)
    scheduled = sorted(
        (item for item in periods if item.record_state == "valid" and item.starts_on > effective_on),
        key=lambda item: item.starts_on,
    )
    if current is None or availability is None:
        raise RuntimeError("Space status records are missing.")
    availability_view = availability.to_dict()
    availability_view["recordedStatus"] = availability.availability_status
    availability_view["effectiveStatus"] = availability.availability_status
    if availability.availability_status == "available_on" and availability.available_on is not None and availability.available_on <= effective_on:
        availability_view["availabilityStatus"] = "available_now"
        availability_view["effectiveStatus"] = "available_now"
    attention_reasons = []
    if current.occupancy_status == "unknown":
        attention_reasons.append({"code": "occupancy_unknown", "resolution": "classify_occupancy"})
    if availability.availability_status == "unknown":
        attention_reasons.append({"code": "availability_unknown", "resolution": "classify_availability"})
    return {
        **space.to_dict(),
        "currentOccupancy": current.to_dict(),
        "scheduledOccupancy": None if not scheduled else scheduled[0].to_dict(),
        "scheduledOccupancyTimeline": [item.to_dict() for item in scheduled],
        "availability": availability_view,
        "attentionReasons": attention_reasons,
    }
