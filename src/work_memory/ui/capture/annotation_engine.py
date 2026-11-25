"""Pure vector annotation state and non-destructive QPainter renderer."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

AnnotationTool = Literal["rect", "circle", "arrow", "pen", "text"]
SizePreset = Literal["small", "medium", "large"]

STROKE_PRESETS: dict[SizePreset, int] = {"small": 2, "medium": 4, "large": 7}
FONT_PRESETS: dict[SizePreset, int] = {"small": 14, "medium": 18, "large": 24}
DEFAULT_ANNOTATION_COLOR = QColor("#ef5350")


@dataclass(frozen=True, slots=True)
class AnnotationItem:
    """Single immutable vector annotation with snapshotted color and size."""

    tool: AnnotationTool
    start: QPointF
    end: QPointF
    points: tuple[QPointF, ...] = ()
    text: str = ""
    color: QColor = field(default_factory=lambda: QColor(DEFAULT_ANNOTATION_COLOR))
    thickness: int = 4
    font_size: int = 18


class AnnotationEngine:
    """Manages ordered vector annotations with per-item style, Undo, and Reset."""

    def __init__(self) -> None:
        self._items: list[AnnotationItem] = []
        self._active_color = QColor(DEFAULT_ANNOTATION_COLOR)
        self._active_size_preset: SizePreset = "medium"

    @property
    def items(self) -> tuple[AnnotationItem, ...]:
        """Return committed annotation items in drawing order."""
        return tuple(self._items)

    @property
    def active_color(self) -> QColor:
        """Return a copy of the active color for new annotations."""
        return QColor(self._active_color)

    @property
    def active_size_preset(self) -> SizePreset:
        """Return the active size preset key (``small``, ``medium``, or ``large``)."""
        return self._active_size_preset

    @property
    def active_thickness(self) -> int:
        """Return the stroke width in pixels for the active size preset."""
        return STROKE_PRESETS[self._active_size_preset]

    @property
    def active_font_size(self) -> int:
        """Return the text font size in points for the active size preset."""
        return FONT_PRESETS[self._active_size_preset]

    def set_color(self, color: QColor) -> None:
        """Update active color for subsequent annotations without altering existing items."""
        if color.isValid():
            self._active_color = QColor(color)

    def set_size_preset(self, preset: SizePreset | str) -> None:
        """Update active size preset for subsequent annotations without altering existing items."""
        if preset in STROKE_PRESETS:
            self._active_size_preset = preset  # type: ignore[assignment]

    def has_annotations(self) -> bool:
        """Return ``True`` when at least one annotation item is present."""
        return bool(self._items)

    def add_item(self, item: AnnotationItem) -> None:
        """Append a pre-built ``AnnotationItem``."""
        self._items.append(item)

    def add_shape(
        self,
        tool: AnnotationTool,
        start: QPointF,
        end: QPointF,
        *,
        color: QColor | None = None,
        thickness: int | None = None,
    ) -> AnnotationItem:
        """Record a ``rect``, ``circle``, or ``arrow`` annotation with snapshotted style."""
        item = AnnotationItem(
            tool=tool,
            start=QPointF(start),
            end=QPointF(end),
            color=QColor(color) if color is not None else QColor(self._active_color),
            thickness=thickness if thickness is not None else self.active_thickness,
            font_size=self.active_font_size,
        )
        self._items.append(item)
        return item

    def add_pen_stroke(
        self,
        points: Sequence[QPointF],
        *,
        color: QColor | None = None,
        thickness: int | None = None,
    ) -> AnnotationItem | None:
        """Record a freehand pen stroke from two or more selection-relative points."""
        pts = tuple(QPointF(p) for p in points)
        if len(pts) < 2:
            return None
        item = AnnotationItem(
            tool="pen",
            start=pts[0],
            end=pts[-1],
            points=pts,
            color=QColor(color) if color is not None else QColor(self._active_color),
            thickness=thickness if thickness is not None else self.active_thickness,
            font_size=self.active_font_size,
        )
        self._items.append(item)
        return item

    def add_text(
        self,
        pos: QPointF,
        text: str,
        *,
        color: QColor | None = None,
        font_size: int | None = None,
    ) -> AnnotationItem | None:
        """Record a text label at ``pos`` relative to the selection top-left."""
        clean = text.strip()
        if not clean:
            return None
        item = AnnotationItem(
            tool="text",
            start=QPointF(pos),
            end=QPointF(pos),
            text=clean,
            color=QColor(color) if color is not None else QColor(self._active_color),
            thickness=self.active_thickness,
            font_size=font_size if font_size is not None else self.active_font_size,
        )
        self._items.append(item)
        return item

    def undo(self) -> bool:
        """Remove the most recent annotation item, returning ``True`` if one existed."""
        if not self._items:
            return False
        self._items.pop()
        return True

    def reset(self) -> bool:
        """Clear all annotations, returning ``True`` if any existed."""
        if not self._items:
            return False
        self._items.clear()
        return True

    def paint_on(
        self,
        painter: QPainter,
        origin: QPointF | None = None,
        *,
        preview: AnnotationItem | None = None,
    ) -> None:
        """Paint all committed annotations (plus optional live ``preview``) offset by ``origin``."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if origin is not None:
            painter.translate(origin)
        for item in self._items:
            self._draw_item(painter, item)
        if preview is not None:
            self._draw_item(painter, preview)
        painter.restore()

    def render_annotated(self, base_pixmap: QPixmap) -> QPixmap:
        """Return a new annotated ``QPixmap`` copy without modifying ``base_pixmap``."""
        if base_pixmap.isNull():
            return QPixmap()
        out = base_pixmap.copy()
        if not self._items:
            return out
        painter = QPainter(out)
        try:
            self.paint_on(painter, QPointF(0.0, 0.0))
        finally:
            painter.end()
        return out

    @staticmethod
    def _draw_item(painter: QPainter, item: AnnotationItem) -> None:
        if item.tool == "text":
            font = QFont("Segoe UI")
            font.setPointSize(max(10, item.font_size))
            font.setBold(True)
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            baseline = QPointF(item.start.x(), item.start.y() + metrics.ascent())
            painter.setPen(QColor(15, 17, 22, 180))
            painter.drawText(baseline + QPointF(1.0, 1.0), item.text)
            painter.setPen(item.color)
            painter.drawText(baseline, item.text)
            return

        pen = QPen(
            item.color,
            float(item.thickness),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if item.tool == "pen" and len(item.points) >= 2:
            path = QPainterPath(item.points[0])
            for pt in item.points[1:]:
                path.lineTo(pt)
            painter.drawPath(path)
        elif item.tool == "rect":
            painter.drawRect(QRectF(item.start, item.end).normalized())
        elif item.tool == "circle":
            painter.drawEllipse(QRectF(item.start, item.end).normalized())
        elif item.tool == "arrow":
            painter.drawLine(item.start, item.end)
            dx = item.end.x() - item.start.x()
            dy = item.end.y() - item.start.y()
            if math.hypot(dx, dy) < 2.0:
                return
            angle = math.atan2(dy, dx)
            head_len = max(10.0, float(item.thickness) * 3.5)
            p1 = QPointF(
                item.end.x() - head_len * math.cos(angle - 0.45),
                item.end.y() - head_len * math.sin(angle - 0.45),
            )
            p2 = QPointF(
                item.end.x() - head_len * math.cos(angle + 0.45),
                item.end.y() - head_len * math.sin(angle + 0.45),
            )
            painter.setBrush(item.color)
            painter.drawPolygon(QPolygonF([item.end, p1, p2]))
