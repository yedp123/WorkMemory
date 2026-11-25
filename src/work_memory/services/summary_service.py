"""Offline rule-based project summary engine (Last Known State & Recent Activity)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, tzinfo
from pathlib import PurePosixPath

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import (
    CalendarEvent,
    CaptureEntry,
    ObservedEvent,
    Project,
    ProjectSummaryView,
    SummaryReference,
)
from work_memory.core.protocols import SummaryProvider
from work_memory.services.history_service import parse_utc_to_local, resolve_local_tz
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository


def _short_date(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _truncate(text: str, limit: int = 120) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}\u2026"


def _capture_text(cap: CaptureEntry) -> str:
    return (cap.note_text or cap.transcription or cap.transcript_text or "").strip()


def _format_generated_blob(view: ProjectSummaryView) -> str:
    parts = [p for p in (view.confirmed_text.strip(), view.inferred_text.strip()) if p]
    return " ".join(parts)


class RuleBasedSummaryProvider:
    """100% local, deterministic summary provider requiring zero internet or LLM."""

    def __init__(self, tz: tzinfo | None = None) -> None:
        self._tz = tz

    def generate_summary(
        self,
        project: Project,
        *,
        captures: Sequence[CaptureEntry],
        observed_events: Sequence[ObservedEvent],
        scheduled_events: Sequence[CalendarEvent],
    ) -> ProjectSummaryView:
        """Synthesize a ``ProjectSummaryView`` from separated project records."""
        zone = resolve_local_tz(self._tz)
        now_utc = utc_now_iso()
        today_local = datetime.now(zone).date()

        caps_sorted = sorted(captures, key=lambda c: (c.captured_at_utc, c.id), reverse=True)
        obs_sorted = sorted(
            (ev for ev in observed_events if not ev.is_baseline),
            key=lambda e: (e.occurred_at_utc, e.id),
            reverse=True,
        )

        confirmed = self._build_confirmed(caps_sorted, obs_sorted, zone)
        inferred = self._build_inferred(obs_sorted, scheduled_events, now_utc, zone)
        recent, active_date = self._build_recent(caps_sorted, obs_sorted, today_local, zone)
        refs = self._build_references(caps_sorted, obs_sorted, active_date)

        return ProjectSummaryView(
            project_id=project.id,
            confirmed_text=confirmed,
            inferred_text=inferred,
            custom_text=project.summary_custom,
            recent_summary=recent,
            references=refs,
            updated_utc=project.summary_updated_utc or now_utc,
        )

    def _build_confirmed(
        self,
        caps_sorted: list[CaptureEntry],
        obs_sorted: list[ObservedEvent],
        zone: tzinfo,
    ) -> str:
        for cap in caps_sorted:
            if text := _capture_text(cap):
                d = parse_utc_to_local(cap.captured_at_utc, zone).date()
                return f'Latest note ({_short_date(d)}): "{_truncate(text)}".'

        milestone_obs = next((e for e in obs_sorted if e.is_milestone), None)
        milestone_cap = next((c for c in caps_sorted if c.is_milestone), None)
        if milestone_cap is not None and (
            milestone_obs is None or milestone_cap.captured_at_utc >= milestone_obs.occurred_at_utc
        ):
            d = parse_utc_to_local(milestone_cap.captured_at_utc, zone).date()
            return f"Starred milestone ({_short_date(d)}): capture recorded."
        if milestone_obs is not None:
            d = parse_utc_to_local(milestone_obs.occurred_at_utc, zone).date()
            name = PurePosixPath(milestone_obs.rel_path).name or milestone_obs.rel_path
            return f"Starred milestone ({_short_date(d)}): {name} ({milestone_obs.event_type})."
        return ""

    def _build_inferred(
        self,
        obs_sorted: list[ObservedEvent],
        scheduled_events: Sequence[CalendarEvent],
        now_utc: str,
        zone: tzinfo,
    ) -> str:
        sentences: list[str] = []
        if obs_sorted:
            latest = obs_sorted[0]
            latest_day = parse_utc_to_local(latest.occurred_at_utc, zone).date()
            day_events = [
                ev
                for ev in obs_sorted
                if parse_utc_to_local(ev.occurred_at_utc, zone).date() == latest_day
            ]
            main_name = PurePosixPath(latest.rel_path).name or latest.rel_path
            count = len(day_events)
            noun = "file" if count == 1 else "files"
            sentences.append(
                f"Recent file activity on {_short_date(latest_day)} ({count} {noun} changed, including {main_name})."
            )

        upcoming = sorted(
            (ev for ev in scheduled_events if ev.status == "scheduled" and ev.event_at_utc >= now_utc),
            key=lambda e: (e.event_at_utc, e.id),
        )
        if upcoming:
            nxt = upcoming[0]
            nxt_day = parse_utc_to_local(nxt.event_at_utc, zone).date()
            sentences.append(f'Next scheduled event: "{_truncate(nxt.title, 80)}" on {_short_date(nxt_day)}.')

        return " ".join(sentences) if sentences else "No file activity or scheduled events recorded yet."

    def _build_recent(
        self,
        caps_sorted: list[CaptureEntry],
        obs_sorted: list[ObservedEvent],
        today_local: date,
        zone: tzinfo,
    ) -> tuple[str, date | None]:
        candidates: list[date] = []
        if obs_sorted:
            candidates.append(parse_utc_to_local(obs_sorted[0].occurred_at_utc, zone).date())
        if caps_sorted:
            candidates.append(parse_utc_to_local(caps_sorted[0].captured_at_utc, zone).date())
        if not candidates:
            return "No recent sessions recorded yet.", None

        active_date = max(candidates)
        file_count = sum(
            1 for ev in obs_sorted if parse_utc_to_local(ev.occurred_at_utc, zone).date() == active_date
        )
        note_count = sum(
            1 for cap in caps_sorted if parse_utc_to_local(cap.captured_at_utc, zone).date() == active_date
        )
        counts: list[str] = []
        if file_count:
            counts.append(f"{file_count} file{'s' if file_count != 1 else ''} changed")
        if note_count:
            counts.append(f"{note_count} note{'s' if note_count != 1 else ''} captured")
        prefix = "Today" if active_date == today_local else "Most recent session"
        return f"{prefix} ({_short_date(active_date)}): {', '.join(counts)}.", active_date

    def _build_references(
        self,
        caps_sorted: list[CaptureEntry],
        obs_sorted: list[ObservedEvent],
        active_date: date | None,
    ) -> list[SummaryReference]:
        refs: list[SummaryReference] = []
        latest_cap = caps_sorted[0] if caps_sorted else None
        if latest_cap is not None:
            refs.append(SummaryReference(label="Open latest note", item_type="capture", item_id=latest_cap.id))

        milestone_cap = next((c for c in caps_sorted if c.is_milestone), None)
        milestone_obs = next((e for e in obs_sorted if e.is_milestone), None)
        if milestone_cap is not None and (
            milestone_obs is None or milestone_cap.captured_at_utc >= milestone_obs.occurred_at_utc
        ):
            if latest_cap is None or milestone_cap.id != latest_cap.id:
                refs.append(
                    SummaryReference(label="Open latest milestone", item_type="capture", item_id=milestone_cap.id)
                )
        elif milestone_obs is not None:
            refs.append(
                SummaryReference(label="Open latest milestone", item_type="observed", item_id=milestone_obs.id)
            )

        if active_date is not None and len(refs) < 3:
            refs.append(
                SummaryReference(
                    label=f"Jump to {_short_date(active_date)}",
                    item_type="date",
                    local_date=active_date.isoformat(),
                )
            )
        return refs[:3]


class SummaryService:
    """Computes, caches, and persists Last Known State project summaries."""

    def __init__(
        self,
        database: Database,
        *,
        provider: SummaryProvider | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        self._project_repo = ProjectRepository(database)
        self._capture_repo = CaptureRepository(database)
        self._ev_repo = ObservedEventRepository(database)
        self._calendar_repo = CalendarRepo(database)
        self._provider: SummaryProvider = provider or RuleBasedSummaryProvider(tz=tz)

    def get_project_summary(self, project_id: str) -> ProjectSummaryView:
        """Return the current structured summary for ``project_id``."""
        project = self._require_project(project_id)
        return self._generate_view(project)

    def save_custom_summary(self, project_id: str, custom_text: str) -> ProjectSummaryView:
        """Persist a user-edited custom summary without altering original notes or events."""
        project = self._require_project(project_id)
        cleaned = custom_text.strip()
        if not cleaned:
            return self.regenerate_summary(project_id)
        now = utc_now_iso()
        self._project_repo.update_summary(project_id, cleaned, project.summary_generated, now)
        updated = self._require_project(project_id)
        return self._generate_view(updated)

    def regenerate_summary(self, project_id: str) -> ProjectSummaryView:
        """Clear any custom summary override and regenerate fresh rule-based text."""
        project = self._require_project(project_id)
        project.summary_custom = None
        view = self._generate_view(project)
        now = utc_now_iso()
        generated_blob = _format_generated_blob(view)
        self._project_repo.update_summary(project_id, None, generated_blob, now)
        return ProjectSummaryView(
            project_id=view.project_id,
            confirmed_text=view.confirmed_text,
            inferred_text=view.inferred_text,
            custom_text=None,
            recent_summary=view.recent_summary,
            references=view.references,
            updated_utc=now,
        )

    def refresh_generated_summary(self, project_id: str) -> None:
        """Refresh stored generated summary without overwriting a manual custom edit."""
        project = self._project_repo.get(project_id)
        if project is None:
            return
        view = self._generate_view(project)
        now = utc_now_iso()
        self._project_repo.update_summary(
            project_id,
            project.summary_custom,
            _format_generated_blob(view),
            now,
        )

    def _require_project(self, project_id: str) -> Project:
        project = self._project_repo.get(project_id)
        if project is None:
            raise ValueError(f"Unknown project_id: {project_id!r}")
        return project

    def _generate_view(self, project: Project) -> ProjectSummaryView:
        captures = self._capture_repo.list_recent(project_id=project.id, limit=50)
        observed = self._ev_repo.list_by_project(project.id, limit=100)
        scheduled = self._calendar_repo.list_recent(project_id=project.id, limit=50)
        return self._provider.generate_summary(
            project,
            captures=captures,
            observed_events=observed,
            scheduled_events=scheduled,
        )
