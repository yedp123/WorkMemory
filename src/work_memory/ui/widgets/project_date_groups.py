"""Collapsible Year & vertical Month grouping helpers for ProjectsView."""

from __future__ import annotations

import calendar
from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import Project
from work_memory.services.history_service import parse_utc_to_local
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets import gallery_controls as gc
from work_memory.ui.widgets.project_card import ProjectCard

MonthBucket = tuple[int, list[Project]]
YearBucket = tuple[int, list[MonthBucket]]


def group_projects_by_creation_date(
    projects: Sequence[Project],
) -> tuple[list[Project], list[YearBucket]]:
    """Split pinned projects and group remaining projects into Year -> Month buckets."""
    pinned = sorted(
        (p for p in projects if p.is_pinned),
        key=lambda p: (p.created_at_utc, p.id),
        reverse=True,
    )
    by_year_month: dict[int, dict[int, list[Project]]] = {}
    for proj in projects:
        if proj.is_pinned:
            continue
        local_dt = parse_utc_to_local(proj.created_at_utc)
        by_year_month.setdefault(local_dt.year, {}).setdefault(local_dt.month, []).append(proj)

    year_buckets: list[YearBucket] = []
    for year in sorted(by_year_month.keys(), reverse=True):
        months_map = by_year_month[year]
        month_list: list[MonthBucket] = []
        for month in sorted(months_map.keys(), reverse=True):
            items = sorted(months_map[month], key=lambda p: (p.created_at_utc, p.id), reverse=True)
            month_list.append((month, items))
        year_buckets.append((year, month_list))
    return pinned, year_buckets


def _populate_card_grid(
    grid: QGridLayout,
    cards: Sequence[ProjectCard],
    view_mode: str,
    cols: int,
) -> None:
    is_list = view_mode == "list"
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(0 if is_list else gc.GRID_GAP)
    grid.setVerticalSpacing(10 if is_list else 24)
    grid.setAlignment(
        Qt.AlignmentFlag.AlignTop
        if is_list
        else (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    )
    for col in range(max(cols + 1, 8)):
        grid.setColumnStretch(col, 1 if (is_list and col == 0) else 0)
    for idx, card in enumerate(cards):
        grid.addWidget(card, idx // cols, idx % cols)


class CollapsibleYearSection(QWidget):
    """Bold collapsible Year header containing vertical Month subsections."""

    toggled = Signal(int, bool)

    def __init__(
        self,
        year: int,
        months: Sequence[MonthBucket],
        *,
        expanded: bool,
        view_mode: str,
        cols: int,
        make_card: Callable[[Project], ProjectCard],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._year = year
        self._expanded = expanded
        pal = get_palette()
        total_count = sum(len(items) for _m, items in months)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 8)
        root.setSpacing(10)

        self._header_btn = QPushButton()
        self._header_btn.setObjectName(f"projectYearHeader_{year}")
        self._header_btn.setFlat(True)
        self._header_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 2px 0px; text-align: left; }"
        )
        h_row = QHBoxLayout(self._header_btn)
        h_row.setContentsMargins(0, 0, 0, 2)
        h_row.setSpacing(8)

        year_lbl = QLabel(str(year))
        year_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        year_lbl.setStyleSheet(f"color: {pal.text}; font-size: 20px; font-weight: 700;")

        count_lbl = QLabel(f"\u00b7  {total_count}")
        count_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        count_lbl.setStyleSheet(f"color: {pal.muted}; font-size: 12px;")

        self._chevron = QLabel("\u2304" if expanded else "\u203a")
        self._chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._chevron.setStyleSheet(f"color: {pal.muted}; font-size: 16px;")

        h_row.addWidget(year_lbl)
        h_row.addWidget(count_lbl)
        h_row.addStretch(1)
        h_row.addWidget(self._chevron)
        self._header_btn.clicked.connect(self._on_toggle)
        root.addWidget(self._header_btn)

        divider = QFrame()
        divider.setStyleSheet(f"background-color: {pal.border_soft}; min-height: 1px; max-height: 1px;")
        root.addWidget(divider)

        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 2, 0, 6)
        body_lay.setSpacing(18)

        for month_num, items in months:
            month_wrap = QWidget()
            m_lay = QVBoxLayout(month_wrap)
            m_lay.setContentsMargins(0, 0, 0, 0)
            m_lay.setSpacing(10)

            month_name = calendar.month_name[month_num] if 1 <= month_num <= 12 else "Other"
            m_lbl = QLabel(f"{month_name}")
            m_lbl.setObjectName(f"projectMonthHeader_{year}_{month_num:02d}")
            m_lbl.setStyleSheet(f"color: {pal.muted}; font-size: 13px; font-weight: 600;")
            m_lay.addWidget(m_lbl)

            grid = QGridLayout()
            _populate_card_grid(grid, [make_card(p) for p in items], view_mode, cols)
            m_lay.addLayout(grid)
            body_lay.addWidget(month_wrap)

        self._body.setVisible(expanded)
        root.addWidget(self._body)

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._chevron.setText("\u2304" if self._expanded else "\u203a")
        self.toggled.emit(self._year, self._expanded)


def build_pinned_section(
    pinned: Sequence[Project],
    *,
    view_mode: str,
    cols: int,
    make_card: Callable[[Project], ProjectCard],
) -> QWidget:
    """Build the top Pinned section rendered ahead of chronological Year/Month groups."""
    pal = get_palette()
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 2, 0, 10)
    lay.setSpacing(10)

    hdr = QLabel(f"\U0001f4cc  Pinned  \u00b7  {len(pinned)}")
    hdr.setObjectName("projectPinnedHeader")
    hdr.setStyleSheet(f"color: {pal.amber}; font-size: 14px; font-weight: 600;")
    lay.addWidget(hdr)

    grid = QGridLayout()
    _populate_card_grid(grid, [make_card(p) for p in pinned], view_mode, cols)
    lay.addLayout(grid)
    return wrap


def populate_grouped_sections(
    sections_layout: QVBoxLayout,
    projects: Sequence[Project],
    *,
    collapsed_years: set[int],
    view_mode: str,
    cols: int,
    make_card: Callable[[Project], ProjectCard],
    on_year_toggled: Callable[[int, bool], None],
) -> None:
    """Populate ``sections_layout`` with optional Pinned group and Year/Month sections."""
    pinned, year_buckets = group_projects_by_creation_date(projects)
    if pinned:
        sections_layout.addWidget(
            build_pinned_section(pinned, view_mode=view_mode, cols=cols, make_card=make_card)
        )
    for year, months in year_buckets:
        sec = CollapsibleYearSection(
            year,
            months,
            expanded=(year not in collapsed_years),
            view_mode=view_mode,
            cols=cols,
            make_card=make_card,
        )
        sec.toggled.connect(on_year_toggled)
        sections_layout.addWidget(sec)
