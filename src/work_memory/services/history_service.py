"""Application service for local-date calendar markers, unified timelines, and search."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, tzinfo
from pathlib import PurePosixPath
from typing import Literal

from work_memory.config.paths import AppPaths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import (
    DayMarkers,
    DayTimeline,
    MilestoneDetail,
    MilestoneItem,
    ObservedEvent,
    SearchResults,
)
from work_memory.services.file_resolver import (
    ResolvedFileResult,
    RevealTargetResult,
    resolve_file_from_repos,
    resolve_reveal_from_repos,
)
from work_memory.services.timeline_grouping import (
    group_observed_events,
    local_day_utc_bounds,
    local_month_utc_bounds,
    parse_utc_to_local,
    resolve_local_tz,
)
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.search_repo import SearchRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository

__all__ = [
    "HistoryService",
    "group_observed_events",
    "local_day_utc_bounds",
    "local_month_utc_bounds",
    "parse_utc_to_local",
    "resolve_local_tz",
]


class HistoryService:
    """Provides calendar markers, daily timelines, file resolution, and search."""

    def __init__(
        self,
        database: Database,
        event_bus: EventBus | None = None,
        *,
        app_paths: AppPaths | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        self._bus = event_bus
        self._app_paths = app_paths
        self._tz = tz
        self._ev_repo = ObservedEventRepository(database)
        self._capture_repo = CaptureRepository(database)
        self._calendar_repo = CalendarRepo(database)
        self._project_repo = ProjectRepository(database)
        self._ws_repo = WorkspaceRepository(database)
        self._search_repo = SearchRepository(database)

    def resolve_file_path(
        self,
        rel_path: str,
        *,
        project_id: str | None = None,
        workspace_id: str | None = None,
        event_id: str | None = None,
    ) -> ResolvedFileResult:
        """Resolve a recorded relative path to an existing local file strictly read-only."""
        return resolve_file_from_repos(
            rel_path,
            project_repo=self._project_repo,
            workspace_repo=self._ws_repo,
            event_repo=self._ev_repo,
            project_id=project_id,
            workspace_id=workspace_id,
            event_id=event_id,
        )

    def resolve_reveal_target(
        self,
        rel_path: str,
        *,
        project_id: str | None = None,
        workspace_id: str | None = None,
        event_id: str | None = None,
    ) -> RevealTargetResult:
        """Resolve a recorded relative path (with root bound) for Explorer reveal."""
        return resolve_reveal_from_repos(
            rel_path,
            project_repo=self._project_repo,
            workspace_repo=self._ws_repo,
            event_repo=self._ev_repo,
            project_id=project_id,
            workspace_id=workspace_id,
            event_id=event_id,
        )

    def get_month_markers(self, year: int, month: int, project_id: str | None = None) -> dict[int, DayMarkers]:
        """Return per-day boolean activity flags for ``(year, month)`` in one query per table."""
        start_utc, end_utc = local_month_utc_bounds(year, month, self._tz)
        obs_days = self._days_from_timestamps(self._ev_repo.list_timestamps_in_utc_range(start_utc, end_utc, project_id=project_id), year, month)
        cap_days = self._days_from_timestamps(self._capture_repo.list_timestamps_in_utc_range(start_utc, end_utc, project_id=project_id), year, month)
        ev_days = self._days_from_timestamps(self._calendar_repo.list_timestamps_in_range(start_utc, end_utc, project_id=project_id), year, month)
        return {
            day: DayMarkers(day in obs_days, day in cap_days, day in ev_days)
            for day in sorted(obs_days | cap_days | ev_days)
        }

    def get_day_timeline(self, local_date: date, project_id: str | None = None) -> DayTimeline:
        """Load separated observed, captured, and planned records for one local calendar date."""
        start_utc, end_utc = local_day_utc_bounds(local_date, self._tz)
        observed = self._ev_repo.list_in_utc_range(start_utc, end_utc, project_id=project_id)
        captures = self._capture_repo.list_in_utc_range(start_utc, end_utc, project_id=project_id)
        scheduled = self._calendar_repo.list_in_range(start_utc, end_utc, project_id=project_id)
        return self._build_timeline(local_date, observed, captures, scheduled)

    def get_recent_timeline(self, project_id: str, *, limit: int = 50) -> DayTimeline:
        """Load recent observed activity, captures, and events for a single project."""
        observed = [ev for ev in self._ev_repo.list_by_project(project_id, limit=limit) if not ev.is_baseline]
        captures = self._capture_repo.list_recent(project_id=project_id, limit=limit)
        scheduled = self._calendar_repo.list_recent(project_id=project_id, limit=limit)
        return self._build_timeline(None, observed, captures, scheduled)

    def search(self, query: str, project_id: str | None = None) -> SearchResults:
        """Search across projects, observed files, notes, and events via SearchRepository."""
        raw = self._search_repo.search_all(query, project_id=project_id, limit=50)
        timeline = self._build_timeline(None, raw.observed_events, raw.captures, raw.calendar_events)
        return SearchResults(raw.query, raw.projects, raw.observed_events, raw.captures, raw.calendar_events, timeline)

    def set_milestone(
        self,
        item_type: Literal["observed", "capture"],
        item_id: str,
        is_milestone: bool = True,
    ) -> bool:
        """Idempotently mark or unmark an observed event or capture entry as a milestone."""
        if item_type == "observed":
            if self._ev_repo.get(item_id) is None:
                return False
            self._ev_repo.set_milestone(item_id, is_milestone)
        elif item_type == "capture":
            if self._capture_repo.get(item_id) is None:
                return False
            self._capture_repo.set_milestone(item_id, is_milestone)
        else:
            raise ValueError(f"Unsupported milestone item_type: {item_type!r}")
        if self._bus is not None:
            self._bus.milestone_updated.emit(item_type, item_id, is_milestone)
        return is_milestone

    def toggle_milestone(self, item_type: Literal["observed", "capture"], item_id: str) -> bool:
        """Toggle milestone status on an observed event or capture entry without altering timelines."""
        if item_type == "observed":
            if (ev := self._ev_repo.get(item_id)) is None:
                return False
            next_val = not ev.is_milestone
            self._ev_repo.set_milestone(item_id, next_val)
        elif item_type == "capture":
            if (cap := self._capture_repo.get(item_id)) is None:
                return False
            next_val = not cap.is_milestone
            self._capture_repo.set_milestone(item_id, next_val)
        else:
            raise ValueError(f"Unsupported milestone item_type: {item_type!r}")
        if self._bus is not None:
            self._bus.milestone_updated.emit(item_type, item_id, next_val)
        return next_val

    def get_project_milestones(self, project_id: str) -> list[MilestoneItem]:
        """Return starred observed events and capture entries for ``project_id`` newest-first."""
        items: list[MilestoneItem] = []
        for ev in self._ev_repo.list_milestones(project_id):
            name = PurePosixPath(ev.rel_path).name or ev.rel_path
            items.append(MilestoneItem(
                item_id=ev.id, item_type="observed", project_id=project_id,
                timestamp_utc=ev.occurred_at_utc, title=name,
                detail=f"{ev.rel_path} \u00b7 {ev.event_type.capitalize()}",
            ))
        for cap in self._capture_repo.list_milestones(project_id):
            title = cap.note_text.strip() or cap.transcript_text.strip() or "(Image / screenshot capture)"
            items.append(MilestoneItem(
                item_id=cap.id, item_type="capture", project_id=project_id,
                timestamp_utc=cap.captured_at_utc, title=title,
                detail=cap.rel_path or "Note / capture",
            ))
        items.sort(key=lambda m: (m.timestamp_utc, m.item_id), reverse=True)
        return items

    def get_milestone_detail(
        self, item_type: Literal["observed", "capture"], item_id: str
    ) -> MilestoneDetail | None:
        """Load full inspection details for a starred observed event or capture entry."""
        project_names, ws_names = self._load_name_maps()
        att_dir = str(self._app_paths.attachments_dir) if self._app_paths is not None else ""
        if item_type == "capture":
            if (cap := self._capture_repo.get(item_id)) is None:
                return None
            local_dt = parse_utc_to_local(cap.captured_at_utc, self._tz)
            atts = tuple(self._capture_repo.list_attachments(cap.id))
            proj_name = project_names.get(cap.project_id or "", "General") if cap.project_id else "General"
            body = cap.note_text.strip() or cap.transcript_text.strip() or ("(Image / screenshot capture)" if atts else "(Capture)")
            title = PurePosixPath(cap.rel_path).name if cap.rel_path else "Note"
            return MilestoneDetail(
                item_id=cap.id, item_type="capture", project_id=cap.project_id,
                project_name=proj_name, timestamp_utc=cap.captured_at_utc,
                local_date=local_dt.date(), local_time_label=local_dt.strftime("%H:%M"),
                title=title, body_text=body, rel_path=cap.rel_path,
                attachments=atts, attachments_dir=att_dir,
                transcription=cap.transcription,
                audio_retention=cap.audio_retention,
                is_milestone=cap.is_milestone,
            )
        if item_type == "observed":
            if (ev := self._ev_repo.get(item_id)) is None:
                return None
            local_dt = parse_utc_to_local(ev.occurred_at_utc, self._tz)
            proj_name = project_names.get(ev.project_id or "", ws_names.get(ev.workspace_id, "Workspace")) if ev.project_id else ws_names.get(ev.workspace_id, "Workspace")
            title = PurePosixPath(ev.rel_path).name or ev.rel_path
            detail_lines = [f"Event: {ev.event_type.capitalize()}", f"Path: {ev.rel_path}"]
            if ev.old_rel_path:
                detail_lines.append(f"Previous path: {ev.old_rel_path}")
            if ev.file_size is not None:
                detail_lines.append(f"Size: {ev.file_size:,} bytes")
            return MilestoneDetail(
                item_id=ev.id, item_type="observed", project_id=ev.project_id,
                project_name=proj_name, timestamp_utc=ev.occurred_at_utc,
                local_date=local_dt.date(), local_time_label=local_dt.strftime("%H:%M"),
                title=title, body_text="\n".join(detail_lines), rel_path=ev.rel_path,
                event_type=ev.event_type, old_rel_path=ev.old_rel_path, file_size=ev.file_size,
                is_milestone=ev.is_milestone,
            )
        raise ValueError(f"Unsupported milestone item_type: {item_type!r}")

    def _build_timeline(
        self, local_date: date | None, observed: Sequence[ObservedEvent], captures: Sequence[object], scheduled: Sequence[object]
    ) -> DayTimeline:
        project_names, ws_names = self._load_name_maps()
        cap_ids = [c.id for c in captures]  # type: ignore[attr-defined]
        att_map = self._capture_repo.list_attachments_for_entries(cap_ids) if cap_ids else {}
        att_dir = str(self._app_paths.attachments_dir) if self._app_paths is not None else ""
        return DayTimeline(
            local_date=local_date,
            observed_groups=group_observed_events(observed, project_names, ws_names, tz=self._tz),
            captures=tuple(captures),  # type: ignore[arg-type]
            scheduled_events=tuple(scheduled),  # type: ignore[arg-type]
            project_names=project_names,
            capture_attachments=att_map,
            attachments_dir=att_dir,
        )

    def _days_from_timestamps(self, timestamps: Iterable[str], year: int, month: int) -> set[int]:
        days: set[int] = set()
        for ts in timestamps:
            local_dt = parse_utc_to_local(ts, self._tz)
            if local_dt.year == year and local_dt.month == month:
                days.add(local_dt.day)
        return days

    def _load_name_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        return (
            {p.id: p.name for p in self._project_repo.list_all()},
            {w.id: w.name for w in self._ws_repo.list_all()},
        )
