"""Interactive annotation stroke/text session helper for CaptureOverlay."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import QLineEdit, QWidget

from work_memory.ui.capture.annotation_engine import (
    AnnotationEngine,
    AnnotationItem,
    AnnotationTool,
)


class InlineTextInput(QLineEdit):
    """Compact dark inline editor for placing text annotations directly on screen."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self.hide()
            return
        super().keyPressEvent(event)


class OverlayAnnotationSession:
    """Tracks live drawing strokes and inline text input inside ``CaptureOverlay``."""

    def __init__(self, parent: QWidget, engine: AnnotationEngine) -> None:
        self._parent = parent
        self._engine = engine
        self.active_tool: AnnotationTool | None = None
        self.drawing = False
        self.draw_start = QPointF()
        self.draw_end = QPointF()
        self.pen_points: list[QPointF] = []
        self._text_pos = QPointF()

        self.text_editor = InlineTextInput(parent)
        self.text_editor.setPlaceholderText("Type note, Enter")
        self.text_editor.setVisible(False)
        self.sync_text_editor_style()

    def sync_text_editor_style(self) -> None:
        """Apply current active swatch color and font size to ``text_editor``."""
        color_hex = self._engine.active_color.name()
        font_pt = self._engine.active_font_size
        font = QFont("Segoe UI", font_pt, QFont.Weight.Bold)
        self.text_editor.setFont(font)
        self.text_editor.setStyleSheet(
            f"QLineEdit {{ background: #17191d; color: {color_hex}; border: 2px solid #6ec494; "
            f"border-radius: 5px; padding: 3px 7px; font-weight: 700; }}"
        )
        if self.text_editor.isVisible():
            h = max(32, font_pt + 18)
            self.text_editor.resize(max(180, font_pt * 10), h)

    @staticmethod
    def to_selection_rel(selection: QRect, pos: QPoint) -> QPointF:
        """Clamp ``pos`` inside ``selection`` and convert to selection-relative coords."""
        cx = max(selection.left(), min(pos.x(), selection.right()))
        cy = max(selection.top(), min(pos.y(), selection.bottom()))
        return QPointF(cx - selection.left(), cy - selection.top())

    def begin(self, selection: QRect, pos: QPoint) -> None:
        """Start a shape/pen stroke or open the inline text input at ``pos``."""
        rel = self.to_selection_rel(selection, pos)
        if self.active_tool == "text":
            self._text_pos = rel
            self.sync_text_editor_style()
            w = max(180, self._engine.active_font_size * 10)
            h = max(32, self._engine.active_font_size + 18)
            x = max(selection.left(), min(pos.x(), max(selection.left(), selection.right() - w + 1)))
            y = max(selection.top(), min(pos.y() - h // 2, max(selection.top(), selection.bottom() - h + 1)))
            self.text_editor.setGeometry(x, y, min(w, max(80, selection.width())), min(h, max(28, selection.height())))
            self.text_editor.clear()
            self.text_editor.setVisible(True)
            self.text_editor.setFocus()
            return
        self.drawing = True
        self.draw_start = self.draw_end = rel
        self.pen_points = [rel] if self.active_tool == "pen" else []

    def move(self, selection: QRect, pos: QPoint) -> None:
        """Update the live stroke endpoint while dragging."""
        rel = self.to_selection_rel(selection, pos)
        self.draw_end = rel
        if self.active_tool == "pen":
            self.pen_points.append(rel)

    def finish(self, selection: QRect, pos: QPoint) -> None:
        """Commit the active shape or pen stroke to ``AnnotationEngine``."""
        self.drawing = False
        self.draw_end = self.to_selection_rel(selection, pos)
        if self.active_tool == "pen":
            self._engine.add_pen_stroke(self.pen_points)
            self.pen_points.clear()
        elif self.active_tool in ("rect", "circle", "arrow") and (
            (self.draw_end - self.draw_start).manhattanLength() >= 4.0
        ):
            self._engine.add_shape(self.active_tool, self.draw_start, self.draw_end)

    def commit_text(self) -> bool:
        """Commit text from ``text_editor`` into ``AnnotationEngine`` and hide it."""
        text = self.text_editor.text().strip()
        self.text_editor.hide()
        if text:
            return self._engine.add_text(self._text_pos, text) is not None
        return False

    def preview_item(self) -> AnnotationItem | None:
        """Return an ephemeral ``AnnotationItem`` for live drag rendering."""
        if not self.drawing or self.active_tool is None or self.active_tool == "text":
            return None
        return AnnotationItem(
            tool=self.active_tool,
            start=self.draw_start,
            end=self.draw_end,
            points=tuple(self.pen_points),
            color=self._engine.active_color,
            thickness=self._engine.active_thickness,
            font_size=self._engine.active_font_size,
        )
