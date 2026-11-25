"""Application service for calendar events and sleep-safe reminder polling."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from PySide6.QtCore import QObject, QTimer, Signal

from work_memory.core.event_bus import EventBus
from work_memory.core.ids import new_id, utc_now_iso
from work_memory.core.models import CalendarEvent, CalendarEventStatus
from work_memory.services.history_service import parse_utc_to_local, resolve_local_tz
from work_memory.services.notification_service import NotificationPayload
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.project_repo import ProjectRepository

logger = logging.getLogger(__name__)


def local_datetime_to_utc_iso(
    local_date: date, local_time: time, tz: tzinfo | None = None
) -> str:
    """Convert a local calendar date and time into an ISO-8601 UTC string."""
    zone = resolve_local_tz(tz)
    local_dt = datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        local_time.hour,
        local_time.minute,
        local_time.second,
        tzinfo=zone,
    )
    return local_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_remind_at_utc(event_at_utc: str, reminder_minutes: int | None) -> str | None:
    """Compute ``remind_at_utc = event_at_utc - reminder_minutes`` or ``None`` if disabled."""
    if reminder_minutes is None:
        return None
    normalized = f"{event_at_utc[:-1]}+00:00" if event_at_utc.endswith("Z") else event_at_utc
    dt = datetime.fromisoformat(normalized)
    utc_dt = (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).astimezone(UTC)
    remind_dt = utc_dt - timedelta(minutes=int(reminder_minutes))
    return remind_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class CalendarService(QObject):
    """Manages scheduled calendar events and sleep-safe desktop reminder polling."""

    reminder_triggered = Signal(object)

    def __init__(
        self,
        database: Database,
        event_bus: EventBus | None = None,
        *,
        tz: tzinfo | None = None,
        poll_interval_ms: int = 15_000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = event_bus
        self._tz = tz
        self._poll_interval_ms = poll_interval_ms
        self._repo = CalendarRepo(database)
        self._project_repo = ProjectRepository(database)
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self.check_due_reminders)

    def start_poller(self) -> None:
        """Start the 15-second sleep-safe reminder poller and check immediately."""
        self.check_due_reminders()
        if not self._timer.isActive():
            self._timer.start()

    def stop_poller(self) -> None:
        """Stop the reminder poller cleanly on application shutdown."""
        self._timer.stop()

    def get_event(self, event_id: str) -> CalendarEvent | None:
        """Return a single calendar event by ID."""
        return self._repo.get_by_id(event_id)

    def create_event(
        self,
        *,
        title: str,
        local_date: date,
        local_time: time,
        project_id: str | None = None,
        reminder_minutes: int | None = 10,
        description: str = "",
    ) -> CalendarEvent:
        """Create a scheduled calendar event in local time and persist it as UTC."""
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Event title is required.")
        event_at_utc = local_datetime_to_utc_iso(local_date, local_time, self._tz)
        remind_at_utc = compute_remind_at_utc(event_at_utc, reminder_minutes)
        event = CalendarEvent(
            title=clean_title,
            starts_at_utc=event_at_utc,
            event_at_utc=event_at_utc,
            project_id=project_id or None,
            description=description.strip(),
            reminder_minutes=reminder_minutes,
            remind_at_utc=remind_at_utc,
            status="scheduled",
        )
        self._repo.create(event)
        if self._bus is not None:
            self._bus.calendar_updated.emit()
            self._bus.status_message.emit("Event scheduled")
        return event

    def update_event(
        self,
        event_id: str,
        *,
        title: str,
        local_date: date,
        local_time: time,
        project_id: str | None = None,
        reminder_minutes: int | None = 10,
        description: str = "",
        status: CalendarEventStatus | None = None,
    ) -> CalendarEvent | None:
        """Update an existing calendar event, status, and recalculate its UTC reminder time."""
        existing = self._repo.get_by_id(event_id)
        if existing is None:
            return None
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Event title is required.")
        next_status = status if status is not None else existing.status
        if next_status not in ("scheduled", "completed", "cancelled"):
            raise ValueError(f"Invalid calendar event status: {next_status!r}")
        event_at_utc = local_datetime_to_utc_iso(local_date, local_time, self._tz)
        remind_at_utc = compute_remind_at_utc(event_at_utc, reminder_minutes)
        reopened = existing.status != "scheduled" and next_status == "scheduled"
        if (
            event_at_utc != existing.event_at_utc
            or reminder_minutes != existing.reminder_minutes
            or remind_at_utc != existing.remind_at_utc
            or reopened
        ):
            existing.notified_at_utc = None
        existing.title = clean_title
        existing.project_id = project_id or None
        existing.description = description.strip()
        existing.starts_at_utc = event_at_utc
        existing.event_at_utc = event_at_utc
        existing.reminder_minutes = reminder_minutes
        existing.remind_at_utc = remind_at_utc
        existing.status = next_status
        self._repo.update(existing)
        if self._bus is not None:
            self._bus.calendar_updated.emit()
        return existing

    def set_status(self, event_id: str, status: CalendarEventStatus) -> CalendarEvent | None:
        """Explicitly set an event's status (never auto-completed)."""
        updated = self._repo.update_status(event_id, status)
        if updated is not None and self._bus is not None:
            self._bus.calendar_updated.emit()
        return updated

    def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event and emit ``calendar_updated``."""
        deleted = self._repo.delete(event_id)
        if deleted and self._bus is not None:
            self._bus.calendar_updated.emit()
        return deleted

    def check_due_reminders(self, now_utc: str | None = None) -> list[NotificationPayload]:
        """Find due scheduled reminders, mark them notified immediately, and emit payloads."""
        now = now_utc or utc_now_iso()
        due = self._repo.list_due_reminders(now)
        if not due:
            return []
        project_names = {p.id: p.name for p in self._project_repo.list_all()}
        emitted: list[NotificationPayload] = []
        for ev in due:
            self._repo.mark_notified(ev.id, now)
            proj_name = project_names.get(ev.project_id or "", "") if ev.project_id else ""
            if ev.reminder_minutes is None or ev.reminder_minutes <= 0:
                lead = "starts now"
            elif ev.reminder_minutes == 60:
                lead = "starts in 1 hour"
            else:
                lead = f"starts in {ev.reminder_minutes} minutes"
            title = f"{ev.title} {lead}"
            if proj_name:
                title = f"{title} \u2014 {proj_name}"
            local_dt = parse_utc_to_local(ev.event_at_utc, self._tz)
            msg = ev.description.strip() or f"Scheduled for {local_dt.strftime('%H:%M')}"
            payload = NotificationPayload(
                notif_id=new_id(),
                kind="calendar_event",
                title=title,
                message=msg,
                project_id=ev.project_id,
                event_id=ev.id,
                rel_path=None,
                duration_sec=10,
            )
            emitted.append(payload)
            self.reminder_triggered.emit(payload)
            logger.info("Emitted calendar reminder for event %s (%s).", ev.id, ev.title)
        return emitted
