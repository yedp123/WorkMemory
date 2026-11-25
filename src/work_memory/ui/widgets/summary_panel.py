"""Calm dark Last Known State & Recent Activity Summary widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import ProjectSummaryView, SummaryReference
from work_memory.ui.theme import get_palette


def _chip_button(ref: SummaryReference, on_click: object) -> QPushButton:
    pal = get_palette()
    btn = QPushButton(ref.label)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setStyleSheet(
        f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.accent}; border: 1px solid {pal.border}; "
        "border-radius: 7px; padding: 4px 10px; font-size: 11px; }"
        f"QPushButton:hover {{ border-color: {pal.accent}; color: {pal.text}; }}"
    )
    btn.clicked.connect(lambda: on_click(ref))  # type: ignore[operator]
    return btn


class SummaryPanel(QFrame):
    """Displays Confirmed/Inferred Last Known State, custom edits, and clickable references."""

    reference_clicked = Signal(object)
    save_custom_requested = Signal(str)
    regenerate_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lksPanel")
        self._current_view: ProjectSummaryView | None = None
        self._editing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)
        root.addLayout(self._build_header())

        self._display_box = QWidget()
        disp = QVBoxLayout(self._display_box)
        disp.setContentsMargins(0, 0, 0, 0)
        disp.setSpacing(6)

        self._edited_badge = QLabel("Edited by you")
        self._edited_badge.setObjectName("summaryEditedBadge")
        self._edited_badge.setVisible(False)

        self._custom_label = QLabel()
        self._custom_label.setObjectName("summaryCustomText")
        self._custom_label.setWordWrap(True)
        self._custom_label.setVisible(False)

        self._confirmed_row, self._confirmed_tag, self._confirmed_text = self._make_tagged_row("Confirmed:")
        self._inferred_row, self._inferred_tag, self._inferred_text = self._make_tagged_row("Inferred:")

        self._recent_label = QLabel("No recent sessions recorded yet.")
        self._recent_label.setObjectName("summaryRecentLabel")
        self._recent_label.setWordWrap(True)

        self._refs_row = QHBoxLayout()
        self._refs_row.setContentsMargins(0, 4, 0, 0)
        self._refs_row.setSpacing(8)
        self._refs_container = QWidget()
        self._refs_container.setLayout(self._refs_row)
        self._refs_container.setVisible(False)

        for widget in (
            self._edited_badge,
            self._custom_label,
            self._confirmed_row,
            self._inferred_row,
            self._recent_label,
            self._refs_container,
        ):
            disp.addWidget(widget)

        self._edit_box = self._build_edit_box()
        self._edit_box.setVisible(False)

        root.addWidget(self._display_box)
        root.addWidget(self._edit_box)
        self.refresh_theme()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        title = QLabel("Last known state")
        title.setProperty("role", "sectionTitle")
        row.addWidget(title, 1)

        self._regen_btn = QPushButton("Regenerate")
        self._regen_btn.setObjectName("summaryRegenerateButton")
        self._regen_btn.setProperty("textButton", True)
        self._regen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._regen_btn.clicked.connect(self.regenerate_requested.emit)

        self._edit_btn = QPushButton("Edit summary")
        self._edit_btn.setObjectName("summaryEditButton")
        self._edit_btn.setProperty("textButton", True)
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(lambda: self._set_edit_mode(True))

        row.addWidget(self._regen_btn)
        row.addWidget(self._edit_btn)
        return row

    def _make_tagged_row(self, tag_text: str) -> tuple[QWidget, QLabel, QLabel]:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        tag = QLabel(tag_text)
        tag.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        body = QLabel()
        body.setWordWrap(True)
        row.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(body, 1)
        return row_widget, tag, body

    def _build_edit_box(self) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(8)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("summaryEditor")
        self._editor.setFixedHeight(88)
        col.addWidget(self._editor)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("summaryCancelButton")
        self._cancel_btn.setProperty("secondary", True)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.clicked.connect(lambda: self._set_edit_mode(False))

        self._save_btn = QPushButton("Save summary")
        self._save_btn.setObjectName("summarySaveButton")
        self._save_btn.setProperty("primary", True)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save_clicked)

        btns.addWidget(self._cancel_btn)
        btns.addWidget(self._save_btn)
        col.addLayout(btns)
        return box

    def refresh_theme(self) -> None:
        """Re-apply active theme colors across labels and reference chips."""
        pal = get_palette()
        self._edited_badge.setStyleSheet(f"color: {pal.accent}; font-size: 11px; font-weight: 600;")
        self._custom_label.setStyleSheet(f"color: {pal.soft}; font-size: 13px;")
        self._confirmed_tag.setStyleSheet(f"color: {pal.green}; font-size: 12px; font-weight: 600;")
        self._confirmed_text.setStyleSheet(f"color: {pal.soft}; font-size: 13px;")
        self._inferred_tag.setStyleSheet(f"color: {pal.amber}; font-size: 12px; font-weight: 600;")
        self._inferred_text.setStyleSheet(f"color: {pal.soft}; font-size: 13px;")
        self._recent_label.setStyleSheet(f"color: {pal.muted}; font-size: 12px; padding-top: 2px;")
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {pal.input_bg}; color: {pal.text}; border: 1px solid {pal.border}; "
            "border-radius: 8px; padding: 8px 10px; font-size: 13px; }}"
        )
        if self._current_view is not None:
            self._render_references(self._current_view.references)

    def set_summary(self, view: ProjectSummaryView | None) -> None:
        """Render ``view`` or reset to a quiet placeholder when ``view`` is ``None``."""
        self._current_view = view
        self._set_edit_mode(False)
        if view is None:
            self._edited_badge.setVisible(False)
            self._custom_label.setVisible(False)
            self._confirmed_row.setVisible(False)
            self._inferred_text.setText("Loading project summary...")
            self._inferred_row.setVisible(True)
            self._recent_label.setVisible(False)
            self._render_references([])
            return

        has_custom = bool(view.custom_text and view.custom_text.strip())
        self._edited_badge.setVisible(has_custom)
        self._custom_label.setVisible(has_custom)
        if has_custom and view.custom_text is not None:
            self._custom_label.setText(view.custom_text.strip())

        has_confirmed = not has_custom and bool(view.confirmed_text.strip())
        self._confirmed_row.setVisible(has_confirmed)
        if has_confirmed:
            self._confirmed_text.setText(view.confirmed_text.strip())

        has_inferred = not has_custom and bool(view.inferred_text.strip())
        self._inferred_row.setVisible(has_inferred)
        if has_inferred:
            self._inferred_text.setText(view.inferred_text.strip())

        self._recent_label.setText(f"Recent activity: {view.recent_summary}")
        self._recent_label.setVisible(bool(view.recent_summary.strip()))
        self._render_references(view.references)

    def _render_references(self, references: list[SummaryReference]) -> None:
        while self._refs_row.count():
            if (item := self._refs_row.takeAt(0)) is not None and (w := item.widget()) is not None:
                w.deleteLater()
        if not references:
            self._refs_container.setVisible(False)
            return
        for ref in references[:3]:
            self._refs_row.addWidget(_chip_button(ref, self.reference_clicked.emit))
        self._refs_row.addStretch(1)
        self._refs_container.setVisible(True)

    def _set_edit_mode(self, editing: bool) -> None:
        self._editing = editing
        self._display_box.setVisible(not editing)
        self._edit_box.setVisible(editing)
        self._edit_btn.setVisible(not editing)
        self._regen_btn.setVisible(not editing)
        if editing:
            self._editor.setPlainText(self._current_plain_text())
            self._editor.setFocus()

    def _current_plain_text(self) -> str:
        if self._current_view is None:
            return ""
        if self._current_view.custom_text and self._current_view.custom_text.strip():
            return self._current_view.custom_text.strip()
        parts = [
            p
            for p in (self._current_view.confirmed_text.strip(), self._current_view.inferred_text.strip())
            if p
        ]
        return " ".join(parts)

    def _on_save_clicked(self) -> None:
        text = self._editor.toPlainText().strip()
        self._set_edit_mode(False)
        self.save_custom_requested.emit(text)
