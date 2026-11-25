"""Extracted QuickCaptureDialog launcher helper keeping MainWindow concise."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from work_memory.core.models import Project
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.services.capture_service import CaptureService
from work_memory.services.project_service import ProjectService
from work_memory.ui.capture.capture_form import resolve_default_project_id
from work_memory.ui.capture.quick_capture_dialog import QuickCaptureDialog


def launch_or_reuse_quick_capture(
    parent: QWidget,
    existing_dialog: QuickCaptureDialog | None,
    capture_service: CaptureService,
    project_service: ProjectService | None,
    cached_projects: list[Project],
    *,
    project_id: str | None = None,
    active_detail_project_id: str | None = None,
    linked_file: str = "",
    launch_screenshot: bool = False,
    launch_voice: bool = False,
    initial_milestone: bool = False,
    sound_player: SoundEffectsPlayer | None = None,
) -> QuickCaptureDialog:
    """Reuse an open Quick Capture dialog or construct and present a fresh one."""
    if existing_dialog is not None and (
        existing_dialog.isVisible() or existing_dialog.is_capturing_screen
    ):
        if not existing_dialog.is_capturing_screen:
            if project_id:
                existing_dialog.set_project_id(project_id)
            if initial_milestone:
                existing_dialog.set_milestone_checked(True)
            existing_dialog.showNormal()
            existing_dialog.raise_()
            existing_dialog.activateWindow()
            if launch_screenshot:
                QTimer.singleShot(0, existing_dialog._on_take_screenshot)
            elif launch_voice:
                existing_dialog.open_voice_drawer()
        return existing_dialog

    if existing_dialog is not None:
        existing_dialog.deleteLater()

    projects = project_service.list_projects() if project_service is not None else cached_projects
    active_pid = resolve_default_project_id(projects, project_id or active_detail_project_id)
    dlg = QuickCaptureDialog(
        capture_service,
        projects,
        initial_project_id=active_pid or None,
        initial_linked_file=linked_file,
        initial_milestone=initial_milestone,
        sound_player=sound_player,
        parent=parent,
    )
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    if launch_screenshot:
        QTimer.singleShot(0, dlg._on_take_screenshot)
    elif launch_voice:
        dlg.open_voice_drawer()
    return dlg
