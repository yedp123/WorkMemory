"""Thin Qt signal bus decoupling background services from UI components."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Typed Qt signals emitted by application services and observed by UI views."""

    observed_event_recorded = Signal(object)
    capture_saved = Signal(object)
    project_updated = Signal(object)
    milestone_updated = Signal(str, str, bool)
    calendar_updated = Signal()
    projects_changed = Signal()
    suggestions_changed = Signal()
    workspaces_changed = Signal()
    monitoring_paused_changed = Signal(bool)
    status_message = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
