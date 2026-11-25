"""Timezone bounds and short-window event grouping helpers for HistoryService."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, tzinfo

from work_memory.core.models import ObservedEvent, ObservedGroup

_DEFAULT_GROUP_WINDOW_SECONDS = 300
_DEFAULT_MAX_SPAN_SECONDS = 900


def resolve_local_tz(tz: tzinfo | None = None) -> tzinfo:
    """Return ``tz`` if provided, otherwise the active system local timezone."""
    return tz if tz is not None else (datetime.now().astimezone().tzinfo or UTC)


def parse_utc_to_local(iso_utc: str, tz: tzinfo | None = None) -> datetime:
    """Parse an ISO-8601 UTC timestamp string into an aware local ``datetime``."""
    zone = resolve_local_tz(tz)
    normalized = f"{iso_utc[:-1]}+00:00" if iso_utc.endswith("Z") else iso_utc
    dt = datetime.fromisoformat(normalized)
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).astimezone(zone)


def local_day_utc_bounds(local_date: date, tz: tzinfo | None = None) -> tuple[str, str]:
    """Convert a local calendar date into half-open UTC ISO-8601 bounds ``[start, end)``."""
    zone = resolve_local_tz(tz)
    start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=zone)
    next_day = local_date + timedelta(days=1)
    end_local = datetime(next_day.year, next_day.month, next_day.day, tzinfo=zone)
    return (
        start_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def local_month_utc_bounds(year: int, month: int, tz: tzinfo | None = None) -> tuple[str, str]:
    """Convert a local ``(year, month)`` into half-open UTC ISO-8601 bounds ``[start, end)``."""
    zone = resolve_local_tz(tz)
    start_local = datetime(year, month, 1, tzinfo=zone)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end_local = datetime(next_year, next_month, 1, tzinfo=zone)
    return (
        start_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def group_observed_events(
    events: Sequence[ObservedEvent],
    project_names: dict[str, str],
    workspace_names: dict[str, str] | None = None,
    *,
    tz: tzinfo | None = None,
    window_seconds: int = _DEFAULT_GROUP_WINDOW_SECONDS,
    max_span_seconds: int = _DEFAULT_MAX_SPAN_SECONDS,
) -> tuple[ObservedGroup, ...]:
    """Group related observed events by project and short time window, newest-first."""
    if not events:
        return ()
    zone = resolve_local_tz(tz)
    ws_map = workspace_names or {}
    sorted_events = sorted(events, key=lambda e: (e.occurred_at_utc, e.id), reverse=True)

    open_buckets: dict[tuple[str, date], list[tuple[ObservedEvent, datetime]]] = {}
    finished: list[list[tuple[ObservedEvent, datetime]]] = []

    for ev in sorted_events:
        local_dt = parse_utc_to_local(ev.occurred_at_utc, zone)
        key = (ev.project_id or f"ws:{ev.workspace_id}", local_dt.date())
        bucket = open_buckets.get(key)
        if bucket is None:
            open_buckets[key] = [(ev, local_dt)]
            continue
        if (bucket[-1][1] - local_dt).total_seconds() <= window_seconds and (
            bucket[0][1] - local_dt
        ).total_seconds() <= max_span_seconds:
            bucket.append((ev, local_dt))
        else:
            finished.append(bucket)
            open_buckets[key] = [(ev, local_dt)]

    finished.extend(open_buckets.values())
    finished.sort(key=lambda b: (b[0][1], b[0][0].id), reverse=True)

    groups: list[ObservedGroup] = []
    for bucket in finished:
        head_ev, head_dt = bucket[0]
        label = (
            project_names.get(head_ev.project_id, "Project")
            if head_ev.project_id
            else ws_map.get(head_ev.workspace_id, "Workspace")
        )
        groups.append(
            ObservedGroup(
                project_id=head_ev.project_id,
                project_name=label,
                occurred_at_utc=head_ev.occurred_at_utc,
                local_date_label=head_dt.strftime("%Y-%m-%d"),
                local_time_label=head_dt.strftime("%H:%M"),
                events=tuple(ev for ev, _dt in bucket),
            )
        )
    return tuple(groups)
