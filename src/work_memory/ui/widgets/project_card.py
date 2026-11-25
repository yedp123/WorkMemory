"""Reusable calm dark project card supporting grid (S/M/L) and compact list modes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QEnterEvent, QFontMetrics, QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from work_memory.config.settings import normalize_gallery_view_mode
from work_memory.core.models import Project
from work_memory.services.history_service import parse_utc_to_local
from work_memory.services.relink_service import is_project_folder_missing
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.cover_actions import build_card_context_menu, build_delete_card_button
from work_memory.ui.widgets.cover_banner import (
    STATUS_COMPLETED_COLOR,
    STATUS_ONGOING_COLOR,
    CoverBanner,
    build_pin_button,
    build_status_badge,
    format_activity_date,
    status_display,
)
from work_memory.ui.widgets.gallery_controls import GRID_CARD_SIZES

__all__ = [
    "STATUS_COMPLETED_COLOR",
    "STATUS_ONGOING_COLOR",
    "CoverBanner",
    "ProjectCard",
    "format_activity_date",
    "status_display",
]

class ProjectCard(QFrame):
    """Calm dark project card displaying cover, title, summary, and status in grid or list mode."""

    clicked = Signal(str)
    pin_toggled = Signal(str)
    relink_requested = Signal(str)
    change_cover_requested = Signal(str)
    reset_cover_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(
        self,
        project: Project,
        parent: QWidget | None = None,
        *,
        view_mode: str = "medium",
        cover_pixmap: QPixmap | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._view_mode = normalize_gallery_view_mode(view_mode)
        self.setObjectName("projectCard")
        self.setProperty("viewMode", self._view_mode)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._raw_title = project.name
        self._raw_desc = project.description.strip() or project.rel_path or project.abs_path
        self._relink_btn: QPushButton | None = None

        if self._view_mode == "list":
            self._build_list_layout(project)
        else:
            self._build_grid_layout(project)
        if cover_pixmap is not None and not cover_pixmap.isNull():
            self._cover.set_pixmap(cover_pixmap)

    def _build_grid_layout(self, project: Project) -> None:
        card_w, cover_h = GRID_CARD_SIZES[self._view_mode]
        self.setFixedWidth(card_w)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        label_text = Path(project.rel_path).parts[0] if project.rel_path else "PROJECT"
        self._cover = CoverBanner(project.cover_style, corner_label=label_text, radius=12)
        self._cover.setFixedSize(card_w, cover_h)

        cover_layout = QVBoxLayout(self._cover)
        cover_layout.setContentsMargins(10, 10, 10, 10)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        self._pin_btn = build_pin_button(project.is_pinned)
        self._pin_btn.clicked.connect(lambda _c=False: self.pin_toggled.emit(self._project.id))
        self._delete_btn = build_delete_card_button()
        self._delete_btn.clicked.connect(lambda _c=False: self.delete_requested.emit(self._project.id))
        self._status_badge, self._status_label = build_status_badge(project.status)
        top_row.addWidget(self._pin_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        top_row.addWidget(self._delete_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        top_row.addStretch(1)
        top_row.addWidget(
            self._status_badge, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        cover_layout.addLayout(top_row)
        cover_layout.addStretch(1)
        layout.addWidget(self._cover)

        self._info_widget = self._build_info_widget(
            project,
            margins=(2, 10 if self._view_mode == "small" else 12, 2, 0),
            title_size=14 if self._view_mode == "small" else 16,
        )
        layout.addWidget(self._info_widget)

    def _build_list_layout(self, project: Project) -> None:
        pal = get_palette()
        self.setStyleSheet(
            f"QFrame#projectCard[viewMode=\"list\"] {{ background-color: {pal.panel}; "
            f"border: 1px solid {pal.border}; border-radius: 11px; }}"
            f"QFrame#projectCard[viewMode=\"list\"]:hover {{ border-color: {pal.hover_border}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 14, 10)
        row.setSpacing(14)

        self._cover = CoverBanner(project.cover_style, corner_label="", radius=8)
        self._cover.setFixedSize(96, 60)
        row.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignVCenter)

        self._info_widget = self._build_info_widget(project, margins=(0, 0, 0, 0), title_size=15)
        row.addWidget(self._info_widget, 1, Qt.AlignmentFlag.AlignVCenter)

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        self._status_badge, self._status_label = build_status_badge(project.status)
        self._pin_btn = build_pin_button(project.is_pinned)
        self._pin_btn.clicked.connect(lambda _c=False: self.pin_toggled.emit(self._project.id))
        self._delete_btn = build_delete_card_button()
        self._delete_btn.clicked.connect(lambda _c=False: self.delete_requested.emit(self._project.id))
        right.addWidget(self._status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self._pin_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self._delete_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(right, 0)

    def _build_info_widget(
        self, project: Project, *, margins: tuple[int, int, int, int], title_size: int
    ) -> QWidget:
        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent; border: none;")
        info = QVBoxLayout(info_widget)
        info.setContentsMargins(*margins)
        info.setSpacing(3)

        pal = get_palette()
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._title_label = QLabel(project.name)
        self._title_label.setStyleSheet(
            f"font-size: {title_size}px; font-weight: 600; color: {pal.text}; border: none;"
        )
        self._title_label.setToolTip(project.name)
        title_row.addWidget(self._title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        if is_project_folder_missing(project):
            missing_pill = QLabel("Folder missing")
            missing_pill.setObjectName("cardFolderMissingPill")
            missing_pill.setStyleSheet(
                f"background-color: {pal.panel_alt}; color: {pal.amber}; border: 1px solid {pal.border}; "
                "border-radius: 6px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
            )
            relink_btn = QPushButton("Relink")
            relink_btn.setObjectName("cardRelinkButton")
            relink_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            relink_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            relink_btn.setToolTip("Locate moved project folder")
            relink_btn.setStyleSheet(
                f"QPushButton#cardRelinkButton {{ background-color: {pal.panel_alt}; color: {pal.accent}; "
                f"border: 1px solid {pal.border}; border-radius: 6px; padding: 1px 7px; font-size: 10px; font-weight: 600; }}"
                f"QPushButton#cardRelinkButton:hover {{ border-color: {pal.accent}; color: {pal.text}; }}"
            )
            relink_btn.clicked.connect(lambda _c=False: self.relink_requested.emit(self._project.id))
            self._relink_btn = relink_btn
            title_row.addWidget(missing_pill, 0, Qt.AlignmentFlag.AlignVCenter)
            title_row.addWidget(relink_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        info.addLayout(title_row)

        self._desc_label = QLabel(self._raw_desc)
        self._desc_label.setStyleSheet(f"font-size: 12px; color: {pal.muted}; border: none;")
        self._desc_label.setToolTip(self._raw_desc)
        info.addWidget(self._desc_label)

        meta_margin = 2 if self._view_mode == "list" else 5
        created_local = parse_utc_to_local(project.created_at_utc).strftime("%m/%d/%Y")
        act_text = format_activity_date(project.last_activity_utc)
        meta_label = QLabel(f"Created {created_local} \u00b7 {act_text}")
        meta_label.setToolTip(f"Created {created_local} \u00b7 Last activity: {act_text}")
        meta_label.setStyleSheet(
            f"font-size: 11px; color: {pal.muted}; margin-top: {meta_margin}px; border: none;"
        )
        info.addWidget(meta_label)
        return info_widget

    @property
    def project_id(self) -> str:
        """Return the project identifier represented by this card."""
        return self._project.id

    @property
    def view_mode(self) -> str:
        """Return the active display mode (``list``, ``small``, ``medium``, or ``large``)."""
        return self._view_mode

    def resizeEvent(self, event: QEvent) -> None:
        """Keep card text cleanly elided to available width."""
        super().resizeEvent(event)  # type: ignore[arg-type]

        avail = self._info_widget.width()
        if avail <= 0:
            avail = max(80, self.width() - (240 if self._view_mode == "list" else 12))
        title_budget = max(80, avail - (164 if self._relink_btn is not None else 8))
        self._title_label.setText(
            QFontMetrics(self._title_label.font()).elidedText(
                self._raw_title, Qt.TextElideMode.ElideRight, title_budget
            )
        )
        self._desc_label.setText(
            QFontMetrics(self._desc_label.font()).elidedText(
                self._raw_desc, Qt.TextElideMode.ElideRight, max(80, avail - 8)
            )
        )

    def enterEvent(self, event: QEnterEvent) -> None:
        self._cover.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._cover.set_hovered(False)
        super().leaveEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = build_card_context_menu(
            self,
            self._project,
            on_change_cover=lambda: self.change_cover_requested.emit(self._project.id),
            on_reset_cover=lambda: self.reset_cover_requested.emit(self._project.id),
            on_toggle_pin=lambda: self.pin_toggled.emit(self._project.id),
            on_delete_project=lambda: self.delete_requested.emit(self._project.id),
        )
        menu.exec(event.globalPos())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
            and not self._pin_btn.underMouse()
            and not self._delete_btn.underMouse()
            and not (self._relink_btn is not None and self._relink_btn.underMouse())
        ):
            self.clicked.emit(self._project.id)
        super().mouseReleaseEvent(event)
