"""System tray icon and context menu controller for background Work Memory operation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from work_memory.ui.app_icon import build_app_icon as build_tray_icon


class SystemTrayController(QObject):
    """Manages the ``QSystemTrayIcon``, status tooltip, and tray context menu."""

    open_requested = Signal()
    quick_capture_requested = Signal()
    toggle_monitoring_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(build_tray_icon(), self)
        self._menu = QMenu()

        self._open_action = QAction("Open Work Memory", self._menu)
        self._open_action.triggered.connect(self.open_requested.emit)

        self._capture_action = QAction("Quick Capture (Ctrl+Shift+M)", self._menu)
        self._capture_action.triggered.connect(self.quick_capture_requested.emit)

        self._pause_action = QAction("Pause Monitoring", self._menu)
        self._pause_action.triggered.connect(self.toggle_monitoring_requested.emit)

        self._quit_action = QAction("Quit Work Memory", self._menu)
        self._quit_action.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(self._open_action)
        self._menu.addAction(self._capture_action)
        self._menu.addAction(self._pause_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self.set_paused(False)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()

    def set_paused(self, paused: bool) -> None:
        """Sync tray tooltip and Pause/Resume menu label with monitoring state."""
        self._pause_action.setText("Resume Monitoring" if paused else "Pause Monitoring")
        self._tray.setToolTip("Work Memory \u2014 Paused" if paused else "Work Memory \u2014 Observing")

    def hide(self) -> None:
        """Hide the tray icon cleanly on application shutdown."""
        self._tray.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()
