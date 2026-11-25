"""Toast popup lifecycle manager extracted from MainWindow."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from work_memory.core.ids import new_id
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.services.history_service import HistoryService
from work_memory.services.notification_service import NotificationPayload, NotificationService
from work_memory.ui.capture.toast_popup import ToastPopup, reposition_toasts
from work_memory.ui.workers import run_in_pool


class ToastController(QObject):
    """Manages active floating ``ToastPopup`` instances and their signal routing."""

    open_capture_requested = Signal(object, str, bool, bool, bool)
    open_project_requested = Signal(str)
    restore_window_requested = Signal()

    def __init__(
        self,
        owner: QWidget,
        *,
        notification_service: NotificationService | None = None,
        history_service: HistoryService | None = None,
        sound_player: SoundEffectsPlayer | None = None,
    ) -> None:
        super().__init__(owner)
        self._notification_service = notification_service
        self._history_service = history_service
        self._sound_player = sound_player
        self.active_toasts: list[ToastPopup] = []
        self._workers: set[QObject] = set()

    def show_payload(self, payload: object) -> None:
        """Display ``payload`` in a non-focus-stealing ``ToastPopup``."""
        if not isinstance(payload, NotificationPayload):
            return
        toast = ToastPopup(payload)
        toast.add_note_requested.connect(
            lambda p: self.open_capture_requested.emit(p.project_id, p.rel_path or "", False, False, False)
        )
        toast.screenshot_requested.connect(
            lambda p: self.open_capture_requested.emit(p.project_id, p.rel_path or "", True, False, False)
        )
        toast.voice_requested.connect(
            lambda p: self.open_capture_requested.emit(p.project_id, p.rel_path or "", False, True, False)
        )
        toast.milestone_requested.connect(self._on_milestone)
        toast.open_project_requested.connect(self._on_open_project_click)
        toast.dismissed.connect(self._on_dismissed)
        self.active_toasts.append(toast)
        toast.show()
        reposition_toasts(self.active_toasts)
        if payload.kind != "info" and self._sound_player is not None:
            self._sound_player.play_notification_ding()

    def show_missing_file(self, filename: str) -> None:
        """Show a quiet auto-dismissing toast when a clicked file is missing on disk."""
        self.show_info("File unavailable", f"File not found on disk: {filename}")

    def show_info(self, title: str, message: str) -> None:
        """Show a quiet auto-dismissing informational toast."""
        self.show_payload(
            NotificationPayload(
                notif_id=new_id(),
                kind="info",
                title=title,
                message=message,
                project_id=None,
                event_id=None,
                rel_path=None,
                duration_sec=4,
            )
        )

    def dismiss_all(self) -> None:
        """Dismiss every currently visible toast popup."""
        for toast in list(self.active_toasts):
            toast.dismiss()

    def _on_milestone(self, payload: object) -> None:
        if not isinstance(payload, NotificationPayload) or not payload.event_id:
            return
        if self._notification_service is not None:
            self._notification_service.reset_save_counter(payload.project_id)
        if (svc := self._history_service) is not None:
            eid = payload.event_id
            run_in_pool(
                self,
                self._workers,
                lambda: svc.set_milestone("observed", eid, True),
                lambda _ok: None,
            )
        self.open_capture_requested.emit(
            payload.project_id, payload.rel_path or "", False, False, True
        )

    def _on_open_project_click(self, payload: object) -> None:
        if isinstance(payload, NotificationPayload) and payload.project_id:
            self.open_project_requested.emit(payload.project_id)
            self.restore_window_requested.emit()

    def _on_dismissed(self, toast: object) -> None:
        if isinstance(toast, ToastPopup):
            if toast in self.active_toasts:
                self.active_toasts.remove(toast)
            toast.deleteLater()
            reposition_toasts(self.active_toasts)
