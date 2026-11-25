"""HiDPI 2x antialiased monochrome vector QIcon factory for the capture toolbar."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_DEFAULT_FG = QColor("#dfe4ea")
_ACTIVE_FG = QColor("#a9b8df")
_CANCEL_FG = QColor("#e07a7a")
_CONFIRM_FG = QColor("#6ec494")


def _render_icon_pixmap(name: str, color: QColor, size: int = 18) -> QPixmap:
    dpr = 2.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "rect":
        painter.drawRoundedRect(QRectF(3.5, 4.2, 11.0, 9.6), 2.0, 2.0)
    elif name == "circle":
        painter.drawEllipse(QRectF(3.5, 3.5, 11.0, 11.0))
    elif name == "arrow":
        painter.drawLine(QPointF(4.2, 13.8), QPointF(13.8, 4.2))
        painter.drawPolyline([QPointF(8.2, 4.2), QPointF(13.8, 4.2), QPointF(13.8, 9.8)])
    elif name == "pen":
        path = QPainterPath(QPointF(3.8, 14.2))
        path.lineTo(QPointF(4.8, 10.6))
        path.lineTo(QPointF(12.2, 3.2))
        path.lineTo(QPointF(14.8, 5.8))
        path.lineTo(QPointF(7.4, 13.2))
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(10.6, 4.8), QPointF(13.2, 7.4))
    elif name == "text":
        painter.drawLine(QPointF(4.2, 4.2), QPointF(13.8, 4.2))
        painter.drawLine(QPointF(4.2, 4.2), QPointF(4.2, 5.6))
        painter.drawLine(QPointF(13.8, 4.2), QPointF(13.8, 5.6))
        painter.drawLine(QPointF(9.0, 4.2), QPointF(9.0, 14.0))
        painter.drawLine(QPointF(7.0, 14.0), QPointF(11.0, 14.0))
    elif name == "undo":
        path = QPainterPath(QPointF(4.5, 7.2))
        path.cubicTo(QPointF(7.5, 4.2), QPointF(13.8, 4.8), QPointF(13.8, 10.0))
        path.cubicTo(QPointF(13.8, 12.6), QPointF(11.8, 13.8), QPointF(9.2, 13.8))
        painter.drawPath(path)
        painter.drawPolyline([QPointF(7.8, 4.6), QPointF(4.2, 7.2), QPointF(7.2, 10.2)])
    elif name == "reset":
        arc_rect = QRectF(4.0, 4.2, 9.8, 9.8)
        painter.drawArc(arc_rect, 100 * 16, 265 * 16)
        end_rad = math.radians(5)
        ex = 8.9 + 4.9 * math.cos(end_rad)
        ey = 9.1 - 4.9 * math.sin(end_rad)
        painter.drawPolyline([QPointF(ex - 2.3, ey + 1.8), QPointF(ex, ey - 0.6), QPointF(ex + 2.0, ey + 2.0)])
    elif name == "cancel":
        painter.drawLine(QPointF(4.6, 4.6), QPointF(13.4, 13.4))
        painter.drawLine(QPointF(13.4, 4.6), QPointF(4.6, 13.4))
    elif name == "confirm":
        painter.drawPolyline([QPointF(3.8, 9.4), QPointF(7.4, 13.2), QPointF(14.2, 5.2)])

    painter.end()
    return pm


def make_toolbar_icon(name: str, *, checkable_tool: bool = False) -> QIcon:
    """Create a 2x HiDPI vector ``QIcon`` for ``name``."""
    base_color = _CANCEL_FG if name == "cancel" else (_CONFIRM_FG if name == "confirm" else _DEFAULT_FG)
    icon = QIcon()
    icon.addPixmap(_render_icon_pixmap(name, base_color), QIcon.Mode.Normal, QIcon.State.Off)
    if checkable_tool:
        icon.addPixmap(_render_icon_pixmap(name, _ACTIVE_FG), QIcon.Mode.Normal, QIcon.State.On)
    return icon
