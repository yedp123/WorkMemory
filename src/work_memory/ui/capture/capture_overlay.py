"""WeChat-style 1:1 on-screen drag capture & annotation overlay dialog."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import QDialog, QWidget

from work_memory.media.screenshot import crop_from_desktop
from work_memory.ui.capture.annotation_engine import AnnotationEngine
from work_memory.ui.capture.floating_toolbar import FloatingToolbar
from work_memory.ui.capture.overlay_annotations import OverlayAnnotationSession
from work_memory.ui.capture.overlay_geometry import (
    HandleKind,
    active_screen_bounds_local,
    apply_handle_drag,
    cursor_for_handle,
    hit_test_handle,
    paint_outer_scrim,
    paint_selection_chrome,
)

logger = logging.getLogger(__name__)
OverlayState = Literal["selecting", "adjusting"]
_MIN_SELECTION_PX = 10


@dataclass(frozen=True, slots=True)
class CaptureOverlayResult:
    """Final cropped original and optional annotated ``QPixmap`` confirmed by the user."""

    original: QPixmap
    annotated: QPixmap | None = None


class CaptureOverlay(QDialog):
    """Frameless 1:1 desktop overlay supporting drag selection, resize/move, and annotation."""

    def __init__(self, frozen_pixmap: QPixmap, virtual_rect: QRect, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frozen, self._virtual_rect = frozen_pixmap, virtual_rect
        self._state: OverlayState = "selecting"
        self._engine = AnnotationEngine()
        self._capture_result: CaptureOverlayResult | None = None
        self._selection, self._dragging, self._drag_origin = QRect(), False, QPoint()
        self._drag_start_rect = QRect()
        self._active_handle: HandleKind | None = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(self._virtual_rect)

        self._toolbar = FloatingToolbar(self)
        self._toolbar.setVisible(False)
        self._toolbar.tool_selected.connect(self._on_tool_selected)
        self._toolbar.color_changed.connect(self._on_color_changed)
        self._toolbar.size_preset_changed.connect(self._on_size_preset_changed)
        self._toolbar.undo_clicked.connect(self._on_undo)
        self._toolbar.reset_clicked.connect(self._on_reset)
        self._toolbar.cancel_clicked.connect(self.reject)
        self._toolbar.confirm_clicked.connect(self._on_confirm)

        self._session = OverlayAnnotationSession(self, self._engine)
        self._text_editor = self._session.text_editor
        self._text_editor.returnPressed.connect(self._commit_text_editor)

    @property
    def capture_result(self) -> CaptureOverlayResult | None:
        """Return confirmed ``CaptureOverlayResult``, or ``None`` if cancelled."""
        return self._capture_result

    @property
    def state(self) -> OverlayState:
        """Return the current interaction state (``'selecting'`` or ``'adjusting'``)."""
        return self._state

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.setGeometry(self._virtual_rect)
        self.raise_()
        self.activateWindow()
        self.setFocus()
        logger.info("CaptureOverlay opened: rect=%s", self._virtual_rect.getRect())

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        if not self._frozen.isNull():
            painter.drawPixmap(self.rect(), self._frozen, self._frozen.rect())
        paint_outer_scrim(painter, self.rect(), self._selection)
        if self._selection.isEmpty():
            return
        painter.save()
        painter.setClipRect(self._selection)
        self._engine.paint_on(painter, QPointF(self._selection.topLeft()), preview=self._session.preview_item())
        painter.restore()
        paint_selection_chrome(
            painter, self._selection, self.rect(),
            dpr=self._frozen.devicePixelRatio() or 1.0, show_handles=(self._state == "adjusting"),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._text_editor.hide() if self._text_editor.isVisible() else self.reject()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._text_editor.isVisible():
            self._commit_text_editor()

        if self._state == "selecting":
            self._dragging, self._drag_origin = True, pos
            self._selection = QRect(pos, pos)
            self.update()
        elif self._session.active_tool is not None:
            if self._selection.contains(pos):
                self._session.begin(self._selection, pos)
        elif (handle := hit_test_handle(self._selection, pos)) is not None:
            self._dragging, self._active_handle, self._drag_origin = True, handle, pos
            self._drag_start_rect = QRect(self._selection)
            self._toolbar.setVisible(False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._state == "selecting" and self._dragging:
            self._selection = QRect(self._drag_origin, pos).normalized().intersected(self.rect())
            self.update()
        elif self._session.drawing:
            self._session.move(self._selection, pos)
            self.update()
        elif self._dragging and self._active_handle is not None:
            self._selection = apply_handle_drag(
                self._drag_start_rect, self._active_handle,
                pos - self._drag_origin, self.rect(), min_size=_MIN_SELECTION_PX,
            )
            self.update()
        else:
            self._update_hover_cursor(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._state == "selecting" and self._dragging:
            self._dragging = False
            if self._selection.width() >= _MIN_SELECTION_PX and self._selection.height() >= _MIN_SELECTION_PX:
                self._state = "adjusting"
                self._show_toolbar()
            else:
                self._selection = QRect()
            self.update()
        elif self._session.drawing:
            self._session.finish(self._selection, event.position().toPoint())
            self._toolbar.set_history_available(self._engine.has_annotations())
            self.update()
        elif self._dragging and self._active_handle is not None:
            self._dragging, self._active_handle = False, None
            self._show_toolbar()
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._state == "adjusting":
            self._on_confirm()
        elif event.key() == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._on_undo()
        else:
            super().keyPressEvent(event)

    def reject(self) -> None:
        self._capture_result = None
        logger.info("CaptureOverlay cancelled.")
        super().reject()

    def _on_tool_selected(self, tool: object) -> None:
        self._session.active_tool = tool  # type: ignore[assignment]
        self._text_editor.hide()
        if self._state == "adjusting":
            self._show_toolbar()
        self._update_hover_cursor(self.mapFromGlobal(self.cursor().pos()))

    def _on_color_changed(self, color: QColor) -> None:
        self._engine.set_color(color)
        self._session.sync_text_editor_style()

    def _on_size_preset_changed(self, preset: str) -> None:
        self._engine.set_size_preset(preset)
        self._session.sync_text_editor_style()

    def _on_undo(self) -> None:
        if self._engine.undo():
            self._toolbar.set_history_available(self._engine.has_annotations())
            self.update()

    def _on_reset(self) -> None:
        if self._engine.reset():
            self._toolbar.set_history_available(False)
            self.update()

    def _commit_text_editor(self) -> None:
        if self._session.commit_text():
            self._toolbar.set_history_available(self._engine.has_annotations())
            self.update()
        self.setFocus()

    def _on_confirm(self) -> None:
        if self._text_editor.isVisible():
            self._commit_text_editor()
        if self._selection.width() < _MIN_SELECTION_PX or self._selection.height() < _MIN_SELECTION_PX:
            self.reject()
            return
        global_sel = self._selection.translated(self._virtual_rect.topLeft())
        original = crop_from_desktop(self._frozen, self._virtual_rect, global_sel)
        if original.isNull():
            self.reject()
            return
        annotated = self._engine.render_annotated(original) if self._engine.has_annotations() else None
        self._capture_result = CaptureOverlayResult(original=original, annotated=annotated)
        logger.info("CaptureOverlay confirmed: %dx%d px (annotated=%s)", original.width(), original.height(), annotated is not None)
        self.accept()

    def _show_toolbar(self) -> None:
        bounds = active_screen_bounds_local(self._selection, self._virtual_rect, self.rect())
        self._toolbar.reposition_for_selection(self._selection, bounds)
        self._toolbar.setVisible(True)

    def _update_hover_cursor(self, pos: QPoint) -> None:
        if self._state == "selecting":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._session.active_tool is not None:
            if not self._selection.contains(pos):
                self.setCursor(Qt.CursorShape.ArrowCursor)
            elif self._session.active_tool == "text":
                self.setCursor(Qt.CursorShape.IBeamCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(cursor_for_handle(hit_test_handle(self._selection, pos)))
