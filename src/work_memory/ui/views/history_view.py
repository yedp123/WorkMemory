"""History screen pairing fixed MonthCalendarWidget with scrollable TimelineWidget."""

from __future__ import annotations

from PySide6.QtCore import QDate, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.event_bus import EventBus
from work_memory.core.models import CalendarEvent, DayTimeline, SearchResults
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.services.calendar_service import CalendarService
from work_memory.services.history_service import HistoryService
from work_memory.services.project_service import ProjectService
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.calendar_actions import (
    apply_event_status,
    open_create_event_dialog,
    open_edit_event_dialog,
)
from work_memory.ui.widgets.detail_helpers import (
    format_day_heading,
    qdate_to_date,
    render_matched_projects_chips,
)
from work_memory.ui.widgets.file_open_helper import (
    open_timeline_file_async,
    preview_timeline_file_async,
    reveal_timeline_file_async,
)
from work_memory.ui.widgets.month_calendar import MonthCalendarWidget
from work_memory.ui.widgets.scroll_helpers import wrap_in_scroll_area
from work_memory.ui.widgets.timeline_widget import TimelineWidget
from work_memory.ui.workers import run_in_pool


class HistoryView(QWidget):
    """Primary History view with fixed left calendar and independently scrollable right timeline."""

    project_selected = Signal(str)
    file_missing = Signal(str)
    info_toast = Signal(str, str)

    def __init__(
        self,
        history_service: HistoryService | None = None,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
        *,
        calendar_service: CalendarService | None = None,
        project_service: ProjectService | None = None,
        thumbnail_service: ThumbnailService | None = None,
    ) -> None:
        super().__init__(parent)
        self._history_service = history_service
        self._calendar_service = calendar_service
        self._project_service = project_service
        self._thumbnail_service = thumbnail_service
        self._search_query = ""
        self._markers_seq = self._timeline_seq = 0
        self._active_workers: set[QObject] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 30, 0, 24)
        layout.setSpacing(20)
        layout.addLayout(self._build_page_header())

        split = QHBoxLayout()
        split.setSpacing(26)
        self._calendar_card = self._build_calendar_surface()
        self._calendar_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        split.addWidget(self._calendar_card, 2, Qt.AlignmentFlag.AlignTop)
        split.addWidget(self._build_timeline_surface(), 3)
        layout.addLayout(split, 1)

        if event_bus is not None:
            event_bus.observed_event_recorded.connect(self._on_bus_refresh)
            event_bus.capture_saved.connect(self._on_bus_refresh)
            event_bus.milestone_updated.connect(self._on_bus_milestone_updated)
            event_bus.calendar_updated.connect(self.refresh_async)
            event_bus.projects_changed.connect(self.refresh_async)
            event_bus.project_updated.connect(self._on_bus_refresh)

        self.refresh_theme()
        self._update_day_header()
        self.refresh_async()

    @property
    def scroll_area(self) -> QScrollArea:
        """Return the right-hand timeline ``QScrollArea``."""
        return self._timeline_scroll

    def vertical_scroll_bar(self) -> QScrollBar:
        """Return the vertical scrollbar of the right-hand daily timeline."""
        return self._timeline_scroll.verticalScrollBar()

    def set_search_query(self, query: str) -> None:
        """Filter/search files, projects, and notes live via HistoryService."""
        trimmed = query.strip()
        if trimmed == self._search_query:
            return
        self._search_query = trimmed
        self._timeline_scroll.verticalScrollBar().setValue(0)
        self._update_day_header()
        self._load_timeline_async()

    def refresh_theme(self) -> None:
        """Re-apply theme palette to day heading, today pill, calendar, and timeline."""
        pal = get_palette()
        self._day_heading.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {pal.text};")
        self._today_tag.setStyleSheet(
            f"background-color: {pal.accent_bg}; color: {pal.accent}; border-radius: 10px; "
            "padding: 4px 8px; font-size: 10px; font-weight: 600;"
        )
        self._calendar.refresh_theme()
        self._load_timeline_async()

    @Slot(object)
    def _on_bus_refresh(self, _payload: object = None) -> None:
        self.refresh_async()

    @Slot(str, str, bool)
    def _on_bus_milestone_updated(self, _item_type: str, _item_id: str, _flag: bool) -> None:
        self._load_timeline_async()

    def refresh_async(self) -> None:
        """Reload month calendar markers and the active timeline or search results off-thread."""
        self._load_markers_async()
        self._load_timeline_async()

    def _build_page_header(self) -> QVBoxLayout:
        title = QLabel("History")
        title.setProperty("role", "pageTitle")
        subtitle = QLabel("A quiet record of what happened and what is planned, day by day.")
        subtitle.setProperty("role", "subtitle")
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(title)
        box.addWidget(subtitle)
        return box

    def _build_calendar_surface(self) -> QFrame:
        card = QFrame()
        card.setObjectName("historyCalendarCard")
        card.setProperty("surface", True)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(20, 20, 20, 20)
        self._calendar = MonthCalendarWidget(select_initial=True, allow_deselect=False)
        self._calendar.date_selected.connect(self._on_date_selected)
        self._calendar.month_changed.connect(self._on_month_changed)
        inner.addWidget(self._calendar)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.addStretch(1)
        self._schedule_btn = QPushButton("+ Schedule event")
        self._schedule_btn.setObjectName("scheduleEventButton")
        self._schedule_btn.setProperty("textButton", True)
        self._schedule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._schedule_btn.clicked.connect(self._on_schedule_event)
        footer.addWidget(self._schedule_btn)
        inner.addLayout(footer)
        return card

    def _build_timeline_surface(self) -> QFrame:
        card = QFrame()
        card.setObjectName("historyTimelineCard")
        card.setProperty("surface", True)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(20, 20, 20, 20)
        inner.setSpacing(14)

        day_head = QHBoxLayout()
        day_head.setSpacing(10)
        self._day_heading = QLabel()
        self._day_heading.setObjectName("historyDayHeading")
        self._today_tag = QLabel("TODAY")
        self._today_tag.setObjectName("historyTodayTag")
        day_head.addWidget(self._day_heading, 1)
        day_head.addWidget(self._today_tag, 0, Qt.AlignmentFlag.AlignRight)
        inner.addLayout(day_head)

        self._timeline_scroll, _content, tl_layout = wrap_in_scroll_area(
            margins=(0, 0, 4, 0), spacing=10, embedded=True, attach_to_host=False
        )
        self._search_projects_box = QWidget()
        self._search_projects_layout = QVBoxLayout(self._search_projects_box)
        self._search_projects_layout.setContentsMargins(0, 0, 0, 4)
        self._search_projects_layout.setSpacing(6)
        self._search_projects_box.setVisible(False)
        tl_layout.addWidget(self._search_projects_box)

        self._timeline = TimelineWidget(
            show_project_names=True, thumbnail_service=self._thumbnail_service
        )
        self._timeline.milestone_toggled.connect(self._on_milestone_toggled)
        self._timeline.event_edit_requested.connect(self._on_edit_event)
        self._timeline.event_status_requested.connect(self._on_event_status)
        self._timeline.file_open_requested.connect(self._on_file_open_requested)
        self._timeline.file_reveal_requested.connect(self._on_file_reveal_requested)
        self._timeline.file_preview_requested.connect(self._on_file_preview_requested)
        tl_layout.addWidget(self._timeline)
        tl_layout.addStretch(1)
        inner.addWidget(self._timeline_scroll, 1)
        return card

    def _on_date_selected(self, qdate: QDate) -> None:
        del qdate
        if not self._search_query:
            self._timeline_scroll.verticalScrollBar().setValue(0)
            self._update_day_header()
            self._load_timeline_async()

    def _on_month_changed(self, year: int, month: int) -> None:
        del year, month
        self._load_markers_async()

    def _update_day_header(self) -> None:
        if self._search_query:
            self._day_heading.setText(f'Search results for "{self._search_query}"')
            self._today_tag.setVisible(False)
            return
        selected = self._calendar.selected_date() or QDate.currentDate()
        self._day_heading.setText(format_day_heading(qdate_to_date(selected)))
        self._today_tag.setVisible(selected == QDate.currentDate())

    def _load_markers_async(self) -> None:
        if (service := self._history_service) is None:
            return
        year, month = self._calendar.current_year_month()
        self._markers_seq += 1
        seq = self._markers_seq
        run_in_pool(self, self._active_workers, lambda: (seq, year, month, service.get_month_markers(year, month)), self._on_markers_loaded)

    def _on_markers_loaded(self, payload: object) -> None:
        seq, year, month, markers = payload  # type: ignore[misc]
        if seq == self._markers_seq and (year, month) == self._calendar.current_year_month() and isinstance(markers, dict):
            self._calendar.set_markers(markers)  # type: ignore[arg-type]

    def _load_timeline_async(self) -> None:
        if (service := self._history_service) is None:
            render_matched_projects_chips(self._search_projects_box, self._search_projects_layout, (), self.project_selected.emit)
            self._timeline.set_timeline(DayTimeline(local_date=None))
            return
        self._timeline_seq += 1
        seq, query = self._timeline_seq, self._search_query
        if query:
            run_in_pool(self, self._active_workers, lambda: (seq, True, service.search(query)), self._on_timeline_loaded)
            return
        target_date = qdate_to_date(self._calendar.selected_date() or QDate.currentDate())
        run_in_pool(self, self._active_workers, lambda: (seq, False, service.get_day_timeline(target_date)), self._on_timeline_loaded)

    def _on_timeline_loaded(self, payload: object) -> None:
        seq, is_search, data = payload  # type: ignore[misc]
        if seq != self._timeline_seq:
            return
        if is_search and isinstance(data, SearchResults):
            render_matched_projects_chips(self._search_projects_box, self._search_projects_layout, data.projects, self.project_selected.emit)
            empty_msg = "No matching projects, files, or notes found." if not data.projects else "No matching file activity, notes, or scheduled events."
            self._timeline.set_timeline(data.timeline or DayTimeline(local_date=None), empty_text=empty_msg)
        elif not is_search and isinstance(data, DayTimeline):
            render_matched_projects_chips(self._search_projects_box, self._search_projects_layout, (), self.project_selected.emit)
            self._timeline.set_timeline(data)
        self._timeline.updateGeometry()
        self.updateGeometry()

    def _on_milestone_toggled(self, item_type: str, item_id: str) -> None:
        if (service := self._history_service) is None:
            return
        run_in_pool(
            self, self._active_workers,
            lambda: service.toggle_milestone(item_type, item_id),  # type: ignore[arg-type]
            lambda _res: self._load_timeline_async(),
        )

    def _on_schedule_event(self) -> None:
        selected = qdate_to_date(self._calendar.selected_date() or QDate.currentDate())
        open_create_event_dialog(self, self._calendar_service, self._project_service, initial_date=selected)

    def _on_edit_event(self, event: object) -> None:
        if isinstance(event, CalendarEvent):
            open_edit_event_dialog(self, self._calendar_service, self._project_service, event)

    def _on_event_status(self, event_id: str, status: str) -> None:
        apply_event_status(self._calendar_service, event_id, status)  # type: ignore[arg-type]

    def _on_file_open_requested(
        self, rel_path: str, project_id: str, workspace_id: str
    ) -> None:
        open_timeline_file_async(
            self, self._active_workers, self._history_service,
            rel_path, project_id, workspace_id, self.file_missing.emit,
        )

    def _on_file_reveal_requested(
        self, rel_path: str, project_id: str, workspace_id: str
    ) -> None:
        reveal_timeline_file_async(
            self, self._active_workers, self._history_service,
            rel_path, project_id, workspace_id, self.info_toast.emit,
        )

    def _on_file_preview_requested(
        self, rel_path: str, project_id: str, workspace_id: str
    ) -> None:
        preview_timeline_file_async(
            self, self._active_workers, self._history_service, self._thumbnail_service,
            rel_path, project_id, workspace_id, self.file_missing.emit, self.info_toast.emit,
        )
