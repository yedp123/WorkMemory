"""Shared UI helpers for picking, loading, and resetting project cover images."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QPushButton, QWidget

from work_memory.core.models import Project
from work_memory.services.project_service import ProjectService
from work_memory.ui.theme import get_palette
from work_memory.ui.workers import run_in_pool

_COVER_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"


def load_cover_pixmap(cover_path: Path | None) -> QPixmap | None:
    """Load an app-owned cover image into a ``QPixmap``, or return ``None``."""
    if cover_path is None or not cover_path.is_file():
        return None
    pm = QPixmap(str(cover_path))
    return None if pm.isNull() else pm


def choose_cover_image_dialog(parent: QWidget, project_name: str) -> Path | None:
    """Prompt the user to select an image file for ``project_name``."""
    selected, _ = QFileDialog.getOpenFileName(
        parent,
        f'Choose cover image for "{project_name}"',
        "",
        _COVER_FILE_FILTER,
    )
    return Path(selected) if selected else None


def run_set_cover_async(
    host: QWidget,
    workers: set[QObject],
    project_service: ProjectService | None,
    project_id: str,
    source_path: Path,
    *,
    on_done: Callable[[object], None] | None = None,
) -> None:
    """Persist a resized copy of ``source_path`` in ``covers/`` off the GUI thread."""
    if project_service is None:
        return
    run_in_pool(
        host,
        workers,
        lambda: project_service.set_project_cover(project_id, source_path),
        on_done,
        lambda msg: QMessageBox.warning(host, "Cover image failed", msg),
    )


def run_clear_cover_async(
    host: QWidget,
    workers: set[QObject],
    project_service: ProjectService | None,
    project_id: str,
    *,
    on_done: Callable[[object], None] | None = None,
) -> None:
    """Clear a project's custom cover off the GUI thread."""
    if project_service is None:
        return
    run_in_pool(
        host,
        workers,
        lambda: project_service.clear_project_cover(project_id),
        on_done,
        lambda msg: QMessageBox.warning(host, "Reset cover failed", msg),
    )


def build_delete_card_button() -> QPushButton:
    """Create the compact delete button rendered on project thumbnail and list cards."""
    pal = get_palette()
    btn = QPushButton("\u2715")
    btn.setObjectName("projectDeleteButton")
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedSize(26, 24)
    btn.setToolTip("Delete project from Work Memory")
    btn.setStyleSheet(
        "QPushButton#projectDeleteButton { background-color: rgba(23, 25, 29, 0.65); "
        "border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 9px; "
        "color: #9ca5af; font-size: 11px; padding: 0; }"
        f"QPushButton#projectDeleteButton:hover {{ border-color: {pal.danger_border}; "
        f"color: {pal.danger_text}; background-color: rgba(23, 25, 29, 0.88); }}"
    )
    return btn


def build_card_context_menu(
    parent: QWidget,
    project: Project,
    *,
    on_change_cover: Callable[[], None],
    on_reset_cover: Callable[[], None],
    on_toggle_pin: Callable[[], None],
    on_delete_project: Callable[[], None] | None = None,
) -> QMenu:
    """Build the themed right-click menu for ``ProjectCard``."""
    pal = get_palette()
    menu = QMenu(parent)
    menu.setStyleSheet(
        f"QMenu {{ background-color: {pal.panel_alt}; color: {pal.text}; "
        f"border: 1px solid {pal.border}; border-radius: 8px; padding: 4px; }}"
        "QMenu::item { padding: 6px 14px; border-radius: 5px; font-size: 12px; }"
        f"QMenu::item:selected {{ background-color: {pal.accent_bg}; }}"
    )
    change_act = menu.addAction("Change cover...")
    change_act.triggered.connect(on_change_cover)
    if project.cover_image_path:
        reset_act = menu.addAction("Reset cover")
        reset_act.triggered.connect(on_reset_cover)
    menu.addSeparator()
    pin_act = menu.addAction("Unpin project" if project.is_pinned else "Pin project")
    pin_act.triggered.connect(on_toggle_pin)
    if on_delete_project is not None:
        menu.addSeparator()
        del_act = menu.addAction("Delete project...")
        del_act.triggered.connect(on_delete_project)
    return menu
