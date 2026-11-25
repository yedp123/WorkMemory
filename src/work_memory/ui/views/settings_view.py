"""Settings view accessed via the top-right gear icon."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)

from work_memory.config.paths import AppPaths
from work_memory.config.settings import AppSettings, save_settings
from work_memory.core.event_bus import EventBus
from work_memory.core.models import Workspace
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.services.backup_service import BackupService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.notification_service import NotificationService
from work_memory.services.project_service import ProjectService
from work_memory.services.relink_service import RelinkService
from work_memory.services.startup_service import StartupService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.ui.widgets.audio_appearance_cards import (
    AppearanceSettingsCard,
    AudioSettingsCard,
)
from work_memory.ui.widgets.notification_settings_card import NotificationSettingsCard
from work_memory.ui.widgets.portability_card import PortabilityCard
from work_memory.ui.widgets.scroll_helpers import wrap_in_scroll_area
from work_memory.ui.widgets.settings_cards import (
    build_readonly_banner,
    build_startup_card,
    build_workspace_row,
)


class SettingsView(QWidget):
    """Quiet Settings page displaying read-only guarantees, workspaces, audio, and theme."""

    theme_changed = Signal(str)

    def __init__(
        self,
        app_paths: AppPaths,
        workspace_service: WorkspaceService | None = None,
        event_bus: EventBus | None = None,
        *,
        settings: AppSettings | None = None,
        notification_service: NotificationService | None = None,
        relink_service: RelinkService | None = None,
        manifest_service: ManifestService | None = None,
        backup_service: BackupService | None = None,
        project_service: ProjectService | None = None,
        startup_service: StartupService | None = None,
        sound_player: SoundEffectsPlayer | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_paths = app_paths
        self._workspace_service = workspace_service
        self._settings = settings or AppSettings()
        self._notification_service = notification_service
        self._relink_service = relink_service
        self._manifest_service = manifest_service
        self._backup_service = backup_service
        self._project_service = project_service
        self._startup_service = startup_service or StartupService()
        self._sound_player = sound_player
        self._is_paused = (
            workspace_service.is_monitoring_paused() if workspace_service is not None else False
        )

        self._scroll_area, _content, layout = wrap_in_scroll_area(
            self, margins=(0, 30, 0, 40), spacing=18
        )

        title = QLabel("Settings")
        title.setProperty("role", "pageTitle")
        subtitle = QLabel("Local-first configuration. Your original folders are never modified.")
        subtitle.setProperty("role", "subtitle")

        header_box = QVBoxLayout()
        header_box.setSpacing(4)
        header_box.addWidget(title)
        header_box.addWidget(subtitle)
        layout.addLayout(header_box)

        layout.addWidget(build_readonly_banner())
        self._appearance_card = AppearanceSettingsCard(self._settings.theme_mode)
        self._appearance_card.theme_changed.connect(self._on_theme_selected)
        layout.addWidget(self._appearance_card)
        layout.addWidget(self._build_workspaces_card())
        self._notif_card = NotificationSettingsCard(self._settings)
        self._notif_card.settings_changed.connect(self._on_notification_setting_changed)
        self._new_file_cb = self._notif_card.new_file_cb
        self._repeat_combo = self._notif_card.repeat_combo
        self._duration_combo = self._notif_card.duration_combo
        self._reminder_combo = self._notif_card.reminder_combo
        layout.addWidget(self._notif_card)

        self._audio_card = AudioSettingsCard(self._settings, sound_player=self._sound_player)
        self._audio_card.settings_changed.connect(self._on_notification_setting_changed)
        layout.addWidget(self._audio_card)

        startup_widgets = build_startup_card(
            self._startup_service.is_startup_enabled(), self._on_startup_toggled
        )
        self._startup_cb = startup_widgets.startup_cb
        layout.addWidget(startup_widgets.card)

        layout.addWidget(
            PortabilityCard(
                app_paths,
                backup_service=self._backup_service,
                manifest_service=self._manifest_service,
                project_service=self._project_service,
            )
        )
        layout.addStretch(1)

        if event_bus is not None:
            event_bus.workspaces_changed.connect(self._refresh_from_service)
            event_bus.monitoring_paused_changed.connect(self._on_monitoring_paused_changed)
        self._refresh_from_service()

    @property
    def scroll_area(self) -> QScrollArea:
        """Return this view's independent ``QScrollArea``."""
        return self._scroll_area

    def vertical_scroll_bar(self) -> QScrollBar:
        """Return this view's vertical scrollbar."""
        return self._scroll_area.verticalScrollBar()

    def _build_workspaces_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("surface", True)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        heading = QLabel("Monitored workspaces")
        heading.setProperty("role", "sectionTitle")

        self._add_btn = QPushButton("+ Add folder")
        self._add_btn.setObjectName("addWorkspaceButton")
        self._add_btn.setProperty("secondary", True)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setEnabled(self._workspace_service is not None)
        self._add_btn.clicked.connect(self._on_add_folder)

        self._toggle_monitor_btn = QPushButton("Pause monitoring")
        self._toggle_monitor_btn.setObjectName("toggleMonitoringButton")
        self._toggle_monitor_btn.setProperty("secondary", True)
        self._toggle_monitor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_monitor_btn.setEnabled(self._workspace_service is not None)
        self._toggle_monitor_btn.clicked.connect(self._on_toggle_monitoring)

        header.addWidget(heading)
        header.addStretch(1)
        header.addWidget(self._add_btn)
        header.addWidget(self._toggle_monitor_btn)
        inner.addLayout(header)

        self._workspace_list = QWidget()
        self._workspace_list.setObjectName("workspaceListContainer")
        self._workspace_list_layout = QVBoxLayout(self._workspace_list)
        self._workspace_list_layout.setContentsMargins(0, 0, 0, 0)
        self._workspace_list_layout.setSpacing(0)
        inner.addWidget(self._workspace_list)
        return card

    def _workspace_roots(self) -> list[Path]:
        if self._workspace_service is None:
            return []
        return [Path(ws.root_path) for ws in self._workspace_service.cached_workspaces()]

    def refresh_theme(self) -> None:
        """Re-apply active theme styling across child settings cards."""
        self._notif_card.refresh_theme()
        self._audio_card.refresh_theme()

    def _on_notification_setting_changed(self) -> None:
        self._notif_card.apply_to(self._settings)
        self._audio_card.apply_to(self._settings)
        save_settings(self._app_paths, self._settings, workspace_roots=self._workspace_roots())
        if self._notification_service is not None:
            self._notification_service.update_settings(self._settings)
        if self._sound_player is not None:
            self._sound_player.update_settings(self._settings)

    def _on_theme_selected(self, mode: str) -> None:
        self._settings.theme_mode = mode
        save_settings(self._app_paths, self._settings, workspace_roots=self._workspace_roots())
        self.theme_changed.emit(mode)

    def _on_startup_toggled(self, enabled: bool) -> None:
        if not self._startup_service.set_startup_enabled(enabled):
            with QSignalBlocker(self._startup_cb):
                self._startup_cb.setChecked(self._startup_service.is_startup_enabled())
            return
        self._settings.launch_at_startup = enabled
        save_settings(self._app_paths, self._settings, workspace_roots=self._workspace_roots())

    def _refresh_from_service(self) -> None:
        if self._workspace_service is None:
            self._render_workspaces([])
            return
        self._is_paused = self._workspace_service.is_monitoring_paused()
        self._toggle_monitor_btn.setText("Resume monitoring" if self._is_paused else "Pause monitoring")
        self._render_workspaces(self._workspace_service.cached_workspaces())

    def _on_monitoring_paused_changed(self, paused: bool) -> None:
        self._is_paused = paused
        self._toggle_monitor_btn.setText("Resume monitoring" if paused else "Pause monitoring")
        if self._workspace_service is not None:
            self._render_workspaces(self._workspace_service.cached_workspaces())

    def _render_workspaces(self, workspaces: list[Workspace]) -> None:
        while self._workspace_list_layout.count():
            item = self._workspace_list_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not workspaces:
            empty = QLabel("No monitored workspaces yet. Click '+ Add folder' to observe a folder read-only.")
            empty.setProperty("role", "mutedBody")
            empty.setWordWrap(True)
            self._workspace_list_layout.addWidget(empty)
            return
        for idx, ws in enumerate(workspaces):
            if idx > 0:
                divider = QFrame()
                divider.setProperty("divider", True)
                self._workspace_list_layout.addWidget(divider)
            self._workspace_list_layout.addWidget(
                build_workspace_row(
                    ws,
                    is_paused=self._is_paused,
                    relink_enabled=self._relink_service is not None,
                    on_relink=self._on_relink_workspace,
                    on_remove=self._on_remove,
                )
            )

    def _on_add_folder(self) -> None:
        if self._workspace_service is None:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select workspace folder")
        if not folder:
            return
        resolved = os.path.normcase(str(Path(folder).expanduser().resolve(strict=False)))
        existing = {
            os.path.normcase(ws.root_path) for ws in self._workspace_service.cached_workspaces()
        }
        if resolved in existing:
            QtWidgets.QMessageBox.information(
                self, "Already monitored", "That folder is already registered as a monitored workspace."
            )
            return
        self._workspace_service.add_workspace_async(folder)

    def _on_remove(self, workspace_id: str) -> None:
        if self._workspace_service is not None:
            self._workspace_service.remove_workspace_async(workspace_id)

    def _on_relink_workspace(self, workspace_id: str) -> None:
        if self._relink_service is None:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select new workspace folder")
        if not folder:
            return
        try:
            count = self._relink_service.relink_workspace(workspace_id, Path(folder), background_scan=True)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Relink failed", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self, "Workspace relinked", f"Workspace relinked ({count} project(s) updated)."
        )

    def _on_toggle_monitoring(self) -> None:
        if self._workspace_service is not None:
            self._workspace_service.set_monitoring_paused_async(not self._is_paused)
