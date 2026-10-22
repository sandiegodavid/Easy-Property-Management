"""Task-owned DASH timing policy, shared by SQL selection and fact hydration."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.tasks.domain.models import due_bucket


def deadline_bucket(due, zone, all_day, captured):
    return due_bucket(
        status="open",
        due_at_utc=due,
        due_timezone=zone,
        is_all_day=bool(all_day),
        now=datetime.fromisoformat(captured),
    )


def deadline_boundary(due, zone, all_day):
    if due is None:
        return None
    instant = datetime.fromisoformat(due).astimezone(UTC)
    if all_day:
        instant = datetime.combine(
            instant.astimezone(ZoneInfo(zone)).date(), time.min, ZoneInfo(zone)
        ).astimezone(UTC)
    return instant.isoformat()


def in_horizon(due, zone, captured, horizon):
    if due is None or zone is None:
        return False
    timezone = ZoneInfo(zone)
    day = datetime.fromisoformat(due).astimezone(timezone).date()
    today = datetime.fromisoformat(captured).astimezone(timezone).date()
    return today < day <= today + timedelta(days=horizon)


def at_or_before(value, captured):
    return value is not None and datetime.fromisoformat(value) <= datetime.fromisoformat(captured)


def next_transition(due, zone, all_day, follow_up, reminder, captured):
    now = datetime.fromisoformat(captured)
    candidates = []
    if due is not None:
        timezone = ZoneInfo(zone)
        tomorrow = now.astimezone(timezone).date() + timedelta(days=1)
        candidates.append(datetime.combine(tomorrow, time.min, timezone).astimezone(UTC))
        boundary = datetime.fromisoformat(deadline_boundary(due, zone, all_day))
        if not all_day:
            boundary += timedelta(microseconds=1)
        if boundary > now:
            candidates.append(boundary)
    for value in (follow_up, reminder):
        if value is not None and datetime.fromisoformat(value) > now:
            candidates.append(datetime.fromisoformat(value).astimezone(UTC))
    return min(candidates).isoformat() if candidates else None
