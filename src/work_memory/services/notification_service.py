"""Non-intrusive notification engine separating file events from periodic reminders."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from PySide6.QtCore import QObject, QTimer, Signal

from work_memory.config.settings import DEFAULT_REMINDER_MESSAGE, AppSettings
from work_memory.core.event_bus import EventBus
from work_memory.core.ids import new_id
from work_memory.core.models import ObservedEvent
from work_memory.services.project_service import ProjectService
from work_memory.services.windows_state import should_suppress_notification

NotificationKind = Literal["new_file", "repeated_save", "timed_reminder", "calendar_event", "info"]


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    """Immutable payload delivered from ``NotificationService`` to the UI toast layer."""

    notif_id: str
    kind: NotificationKind
    title: str
    message: str
    project_id: str | None
    event_id: str | None
    rel_path: str | None
    duration_sec: int


class NotificationService(QObject):
    """Coordinates cooldown-guarded file alerts, repeated-save alerts, and timed reminders."""

    notification_triggered = Signal(object)

    def __init__(
        self,
        settings: AppSettings,
        *,
        project_service: ProjectService | None = None,
        event_bus: EventBus | None = None,
        suppress_fn: Callable[[float], bool] | None = None,
        clock_fn: Callable[[], float] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._project_service = project_service
        self._suppress_fn = suppress_fn or should_suppress_notification
        self._clock = clock_fn or time.monotonic
        self._is_paused = False
        self._new_file_cooldown_sec = 30.0
        self._save_burst_dedupe_sec = 10.0
        self._last_new_file_at: dict[str, float] = {}
        self._save_counts: dict[str, int] = {}
        self._last_save_counted_at: dict[str, float] = {}

        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self.trigger_timed_reminder)

        if event_bus is not None:
            event_bus.observed_event_recorded.connect(self.handle_observed_event)
            event_bus.monitoring_paused_changed.connect(self.set_monitoring_paused)

        self._sync_reminder_timer()

    def update_settings(self, settings: AppSettings) -> None:
        """Apply updated ``AppSettings`` immediately and reschedule the timed reminder."""
        self._settings = settings
        self._sync_reminder_timer()

    def set_monitoring_paused(self, paused: bool) -> None:
        """Pause or resume filesystem and timed notifications."""
        self._is_paused = paused
        self._sync_reminder_timer()

    def reset_save_counter(self, project_id: str | None) -> None:
        """Reset the repeated-save counter for ``project_id`` after handling or dismissal."""
        if project_id:
            self._save_counts.pop(project_id, None)

    def handle_observed_event(self, event: object) -> NotificationPayload | None:
        """Evaluate a live ``ObservedEvent`` and emit a contextual notification if eligible."""
        if not isinstance(event, ObservedEvent) or self._is_paused or event.is_baseline:
            return None
        key = event.project_id or f"ws:{event.workspace_id}"
        now = self._clock()
        if event.event_type == "created":
            return self._handle_created(event, key, now)
        if event.event_type == "modified":
            return self._handle_modified(event, key, now)
        return None

    def trigger_timed_reminder(self) -> NotificationPayload | None:
        """Emit a generic periodic save reminder when active and not suppressed."""
        if self._is_paused or self._settings.save_reminder_minutes <= 0:
            return None
        if self._suppress_fn(120.0):
            return None
        payload = NotificationPayload(
            notif_id=new_id(),
            kind="timed_reminder",
            title="Save reminder",
            message=self._settings.save_reminder_message.strip() or DEFAULT_REMINDER_MESSAGE,
            project_id=None,
            event_id=None,
            rel_path=None,
            duration_sec=self._settings.notification_duration_sec,
        )
        self.notification_triggered.emit(payload)
        return payload

    def _handle_created(self, event: ObservedEvent, key: str, now: float) -> NotificationPayload | None:
        if not self._settings.new_file_notifications:
            return None
        last = self._last_new_file_at.get(key)
        if last is not None and (now - last) < self._new_file_cooldown_sec:
            return None
        if self._suppress_fn(120.0):
            return None
        self._last_new_file_at[key] = now
        proj_name = self._resolve_project_name(event.project_id)
        file_name = PurePosixPath(event.rel_path).name or event.rel_path
        payload = NotificationPayload(
            notif_id=new_id(),
            kind="new_file",
            title=f"New file in {proj_name}" if proj_name else "New file created",
            message=file_name,
            project_id=event.project_id,
            event_id=event.id,
            rel_path=event.rel_path,
            duration_sec=self._settings.notification_duration_sec,
        )
        self.notification_triggered.emit(payload)
        return payload

    def _handle_modified(self, event: ObservedEvent, key: str, now: float) -> NotificationPayload | None:
        interval = self._settings.repeated_save_interval
        if interval <= 0:
            return None
        last_counted = self._last_save_counted_at.get(key)
        if last_counted is not None and (now - last_counted) < self._save_burst_dedupe_sec:
            return None
        self._last_save_counted_at[key] = now
        count = self._save_counts.get(key, 0) + 1
        self._save_counts[key] = count
        if count < interval or self._suppress_fn(120.0):
            return None
        self._save_counts[key] = 0
        proj_name = self._resolve_project_name(event.project_id)
        file_name = PurePosixPath(event.rel_path).name or event.rel_path
        payload = NotificationPayload(
            notif_id=new_id(),
            kind="repeated_save",
            title=f"Multiple saves in {proj_name}" if proj_name else "Multiple saves detected",
            message=f"{file_name} ({interval} saves)",
            project_id=event.project_id,
            event_id=event.id,
            rel_path=event.rel_path,
            duration_sec=self._settings.notification_duration_sec,
        )
        self.notification_triggered.emit(payload)
        return payload

    def _resolve_project_name(self, project_id: str | None) -> str:
        if not project_id or self._project_service is None:
            return ""
        proj = self._project_service.get_project(project_id)
        return proj.name if proj is not None else ""

    def _sync_reminder_timer(self) -> None:
        mins = self._settings.save_reminder_minutes
        if self._is_paused or mins <= 0:
            self._reminder_timer.stop()
            return
        self._reminder_timer.start(mins * 60_000)
