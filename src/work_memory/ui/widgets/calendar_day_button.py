"""Day cell button and legend swatch widgets for MonthCalendarWidget."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QFont, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QPushButton, QWidget

from work_memory.core.models import DayMarkers
from work_memory.ui.theme import get_palette


class LegendSwatch(QWidget):
    """Tiny dot or diamond indicator used in the calendar footer legend."""

    def __init__(self, kind: str, *, diamond: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind, self._diamond = kind, diamond
        self.setFixedSize(8, 8)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        pal = get_palette()
        color_hex = pal.purple if self._kind == "ev" else (pal.accent if self._kind == "obs" else pal.amber)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color_hex))
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self._diamond:
            p.drawPolygon(QPolygonF([QPointF(cx, cy - 3.0), QPointF(cx + 3.0, cy), QPointF(cx, cy + 3.0), QPointF(cx - 3.0, cy)]))
        else:
            p.drawEllipse(QPointF(cx, cy), 2.3, 2.3)


class CalendarDayButton(QPushButton):
    """Single day cell painting hover/selected/today state and up to 3 activity markers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._day_num, self._in_month = 1, True
        self._is_today = self._is_selected = self._hovered = False
        self._markers = DayMarkers()
        self.setMinimumHeight(40)
        self.setFlat(True)

    @property
    def day_num(self) -> int:
        """Return the calendar day number (1..31) represented by this cell."""
        return self._day_num

    @property
    def markers(self) -> DayMarkers:
        """Return the ``DayMarkers`` rendered inside this cell."""
        return self._markers

    def set_cell(
        self, day_num: int, *, in_month: bool, is_today: bool, is_selected: bool, markers: DayMarkers
    ) -> None:
        """Update cell visual state and activity markers."""
        self._day_num, self._in_month = day_num, in_month
        self._is_today, self._is_selected, self._markers = is_today, is_selected, markers
        self.setEnabled(in_month)
        self.setCursor(Qt.CursorShape.PointingHandCursor if in_month else Qt.CursorShape.ArrowCursor)
        self.setText(str(day_num))
        self.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        pal = get_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self._in_month and self._is_selected:
            p.setPen(QPen(QColor(pal.cal_selected_border), 1.5))
            p.setBrush(QColor(pal.cal_selected_bg))
            p.drawRoundedRect(rect, 8.0, 8.0)
        elif self._in_month and self._is_today:
            p.setPen(QPen(QColor(pal.cal_today_border), 1.0))
            p.setBrush(QColor(pal.cal_hover_bg if self._hovered else pal.cal_today_bg))
            p.drawRoundedRect(rect, 8.0, 8.0)
        elif self._in_month and self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal.cal_hover_bg))
            p.drawRoundedRect(rect, 8.0, 8.0)

        text_hex = (
            pal.cal_selected_text
            if (self._in_month and self._is_selected)
            else (pal.cal_in_month_text if self._in_month else pal.cal_out_month_text)
        )
        p.setPen(QColor(text_hex))
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.DemiBold if self._is_selected else QFont.Weight.Normal)
        p.setFont(font)
        p.drawText(rect.adjusted(0, 4, 0, -12), Qt.AlignmentFlag.AlignCenter, str(self._day_num))
        if self._in_month and self._markers.has_any:
            self._paint_markers(p, rect, pal)

    def _paint_markers(self, painter: QPainter, rect: QRectF, pal: object) -> None:
        kinds = [
            k
            for k, flag in (
                ("obs", self._markers.has_observed),
                ("cap", self._markers.has_captures),
                ("ev", self._markers.has_events),
            )
            if flag
        ]
        start_x = rect.center().x() - ((len(kinds) - 1) * 7.0) / 2.0
        y = rect.bottom() - 8.0
        painter.setPen(Qt.PenStyle.NoPen)
        for idx, kind in enumerate(kinds):
            cx = start_x + idx * 7.0
            if kind == "ev":
                painter.setBrush(QColor(pal.purple))  # type: ignore[attr-defined]
                painter.drawPolygon(QPolygonF([QPointF(cx, y - 2.6), QPointF(cx + 2.6, y), QPointF(cx, y + 2.6), QPointF(cx - 2.6, y)]))
            else:
                color = pal.accent if kind == "obs" else pal.amber  # type: ignore[attr-defined]
                painter.setBrush(QColor(color))
                painter.drawEllipse(QPointF(cx, y), 2.1, 2.1)
