"""Property-local calendar boundaries derived from one caller UTC instant."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.portfolio.application.attention_ports import PortfolioAttentionError


def attention_instant(as_of: datetime) -> datetime:
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise PortfolioAttentionError("Portfolio attention requires an aware UTC instant.")
    if as_of.utcoffset() != timedelta(0):
        raise PortfolioAttentionError("Portfolio attention requires UTC.")
    return as_of.astimezone(UTC)


def calendar_boundaries(time_zone: str, as_of: datetime, horizon_days: int):
    if type(horizon_days) is not int or horizon_days not in (7, 30, 90):
        raise PortfolioAttentionError("Portfolio attention horizon must be 7, 30 or 90 days.")
    instant = attention_instant(as_of)
    zone = ZoneInfo(time_zone)
    local_date = instant.astimezone(zone).date()
    boundaries = tuple(
        datetime.combine(local_date + timedelta(days=offset), time.min, zone).astimezone(UTC)
        for offset in (0, 1, horizon_days + 1)
    )
    return local_date, *boundaries


def local_day(time_zone: str, captured: str) -> str:
    return datetime.fromisoformat(captured).astimezone(ZoneInfo(time_zone)).date().isoformat()


def next_midnight(time_zone: str, captured: str) -> str:
    return calendar_boundaries(time_zone, datetime.fromisoformat(captured), 7)[2].isoformat()
