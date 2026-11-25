"""Shared async read-only file resolution and OS default-app opener for views."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from work_memory.core.models import Project
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.services.file_resolver import (
    ResolvedFileResult,
    RevealTargetResult,
    resolve_relative_file,
    resolve_reveal_target,
    strip_sequence_suffix,
)
from work_memory.services.history_service import HistoryService
from work_memory.ui.file_actions import open_file_default, reveal_in_folder
from work_memory.ui.widgets.media_preview_dialog import MediaPreviewDialog
from work_memory.ui.workers import run_in_pool


def open_timeline_file_async(
    host: QWidget,
    workers: set[QObject],
    history_service: HistoryService | None,
    rel_path: str,
    project_id: str,
    workspace_id: str,
    on_missing: Callable[[str], None],
    *,
    fallback_project: Project | None = None,
) -> None:
    """Resolve ``rel_path`` off the GUI thread and open it via ``QDesktopServices.openUrl``."""

    def _resolve() -> ResolvedFileResult:
        if history_service is not None:
            return history_service.resolve_file_path(
                rel_path,
                project_id=project_id or None,
                workspace_id=workspace_id or None,
            )
        if fallback_project is not None:
            return resolve_relative_file(rel_path, project=fallback_project)
        name = PurePosixPath(strip_sequence_suffix(rel_path)).name or rel_path
        return ResolvedFileResult(found=False, resolved_path=None, display_name=name)

    def _on_done(result: object) -> None:
        if not isinstance(result, ResolvedFileResult):
            return
        if result.found and result.resolved_path is not None:
            open_file_default(result.resolved_path)
        else:
            on_missing(result.display_name)

    run_in_pool(host, workers, _resolve, _on_done)


def reveal_timeline_file_async(
    host: QWidget,
    workers: set[QObject],
    history_service: HistoryService | None,
    rel_path: str,
    project_id: str,
    workspace_id: str,
    on_feedback: Callable[[str, str], None],
    *,
    fallback_project: Project | None = None,
) -> None:
    """Resolve ``rel_path`` off the GUI thread and highlight it in Windows Explorer."""

    def _resolve() -> RevealTargetResult:
        if history_service is not None:
            return history_service.resolve_reveal_target(
                rel_path,
                project_id=project_id or None,
                workspace_id=workspace_id or None,
            )
        if fallback_project is not None:
            return resolve_reveal_target(rel_path, project=fallback_project)
        name = PurePosixPath(strip_sequence_suffix(rel_path)).name or rel_path
        return RevealTargetResult(target_path=None, root_bound=None, display_name=name)

    def _on_done(result: object) -> None:
        if not isinstance(result, RevealTargetResult) or result.target_path is None:
            on_feedback("Folder unavailable", "Folder not found on disk")
            return
        ok, status = reveal_in_folder(result.target_path, root_bound=result.root_bound)
        if status == "parent_opened":
            on_feedback(
                "File moved or deleted",
                "File no longer exists \u2014 opened containing folder",
            )
        elif not ok:
            on_feedback("Folder unavailable", "Folder not found on disk")

    run_in_pool(host, workers, _resolve, _on_done)


def preview_timeline_file_async(
    host: QWidget,
    workers: set[QObject],
    history_service: HistoryService | None,
    thumbnail_service: ThumbnailService | None,
    rel_path: str,
    project_id: str,
    workspace_id: str,
    on_missing: Callable[[str], None],
    on_feedback: Callable[[str, str], None],
    *,
    fallback_project: Project | None = None,
) -> None:
    """Resolve ``rel_path`` off the GUI thread and open ``MediaPreviewDialog``."""

    def _resolve() -> RevealTargetResult:
        if history_service is not None:
            return history_service.resolve_reveal_target(
                rel_path,
                project_id=project_id or None,
                workspace_id=workspace_id or None,
            )
        if fallback_project is not None:
            return resolve_reveal_target(rel_path, project=fallback_project)
        name = PurePosixPath(strip_sequence_suffix(rel_path)).name or rel_path
        return RevealTargetResult(target_path=None, root_bound=None, display_name=name)

    def _on_done(result: object) -> None:
        if (
            not isinstance(result, RevealTargetResult)
            or result.target_path is None
            or not result.target_path.is_file()
        ):
            name = result.display_name if isinstance(result, RevealTargetResult) else rel_path
            on_missing(name)
            return
        dlg = MediaPreviewDialog(
            result.target_path,
            thumbnail_service=thumbnail_service,
            root_bound=result.root_bound,
            parent=host,
        )
        dlg.info_toast.connect(on_feedback)
        dlg.exec()
        dlg.deleteLater()

    run_in_pool(host, workers, _resolve, _on_done)
