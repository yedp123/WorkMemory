"""Interactive dark screenshot annotation canvas preserving the original QPixmap."""

from __future__ import annotations

import math
from typing import Literal

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QInputDialog, QWidget

from work_memory.ui.theme import ACCENT, AMBER, BORDER

AnnotatorTool = Literal["pen", "arrow", "rect", "circle", "text", "crop"]


class AnnotatorCanvas(QWidget):
    """Canvas supporting Pen, Arrow, Rect, Circle, Text, Crop, Undo, and Reset."""

    annotation_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._original = QPixmap()
        self._history: list[QPixmap] = []
        self._tool: AnnotatorTool = "pen"
        self._stroke_color = QColor("#e07a7a")
        self._text_color = QColor(AMBER)
        self._drawing = False
        self._start_pt = QPointF()
        self._current_pt = QPointF()
        self._pen_points: list[QPointF] = []

        self.setMinimumSize(420, 210)
        self.setCursor(Qt.CursorShape.CrossCursor)

    @property
    def current_tool(self) -> AnnotatorTool:
        """Return the active annotation tool."""
        return self._tool

    def set_tool(self, tool: AnnotatorTool) -> None:
        """Select the active annotation tool."""
        self._tool = tool

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Load a new captured screenshot while keeping an immutable original copy."""
        self._original = pixmap.copy() if not pixmap.isNull() else QPixmap()
        self._history = [pixmap.copy()] if not pixmap.isNull() else []
        self._drawing = False
        self._pen_points.clear()
        self.update()
        self.annotation_changed.emit()

    def original_pixmap(self) -> QPixmap:
        """Return an intact copy of the original unannotated screenshot."""
        return self._original.copy() if not self._original.isNull() else QPixmap()

    def annotated_pixmap(self) -> QPixmap:
        """Return the current annotated (or cropped) screenshot separately."""
        return self._history[-1].copy() if self._history else QPixmap()

    def has_annotations(self) -> bool:
        """Return ``True`` if at least one annotation or crop has been applied."""
        return len(self._history) > 1

    def undo(self) -> bool:
        """Revert the most recent annotation or crop step."""
        if len(self._history) <= 1:
            return False
        self._history.pop()
        self.update()
        self.annotation_changed.emit()
        return True

    def reset(self) -> None:
        """Discard all annotations and crops, restoring the original screenshot."""
        if self._original.isNull():
            return
        self._history = [self._original.copy()]
        self._drawing = False
        self._pen_points.clear()
        self.update()
        self.annotation_changed.emit()

    def add_text_label(self, pixmap_pt: QPointF, text: str) -> None:
        """Render a text label onto a new history layer at ``pixmap_pt``."""
        clean = text.strip()
        if not clean or not self._history:
            return
        canvas = self._history[-1].copy()
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self._text_color)
        font_px = max(14, round(min(canvas.width(), canvas.height()) * 0.032))
        font = QFont("Segoe UI")
        font.setPixelSize(font_px)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap_pt, clean)
        painter.end()
        self._history.append(canvas)
        self.update()
        self.annotation_changed.emit()

    def _display_rect(self) -> QRectF:
        area = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        if not self._history or self._history[-1].isNull():
            return area
        pm = self._history[-1]
        pw, ph = pm.width(), pm.height()
        if pw <= 0 or ph <= 0:
            return area
        scale = min(area.width() / pw, area.height() / ph)
        w, h = pw * scale, ph * scale
        return QRectF(area.center().x() - w / 2.0, area.center().y() - h / 2.0, w, h)

    def _to_pixmap_pt(self, widget_pt: QPointF) -> QPointF:
        disp = self._display_rect()
        pm = self._history[-1]
        if disp.width() <= 0 or disp.height() <= 0:
            return QPointF(0.0, 0.0)
        x = (widget_pt.x() - disp.left()) * (pm.width() / disp.width())
        y = (widget_pt.y() - disp.top()) * (pm.height() / disp.height())
        return QPointF(max(0.0, min(float(pm.width()), x)), max(0.0, min(float(pm.height()), y)))

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(rect, QColor("#13161b"))

        if not self._history or self._history[-1].isNull():
            p.setPen(QColor("#7f8995"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Capture a screenshot below to preview and annotate.")
        else:
            disp = self._display_rect()
            p.drawPixmap(disp.toRect(), self._history[-1])
            if self._drawing:
                self._paint_live_preview(p, disp)

        p.setPen(QPen(QColor(BORDER), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8.0, 8.0)

    def _paint_live_preview(self, painter: QPainter, disp: QRectF) -> None:
        pm = self._history[-1]
        sx, sy = disp.width() / max(1, pm.width()), disp.height() / max(1, pm.height())
        to_w = lambda pt: QPointF(disp.left() + pt.x() * sx, disp.top() + pt.y() * sy)
        if self._tool == "crop":
            painter.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(169, 184, 223, 30))
            painter.drawRect(QRectF(to_w(self._start_pt), to_w(self._current_pt)).normalized())
            return
        pts = [to_w(pt) for pt in self._pen_points]
        self._draw_shape(painter, self._tool, to_w(self._start_pt), to_w(self._current_pt), pts, 2.5)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._history:
            return
        pt = self._to_pixmap_pt(event.position())
        if self._tool == "text":
            text, ok = QInputDialog.getText(self, "Add label", "Label text:")
            if ok and text.strip():
                self.add_text_label(pt, text)
            return
        self._drawing = True
        self._start_pt = self._current_pt = pt
        self._pen_points = [pt] if self._tool == "pen" else []
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._drawing or not self._history:
            return
        pt = self._to_pixmap_pt(event.position())
        self._current_pt = pt
        if self._tool == "pen":
            self._pen_points.append(pt)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._drawing or not self._history:
            return
        self._drawing = False
        self._current_pt = self._to_pixmap_pt(event.position())
        if self._tool == "crop":
            crop = QRectF(self._start_pt, self._current_pt).normalized().toRect()
            crop = crop.intersected(QRect(0, 0, self._history[-1].width(), self._history[-1].height()))
            if crop.width() >= 8 and crop.height() >= 8:
                self._history.append(self._history[-1].copy(crop))
                self.annotation_changed.emit()
            self.update()
            return

        canvas = self._history[-1].copy()
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        stroke_w = max(2.5, min(canvas.width(), canvas.height()) * 0.0045)
        self._draw_shape(painter, self._tool, self._start_pt, self._current_pt, self._pen_points, stroke_w)
        painter.end()
        self._history.append(canvas)
        self._pen_points.clear()
        self.update()
        self.annotation_changed.emit()

    def _draw_shape(
        self, painter: QPainter, tool: AnnotatorTool, start: QPointF, end: QPointF,
        pen_pts: list[QPointF], width: float,
    ) -> None:
        pen = QPen(self._stroke_color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if tool == "pen" and len(pen_pts) >= 2:
            path = QPainterPath(pen_pts[0])
            for pt in pen_pts[1:]:
                path.lineTo(pt)
            painter.drawPath(path)
        elif tool == "rect":
            painter.drawRect(QRectF(start, end).normalized())
        elif tool == "circle":
            r = math.hypot(end.x() - start.x(), end.y() - start.y())
            painter.drawEllipse(start, r, r)
        elif tool == "arrow":
            painter.drawLine(start, end)
            angle = math.atan2(end.y() - start.y(), end.x() - start.x())
            head_len = max(10.0, width * 4.2)
            p1 = QPointF(end.x() - head_len * math.cos(angle - 0.45), end.y() - head_len * math.sin(angle - 0.45))
            p2 = QPointF(end.x() - head_len * math.cos(angle + 0.45), end.y() - head_len * math.sin(angle + 0.45))
            painter.setBrush(self._stroke_color)
            painter.drawPolygon(QPolygonF([end, p1, p2]))
