"""Calm dark MilestonesPanel widget surfaced near the top of ProjectDetailView."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from work_memory.core.models import MilestoneItem
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.timeline_rows import format_ymd

_EMPTY_TEXT = "No milestones starred yet. Star any activity or note below to highlight it here."


class _ClickableMilestoneRow(QFrame):
    """Hoverable milestone row that emits ``clicked`` without intercepting the unstar button."""

    clicked = Signal(str, str)

    def __init__(self, item_type: str, item_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item_type, self._item_id = item_type, item_id
        self.setObjectName("milestoneRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        pal = get_palette()
        self.setStyleSheet(
            "QFrame#milestoneRow { background: transparent; border-radius: 6px; }"
            f"QFrame#milestoneRow:hover {{ background-color: {pal.panel_alt}; }}"
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self._item_type, self._item_id)
        super().mouseReleaseEvent(event)


class MilestonesPanel(QFrame):
    """Displays starred project milestones with date, label, category tag, and unstar action."""

    unstar_requested = Signal(str, str)
    milestone_clicked = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[MilestoneItem] = []
        self.setObjectName("milestonesPanel")
        self.setProperty("surface", True)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self._title = QLabel("Milestones")
        self._title.setProperty("role", "sectionTitle")
        self._count_lbl = QLabel("")
        head.addWidget(self._title)
        head.addWidget(self._count_lbl)
        head.addStretch(1)
        root.addLayout(head)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        root.addLayout(self._rows_layout)
        self.refresh_theme()
        self.set_milestones([])

    def refresh_theme(self) -> None:
        """Re-apply active theme colors and re-render milestone rows."""
        pal = get_palette()
        self.setStyleSheet(
            f"QFrame#milestonesPanel {{ background-color: {pal.panel}; border: 1px solid {pal.border}; "
            f"border-left: 3px solid {pal.amber}; border-radius: 13px; }}"
        )
        self._count_lbl.setStyleSheet(f"color: {pal.muted}; font-size: 11px;")
        if self._rows_layout.count():
            self.set_milestones(self._items)

    def set_milestones(self, items: list[MilestoneItem]) -> None:
        """Render ``items`` or a compact single-line empty state."""
        self._items = list(items)
        pal = get_palette()
        while self._rows_layout.count():
            if (child := self._rows_layout.takeAt(0)) is not None and (w := child.widget()) is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        self._count_lbl.setText(f"\u00b7 {len(items)}" if items else "")
        if not items:
            empty = QLabel(_EMPTY_TEXT)
            empty.setObjectName("milestonesEmptyLabel")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {pal.muted}; font-size: 12px;")
            self._rows_layout.addWidget(empty)
            return

        for idx, item in enumerate(items):
            if idx > 0:
                sep = QFrame()
                sep.setStyleSheet(f"background-color: {pal.border_soft}; min-height: 1px; max-height: 1px;")
                self._rows_layout.addWidget(sep)
            self._rows_layout.addWidget(self._build_row(item))

    def _build_row(self, item: MilestoneItem) -> QWidget:
        pal = get_palette()
        row_w = _ClickableMilestoneRow(item.item_type, item.item_id)
        row_w.clicked.connect(self.milestone_clicked.emit)
        row = QHBoxLayout(row_w)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(10)

        date_lbl = QLabel(format_ymd(item.timestamp_utc))
        date_lbl.setStyleSheet(f"color: {pal.muted}; font-size: 11px;")
        date_lbl.setFixedWidth(78)

        tag_text = "File" if item.item_type == "observed" else "Note"
        tag = QLabel(tag_text)
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet(
            f"background-color: {pal.panel_alt}; color: {pal.soft}; border: 1px solid {pal.border}; "
            "border-radius: 6px; padding: 1px 7px; font-size: 10px;"
        )

        title_lbl = QLabel(item.title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"color: {pal.body_text}; font-size: 12px;")
        title_lbl.setToolTip(item.detail)

        unstar_btn = QPushButton("\u2605")
        unstar_btn.setObjectName("milestoneUnstarButton")
        unstar_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        unstar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        unstar_btn.setToolTip("Remove from milestones")
        unstar_btn.setFixedSize(26, 24)
        unstar_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {pal.amber}; font-size: 14px; padding: 0; }}"
            f"QPushButton:hover {{ color: {pal.text}; }}"
        )
        unstar_btn.clicked.connect(
            lambda _c=False, t=item.item_type, i=item.item_id: self.unstar_requested.emit(t, i)
        )

        row.addWidget(date_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(title_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(unstar_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return row_w
