"""Reusable dark month calendar widget with observed, capture, and event markers."""

from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import DayMarkers
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.calendar_day_button import CalendarDayButton, LegendSwatch

_WEEKDAYS = ("M", "T", "W", "T", "F", "S", "S")


class MonthCalendarWidget(QWidget):
    """Dark month calendar showing per-day observed, note, and scheduled-event markers."""

    date_selected = Signal(QDate)
    month_changed = Signal(int, int)

    def __init__(
        self, *, initial_date: QDate | None = None, select_initial: bool = True,
        allow_deselect: bool = False, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        today = initial_date or QDate.currentDate()
        self._year, self._month = today.year(), today.month()
        self._selected_date: QDate | None = today if select_initial else None
        self._allow_deselect = allow_deselect
        self._markers: dict[int, DayMarkers] = {}
        self._cells: list[CalendarDayButton] = []

        self._weekday_labels: list[QLabel] = []
        self._legend_labels: list[QLabel] = []
        self._legend_swatches: list[LegendSwatch] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        root.addLayout(self._build_grid())
        self._legend_footer = self._build_legend()
        root.addWidget(self._legend_footer)
        self.refresh_theme()
        self._refresh_cells()

    def current_year_month(self) -> tuple[int, int]:
        """Return the currently displayed ``(year, month)`` pair."""
        return self._year, self._month

    def selected_date(self) -> QDate | None:
        """Return the currently selected ``QDate``, or ``None`` if deselected."""
        return self._selected_date

    def set_month(self, year: int, month: int) -> None:
        """Display ``(year, month)`` and clear stale markers until updated."""
        self._year, self._month, self._markers = year, month, {}
        self._refresh_cells()

    def set_selected_date(self, qdate: QDate | None) -> None:
        """Programmatically select ``qdate`` (or clear selection when ``None``/invalid)."""
        if qdate is None or not qdate.isValid():
            self._selected_date = None
        else:
            self._selected_date, self._year, self._month = qdate, qdate.year(), qdate.month()
        self._refresh_cells()

    def clear_selection(self) -> None:
        """Clear the active day selection without changing the displayed month."""
        self._selected_date = None
        self._refresh_cells()

    def set_markers(self, markers: dict[int, DayMarkers]) -> None:
        """Update per-day markers for the currently displayed month."""
        self._markers = dict(markers)
        self._refresh_cells()

    def day_button(self, day: int) -> CalendarDayButton | None:
        """Return the in-month cell button for ``day`` (1..31), if visible."""
        return next((c for c in self._cells if c.isEnabled() and c.day_num == day), None)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 2)
        self._month_label = QLabel()
        header.addWidget(self._month_label, 1)
        for text, obj, delta in (("\u2039", "calendarPrevMonthButton", -1), ("\u203a", "calendarNextMonthButton", 1)):
            btn = QPushButton(text)
            btn.setObjectName(obj)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, d=delta: self._step_month(d))
            header.addWidget(btn)
            if delta < 0:
                self._prev_btn = btn
                header.addSpacing(6)
            else:
                self._next_btn = btn
        return header

    def _build_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(5)
        for col, name in enumerate(_WEEKDAYS):
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._weekday_labels.append(lbl)
            grid.addWidget(lbl, 0, col)
        for idx in range(42):
            cell = CalendarDayButton()
            cell.clicked.connect(lambda _c=False, b=cell: self._on_day_clicked(b))
            self._cells.append(cell)
            grid.addWidget(cell, 1 + idx // 7, idx % 7)
        return grid

    def _build_legend(self) -> QFrame:
        footer = QFrame()
        row = QHBoxLayout(footer)
        row.setContentsMargins(0, 12, 0, 0)
        row.setSpacing(12)
        for label_text, kind, diamond in (("Activity", "obs", False), ("Notes", "cap", False), ("Planned", "ev", True)):
            item = QHBoxLayout()
            item.setSpacing(5)
            swatch = LegendSwatch(kind, diamond=diamond)
            self._legend_swatches.append(swatch)
            item.addWidget(swatch)
            lbl = QLabel(label_text)
            self._legend_labels.append(lbl)
            item.addWidget(lbl)
            row.addLayout(item)
        row.addStretch(1)
        return footer

    def refresh_theme(self) -> None:
        """Re-apply active theme colors across calendar labels, buttons, and cells."""
        pal = get_palette()
        self._month_label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {pal.text};")
        btn_css = (
            f"QPushButton {{ background: transparent; border: 1px solid {pal.border}; border-radius: 7px; "
            f"color: {pal.muted}; font-size: 15px; min-width: 29px; max-width: 29px; min-height: 29px; max-height: 29px; }}"
            f"QPushButton:hover {{ border-color: {pal.hover_border}; color: {pal.text}; }}"
        )
        self._prev_btn.setStyleSheet(btn_css)
        self._next_btn.setStyleSheet(btn_css)
        for lbl in self._weekday_labels:
            lbl.setStyleSheet(f"color: {pal.muted}; font-size: 10px; padding: 4px 0 6px 0;")
        self._legend_footer.setStyleSheet(f"border-top: 1px solid {pal.border_soft};")
        for lbl in self._legend_labels:
            lbl.setStyleSheet(f"color: {pal.muted}; font-size: 11px; border: none;")
        for sw in self._legend_swatches:
            sw.update()
        for cell in self._cells:
            cell.update()

    def _step_month(self, delta: int) -> None:
        year, month = self._year, self._month + delta
        if month < 1:
            year, month = year - 1, 12
        elif month > 12:
            year, month = year + 1, 1
        self._year, self._month, self._markers = year, month, {}
        self._selected_date = None if self._allow_deselect else QDate(year, month, 1)
        self._refresh_cells()
        self.month_changed.emit(year, month)
        if self._selected_date is not None:
            self.date_selected.emit(self._selected_date)

    def _on_day_clicked(self, button: CalendarDayButton) -> None:
        if not button.isEnabled():
            return
        clicked = QDate(self._year, self._month, button.day_num)
        if self._allow_deselect and self._selected_date == clicked:
            self._selected_date = None
            self._refresh_cells()
            self.date_selected.emit(QDate())
            return
        self._selected_date = clicked
        self._refresh_cells()
        self.date_selected.emit(clicked)

    def _refresh_cells(self) -> None:
        self._month_label.setText(f"{calendar.month_name[self._month]} {self._year}")
        first_wd, days_in_month = calendar.monthrange(self._year, self._month)
        py, pm = (self._year - 1, 12) if self._month == 1 else (self._year, self._month - 1)
        prev_days = calendar.monthrange(py, pm)[1]
        today = date.today()
        for idx, cell in enumerate(self._cells):
            if idx < first_wd:
                cell.set_cell(prev_days - first_wd + idx + 1, in_month=False, is_today=False, is_selected=False, markers=DayMarkers())
            elif idx >= first_wd + days_in_month:
                cell.set_cell(idx - first_wd - days_in_month + 1, in_month=False, is_today=False, is_selected=False, markers=DayMarkers())
            else:
                num = idx - first_wd + 1
                is_today = (self._year, self._month, num) == (today.year, today.month, today.day)
                is_sel = self._selected_date is not None and self._selected_date.isValid() and (self._selected_date.year(), self._selected_date.month(), self._selected_date.day()) == (self._year, self._month, num)
                cell.set_cell(num, in_month=True, is_today=is_today, is_selected=is_sel, markers=self._markers.get(num, DayMarkers()))
