"""Primary desktop shell matching the calm dark layout in docs/ui_prototype.html."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.paths import AppPaths
from work_memory.config.settings import AppSettings
from work_memory.core.event_bus import EventBus
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.services.backup_service import BackupService
from work_memory.services.calendar_service import CalendarService
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.notification_service import NotificationService
from work_memory.services.project_service import ProjectService
from work_memory.services.relink_service import RelinkService
from work_memory.services.startup_service import StartupService
from work_memory.services.summary_service import SummaryService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.ui.app_icon import apply_windows_titlebar_theme, build_app_icon
from work_memory.ui.capture.quick_capture_dialog import QuickCaptureDialog
from work_memory.ui.capture.quick_capture_launcher import launch_or_reuse_quick_capture
from work_memory.ui.capture.toast_controller import ToastController
from work_memory.ui.shell_bars import build_nav_bar, build_top_bar
from work_memory.ui.theme import build_stylesheet, set_active_theme
from work_memory.ui.views.history_view import HistoryView
from work_memory.ui.views.project_detail_view import ProjectDetailView
from work_memory.ui.views.projects_view import ProjectsView
from work_memory.ui.views.settings_view import SettingsView


class MainWindow(QMainWindow):
    """Calm themed PySide6 main window with two primary tabs and top-right Settings."""

    theme_changed = Signal(str)

    def __init__(
        self,
        event_bus: EventBus,
        app_paths: AppPaths,
        workspace_service: WorkspaceService | None = None,
        project_service: ProjectService | None = None,
        history_service: HistoryService | None = None,
        capture_service: CaptureService | None = None,
        settings: AppSettings | None = None,
        notification_service: NotificationService | None = None,
        calendar_service: CalendarService | None = None,
        parent: QWidget | None = None,
        *,
        summary_service: SummaryService | None = None,
        relink_service: RelinkService | None = None,
        manifest_service: ManifestService | None = None,
        backup_service: BackupService | None = None,
        thumbnail_service: ThumbnailService | None = None,
        sound_player: SoundEffectsPlayer | None = None,
        startup_service: StartupService | None = None,
    ) -> None:
        super().__init__(parent)
        self._event_bus, self._workspace_service = event_bus, workspace_service
        self._project_service, self._history_service = project_service, history_service
        self._capture_service, self._current_page = capture_service, "projects"
        self._settings = settings or AppSettings()
        set_active_theme(self._settings.theme_mode)
        self._notification_service = notification_service
        self._calendar_service, self._summary_service = calendar_service, summary_service
        self._relink_service, self._manifest_service, self._backup_service = (
            relink_service, manifest_service, backup_service
        )
        self._startup_service = startup_service
        self._thumbnail_service = thumbnail_service or ThumbnailService(
            app_paths.thumbs_cache_dir,
            path_resolver=(
                (lambda r, p, w: history_service.resolve_file_path(r, project_id=p, workspace_id=w).resolved_path)
                if history_service is not None
                else None
            ),
            workspace_roots_provider=self._workspace_roots,
            parent=self,
        )
        self._sound_player = sound_player or SoundEffectsPlayer(
            app_paths.sounds_cache_dir,
            self._settings,
            workspace_roots_provider=self._workspace_roots,
            parent=self,
        )
        self._capture_dialog: QuickCaptureDialog | None = None
        self._force_quit = False
        self._toasts = ToastController(
            self,
            notification_service=notification_service,
            history_service=history_service,
            sound_player=self._sound_player,
        )
        self._toasts.open_capture_requested.connect(self._on_toast_open_capture)
        self._toasts.open_project_requested.connect(self._open_project_detail)
        self._toasts.restore_window_requested.connect(self.open_from_tray)
        self._active_toasts = self._toasts.active_toasts

        self.setWindowTitle("Work Memory")
        self.setWindowIcon(build_app_icon())
        self.setMinimumSize(960, 660)
        self.resize(1220, 800)
        self.setStyleSheet(build_stylesheet(self._settings.theme_mode))

        root = QWidget()
        root.setObjectName("rootSurface")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(42, 0, 42, 0)
        root_layout.setSpacing(0)

        top = build_top_bar(
            self._show_projects_page,
            self._on_search_changed,
            self._open_quick_capture,
            self._show_settings_page,
        )
        self._search_input, self._capture_btn = top.search_input, top.capture_btn
        self._settings_btn, self._status_dot = top.settings_btn, top.status_dot
        self._capture_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self._capture_shortcut.activated.connect(self._open_quick_capture)

        nav_bar, self._projects_tab, self._history_tab = build_nav_bar(
            self._show_projects_page,
            self._show_history_page,
        )
        root_layout.addWidget(top.frame)
        root_layout.addWidget(nav_bar)
        root_layout.addWidget(self._build_content_area(app_paths), 1)

        self.setCentralWidget(root)
        self._event_bus.status_message.connect(self._on_status_message)
        self._event_bus.monitoring_paused_changed.connect(self._on_monitoring_paused_changed)
        if self._notification_service is not None:
            self._notification_service.notification_triggered.connect(self._toasts.show_payload)
        if self._calendar_service is not None:
            self._calendar_service.reminder_triggered.connect(self._toasts.show_payload)
        if workspace_service is not None:
            self._on_monitoring_paused_changed(workspace_service.is_monitoring_paused())
        self._show_page("projects")

    def _build_content_area(self, app_paths: AppPaths) -> QStackedWidget:
        ws_svc = self._workspace_service
        roots_fn = (
            (lambda svc=ws_svc: [Path(ws.root_path) for ws in svc.cached_workspaces()])
            if ws_svc is not None
            else None
        )
        self._projects_view = ProjectsView(
            project_service=self._project_service,
            event_bus=self._event_bus,
            relink_service=self._relink_service,
            settings=self._settings,
            app_paths=app_paths,
            workspace_roots_provider=roots_fn,
        )
        self._history_view = HistoryView(
            history_service=self._history_service,
            event_bus=self._event_bus,
            calendar_service=self._calendar_service,
            project_service=self._project_service,
            thumbnail_service=self._thumbnail_service,
        )
        self._settings_view = SettingsView(
            app_paths=app_paths, workspace_service=self._workspace_service, event_bus=self._event_bus,
            settings=self._settings, notification_service=self._notification_service,
            relink_service=self._relink_service, manifest_service=self._manifest_service,
            backup_service=self._backup_service, project_service=self._project_service,
            startup_service=self._startup_service, sound_player=self._sound_player,
        )
        self._settings_view.theme_changed.connect(self.apply_theme)
        self._project_detail_view = ProjectDetailView(
            project_service=self._project_service, history_service=self._history_service,
            event_bus=self._event_bus, calendar_service=self._calendar_service,
            summary_service=self._summary_service, relink_service=self._relink_service,
            manifest_service=self._manifest_service,
            thumbnail_service=self._thumbnail_service,
        )

        self._projects_view.project_selected.connect(self._open_project_detail)
        self._projects_view.project_deleted.connect(self._on_project_deleted)
        self._history_view.project_selected.connect(self._open_project_detail)
        self._history_view.file_missing.connect(self._toasts.show_missing_file)
        self._history_view.info_toast.connect(self._toasts.show_info)
        self._project_detail_view.back_requested.connect(self._show_projects_page)
        self._project_detail_view.capture_requested.connect(self._open_quick_capture)
        self._project_detail_view.file_missing.connect(self._toasts.show_missing_file)
        self._project_detail_view.info_toast.connect(self._toasts.show_info)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._projects_view)
        self._stack.addWidget(self._history_view)
        self._stack.addWidget(self._settings_view)
        self._stack.addWidget(self._project_detail_view)
        return self._stack

    def _workspace_roots(self) -> list[Path]:
        if self._workspace_service is None:
            return []
        return [Path(ws.root_path) for ws in self._workspace_service.cached_workspaces()]

    def _show_page(self, page: str) -> None:
        self._current_page = page
        index_map = {"projects": 0, "history": 1, "settings": 2, "detail": 3}
        self._stack.setCurrentIndex(index_map[page])
        self._set_tab_active(self._projects_tab, page in ("projects", "detail"))
        self._set_tab_active(self._history_tab, page == "history")
        self._settings_btn.setChecked(page == "settings")
        self._apply_search_to_active_page(self._search_input.text())

    def _open_project_detail(self, project_id: str) -> None:
        cached = next((p for p in self._projects_view.cached_projects() if p.id == project_id), None)
        self._project_detail_view.show_project(project_id, project=cached)
        self._show_page("detail")

    def _on_project_deleted(self, project_id: str) -> None:
        if self._current_page == "detail" and self._project_detail_view.active_project_id == project_id:
            self._show_projects_page()

    def _set_tab_active(self, button: QPushButton, active: bool) -> None:
        button.setProperty("active", active)
        button.style().unpolish(button)
        button.style().polish(button)

    def _on_search_changed(self, text: str) -> None:
        self._apply_search_to_active_page(text)

    def _apply_search_to_active_page(self, text: str) -> None:
        if self._current_page == "projects":
            self._projects_view.set_search_query(text)
        elif self._current_page == "history":
            self._history_view.set_search_query(text)
        elif self._current_page == "detail":
            self._project_detail_view.set_search_query(text)

    def _on_status_message(self, message: str) -> None:
        if message:
            self._status_dot.setToolTip(message)

    def _on_monitoring_paused_changed(self, paused: bool) -> None:
        self._status_dot.setProperty("paused", paused)
        self._status_dot.style().unpolish(self._status_dot)
        self._status_dot.style().polish(self._status_dot)
        self._status_dot.setToolTip("Monitoring paused" if paused else "Observing workspaces (read-only)")

    def open_from_tray(self) -> None:
        """Restore and focus the main window when opened from the System Tray."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_application(self) -> None:
        """Force a full shutdown from the System Tray Quit action."""
        self._force_quit = True
        self.close()

    def _show_projects_page(self) -> None: self._show_page("projects")
    def _show_history_page(self) -> None: self._show_page("history")
    def _show_settings_page(self) -> None: self._show_page("settings")

    def apply_theme(self, mode: str) -> None:
        """Apply ``mode`` (``'dark'`` or ``'light'``) live across stylesheet, views, and title bar."""
        pal = set_active_theme(mode)
        qss = build_stylesheet(pal.mode)
        if (app := QApplication.instance()) is not None and hasattr(app, "setStyleSheet"):
            app.setStyleSheet(qss)  # type: ignore[attr-defined]
        self.setStyleSheet(qss)
        self._settings_view.refresh_theme()
        self._history_view.refresh_theme()
        self._project_detail_view.refresh_theme()
        self._projects_view.refresh_theme()
        apply_windows_titlebar_theme(self, pal.mode)
        self.theme_changed.emit(pal.mode)

    def _on_toast_open_capture(
        self,
        project_id: object,
        linked_file: str,
        launch_screenshot: bool,
        launch_voice: bool,
        initial_milestone: bool = False,
    ) -> None:
        pid = project_id if isinstance(project_id, str) else None
        self._open_quick_capture(
            pid,
            linked_file=linked_file,
            launch_screenshot=launch_screenshot,
            launch_voice=launch_voice,
            initial_milestone=initial_milestone,
        )

    def _open_quick_capture(
        self, project_id: str | None = None, *, linked_file: str = "",
        launch_screenshot: bool = False, launch_voice: bool = False,
        initial_milestone: bool = False,
    ) -> None:
        if self._capture_service is None:
            return
        detail_pid = self._project_detail_view.active_project_id if self._current_page == "detail" else None
        self._capture_dialog = launch_or_reuse_quick_capture(
            self, self._capture_dialog, self._capture_service, self._project_service,
            self._projects_view.cached_projects(), project_id=project_id,
            active_detail_project_id=detail_pid, linked_file=linked_file,
            launch_screenshot=launch_screenshot, launch_voice=launch_voice,
            initial_milestone=initial_milestone, sound_player=self._sound_player,
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Minimize to System Tray on close when configured, or shut down cleanly."""
        if (
            self._settings is not None
            and self._settings.minimize_to_tray_on_close
            and not self._force_quit
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            event.ignore()
            self.hide()
            return
        self._toasts.dismiss_all()
        if self._capture_dialog is not None:
            self._capture_dialog.force_close_on_shutdown()
        QThreadPool.globalInstance().waitForDone(2000)
        if self._calendar_service is not None:
            self._calendar_service.stop_poller()
        if self._workspace_service is not None:
            self._workspace_service.shutdown()
        super().closeEvent(event)
        if event.isAccepted() and (app := QApplication.instance()) is not None:
            app.quit()
