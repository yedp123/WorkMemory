"""Hero banner and Last Known State panel used by ProjectDetailView."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import CaptureEntry, Project
from work_memory.services.relink_service import is_project_folder_missing
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.project_card import CoverBanner, status_display
from work_memory.ui.widgets.timeline_rows import format_hhmm, format_ymd


def make_label(
    text: str = "", *, role: str | None = None, style: str | None = None, wrap: bool = False
) -> QLabel:
    """Create a styled ``QLabel`` with optional role property and word-wrap."""
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    if style:
        label.setStyleSheet(style)
    if wrap:
        label.setWordWrap(True)
    return label


def make_button(
    text: str, obj_name: str, slot: object, *, prop: str = "secondary"
) -> QPushButton:
    """Create a themed cursor-pointer ``QPushButton`` connected to ``slot``."""
    button = QPushButton(text)
    button.setObjectName(obj_name)
    button.setProperty(prop, True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(slot)  # type: ignore[arg-type]
    return button


def make_surface_card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Create a dark rounded surface card with standard padding and optional title."""
    card = QFrame()
    card.setProperty("surface", True)
    inner = QVBoxLayout(card)
    inner.setContentsMargins(20, 18, 20, 18)
    inner.setSpacing(10)
    if title:
        inner.addWidget(make_label(title, role="sectionTitle"))
    return card, inner


class ProjectHeroSection:
    """Builds and updates the cover, metadata, actions, and LKS header for ProjectDetailView."""

    def __init__(
        self,
        on_capture_note: object,
        on_toggle_status: object,
        on_open_folder: object,
        on_relink_folder: object = None,
        on_export_bundle: object = None,
        on_change_cover: object = None,
        on_reset_cover: object = None,
    ) -> None:
        self.hero_layout = QHBoxLayout()
        self.hero_layout.setSpacing(28)

        self.cover = CoverBanner("c1", corner_label="PROJECT", radius=13)
        self.cover.setFixedSize(310, 210)
        self.hero_layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)

        pal = get_palette()
        info = QVBoxLayout()
        info.setSpacing(10)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.title_label = make_label(
            "Project", style=f"font-size: 30px; font-weight: 600; color: {pal.text};", wrap=True
        )
        self.missing_pill = make_label(
            "Folder missing",
            style=(
                f"background-color: {pal.panel_alt}; color: {pal.amber}; border: 1px solid {pal.border}; "
                "border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 600;"
            ),
        )
        self.missing_pill.setObjectName("detailFolderMissingPill")
        self.missing_pill.setVisible(False)
        self.relink_btn = make_button(
            "Relink folder", "relinkFolderButton", on_relink_folder or (lambda: None)
        )
        self.relink_btn.setStyleSheet(
            f"QPushButton#relinkFolderButton {{ background-color: {pal.panel_alt}; color: {pal.accent}; "
            f"border: 1px solid {pal.border}; border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton#relinkFolderButton:hover {{ border-color: {pal.accent}; color: {pal.text}; }}"
        )
        self.relink_btn.setVisible(False)
        title_row.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.missing_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.relink_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        self.desc_label = make_label(role="mutedBody", wrap=True)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(7, 7)
        self.status_label = make_label(
            "Ongoing", style=f"font-size: 12px; color: {pal.amber}; font-weight: 600;"
        )
        self.path_label = make_label(
            style=f"font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; color: {pal.muted};",
            wrap=True,
        )
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._meta_dot = make_label("\u00b7", style=f"color: {pal.muted};")
        for widget in (
            self.status_dot,
            self.status_label,
            self._meta_dot,
        ):
            meta.addWidget(widget)
        meta.addWidget(self.path_label, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        self.capture_note_btn = make_button(
            "+ Capture note", "detailCaptureButton", on_capture_note, prop="primary"
        )
        self.toggle_status_btn = make_button(
            "Mark completed", "toggleProjectStatusButton", on_toggle_status
        )
        self.open_folder_btn = make_button(
            "\u2197 Open folder", "openFolderButton", on_open_folder
        )
        self.export_btn = make_button(
            "Export .wmem", "exportWmemButton", on_export_bundle or (lambda: None)
        )
        self.change_cover_btn = make_button(
            "Change cover", "changeCoverButton", on_change_cover or (lambda: None)
        )
        self.reset_cover_btn = make_button(
            "Reset cover", "resetCoverButton", on_reset_cover or (lambda: None)
        )
        self.reset_cover_btn.setVisible(False)
        actions.addWidget(self.capture_note_btn)
        actions.addWidget(self.toggle_status_btn)
        actions.addWidget(self.open_folder_btn)
        actions.addWidget(self.export_btn)
        actions.addWidget(self.change_cover_btn)
        actions.addWidget(self.reset_cover_btn)
        actions.addStretch(1)

        info.addLayout(title_row)
        info.addWidget(self.desc_label)
        info.addLayout(meta)
        info.addLayout(actions)
        info.addStretch(1)
        self.hero_layout.addLayout(info, 1)

    def render(self, project: Project, *, cover_pixmap: QPixmap | None = None) -> None:
        """Populate hero metadata widgets from ``project``."""
        pal = get_palette()
        self.title_label.setStyleSheet(f"font-size: 30px; font-weight: 600; color: {pal.text};")
        self.path_label.setStyleSheet(
            f"font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; color: {pal.muted};"
        )
        self._meta_dot.setStyleSheet(f"color: {pal.muted};")
        corner = Path(project.rel_path).parts[0] if project.rel_path else "PROJECT"
        self.cover.set_cover(project.cover_style, corner_label=corner)
        self.cover.set_pixmap(cover_pixmap)
        self.reset_cover_btn.setVisible(bool(project.cover_image_path))
        self.title_label.setText(project.name)
        self.desc_label.setText(project.description.strip() or "No description added yet.")
        self.path_label.setText(project.abs_path or project.rel_path)

        status_text, status_color = status_display(project.status)
        self.status_dot.setStyleSheet(f"background-color: {status_color}; border-radius: 3px;")
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {status_color}; font-weight: 600;"
        )
        self.toggle_status_btn.setText(
            "Reopen ongoing" if project.status == "completed" else "Mark completed"
        )
        missing = is_project_folder_missing(project)
        self.missing_pill.setVisible(missing)
        self.relink_btn.setVisible(missing)


def render_project_notes_list(layout: QVBoxLayout, notes: Sequence[CaptureEntry]) -> None:
    """Populate the compact recent-notes sidebar card."""
    while layout.count():
        if (item := layout.takeAt(0)) is not None and (w := item.widget()) is not None:
            w.deleteLater()
    if not notes:
        layout.addWidget(make_label("No notes recorded yet.", role="mutedBody", wrap=True))
        return
    pal = get_palette()
    for idx, cap in enumerate(notes[:10]):
        if idx > 0:
            sep = QWidget()
            sep.setStyleSheet(f"background-color: {pal.border_soft}; min-height: 1px; max-height: 1px;")
            layout.addWidget(sep)
        txt = cap.note_text.strip() or cap.transcript_text.strip() or "(Image / screenshot capture)"
        meta = f"{format_ymd(cap.captured_at_utc)} at {format_hhmm(cap.captured_at_utc)}"
        if cap.rel_path:
            meta = f"{meta} \u00b7 {cap.rel_path}"
        layout.addWidget(make_label(txt, style=f"font-size: 12px; color: {pal.body_text};", wrap=True))
        layout.addWidget(make_label(meta, style=f"font-size: 11px; color: {pal.muted};", wrap=True))


def relink_project_with_dialog(parent: QWidget, relink_svc: object, project: Project | None) -> Project | None:
    """Prompt for a replacement project folder and relink without touching disk files."""
    if relink_svc is None or project is None:
        return None
    folder = QFileDialog.getExistingDirectory(parent, f'Relink folder for "{project.name}"')
    if not folder:
        return None
    try:
        return relink_svc.relink_project(project.id, Path(folder))  # type: ignore[attr-defined]
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, "Relink failed", str(exc))
        return None


def export_project_with_dialog(parent: QWidget, manifest_svc: object, project: Project | None) -> None:
    """Prompt for an external ``.wmem`` destination and export the project bundle."""
    if manifest_svc is None or project is None:
        return
    default_name = f"{project.name.replace(' ', '_')}.wmem"
    dest, _ = QFileDialog.getSaveFileName(parent, "Export project memory (.wmem)", default_name, "Work Memory Bundle (*.wmem)")
    if not dest:
        return
    try:
        saved = manifest_svc.export_project_bundle(project.id, Path(dest))  # type: ignore[attr-defined]
    except (OSError, PermissionError, ValueError) as exc:
        QMessageBox.warning(parent, "Export failed", str(exc))
        return
    QMessageBox.information(parent, "Export complete", f"Project memory exported to:\n{saved}")


def build_detail_split_cards(
    timeline_widget: QWidget,
    calendar_widget: QWidget,
    on_clear_date: object,
    on_schedule_event: object,
    on_capture_requested: object,
) -> tuple[QHBoxLayout, QLabel, QPushButton, QVBoxLayout]:
    """Build the lower 3:2 activity-timeline / calendar+notes split layout."""
    split = QHBoxLayout()
    split.setSpacing(24)
    activity_card, act_layout = make_surface_card()
    head_row = QHBoxLayout()
    timeline_title = make_label("Recent activity & notes", role="sectionTitle")
    clear_date_btn = make_button("Show all recent", "clearDetailDateButton", on_clear_date, prop="textButton")
    clear_date_btn.setVisible(False)
    head_row.addWidget(timeline_title, 1)
    head_row.addWidget(clear_date_btn, 0, Qt.AlignmentFlag.AlignRight)
    act_layout.addLayout(head_row)
    act_layout.addWidget(timeline_widget)
    act_layout.addStretch(1)

    side = QVBoxLayout()
    side.setSpacing(20)
    cal_card, cal_layout = make_surface_card()
    cal_head = QHBoxLayout()
    cal_head.addWidget(make_label("Project calendar", role="sectionTitle"), 1)
    cal_head.addWidget(make_button("+ Event", "detailAddEventButton", on_schedule_event, prop="textButton"))
    cal_layout.addLayout(cal_head)
    cal_layout.addWidget(calendar_widget)

    notes_card, notes_layout = make_surface_card()
    notes_head = QHBoxLayout()
    notes_head.addWidget(make_label("Project notes", role="sectionTitle"), 1)
    notes_head.addWidget(make_button("+ Add", "detailAddNoteButton", on_capture_requested, prop="textButton"))
    notes_layout.addLayout(notes_head)
    notes_list_layout = QVBoxLayout()
    notes_list_layout.setContentsMargins(0, 0, 0, 0)
    notes_list_layout.setSpacing(6)
    notes_layout.addLayout(notes_list_layout)
    notes_layout.addStretch(1)

    side.addWidget(cal_card)
    side.addWidget(notes_card)
    side.addStretch(1)
    split.addWidget(activity_card, 3)
    split.addLayout(side, 2)
    return split, timeline_title, clear_date_btn, notes_list_layout
