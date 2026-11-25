"""Project Detail screen matching docs/ui_prototype.html with shared calendar & timeline."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QScrollArea, QScrollBar, QWidget

from work_memory.core.event_bus import EventBus
from work_memory.core.models import (
    CalendarEvent,
    MilestoneDetail,
    ObservedEvent,
    Project,
    ProjectSummaryView,
)
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.services.calendar_service import CalendarService
from work_memory.services.history_service import HistoryService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.project_service import ProjectService
from work_memory.services.relink_service import RelinkService
from work_memory.services.summary_service import SummaryService
from work_memory.ui.widgets import calendar_actions, project_hero
from work_memory.ui.widgets import cover_actions as ca
from work_memory.ui.widgets import detail_helpers as dh
from work_memory.ui.widgets.milestone_preview_dialog import MilestonePreviewDialog
from work_memory.ui.widgets.milestones_panel import MilestonesPanel
from work_memory.ui.widgets.month_calendar import MonthCalendarWidget
from work_memory.ui.widgets.project_hero import make_button
from work_memory.ui.widgets.scroll_helpers import wrap_in_scroll_area
from work_memory.ui.widgets.summary_panel import SummaryPanel
from work_memory.ui.widgets.timeline_widget import TimelineWidget
from work_memory.ui.workers import run_in_pool


class ProjectDetailView(QWidget):
    """Displays project metadata, status toggle, project calendar, and unified timeline."""

    back_requested = Signal()
    capture_requested = Signal(str)
    file_missing = Signal(str)
    info_toast = Signal(str, str)

    def __init__(
        self, project_service: ProjectService | None = None, history_service: HistoryService | None = None,
        event_bus: EventBus | None = None, parent: QWidget | None = None, *,
        calendar_service: CalendarService | None = None, summary_service: SummaryService | None = None,
        relink_service: RelinkService | None = None, manifest_service: ManifestService | None = None,
        thumbnail_service: ThumbnailService | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_service, self._history_service = project_service, history_service
        self._calendar_service, self._summary_service = calendar_service, summary_service
        self._relink_service, self._manifest_service = relink_service, manifest_service
        self._thumbnail_service = thumbnail_service
        self._project: Project | None = None
        self._active_project_id: str | None = None
        self._selected_date: date | None = None
        self._search_query, self._load_seq, self._markers_seq = "", 0, 0
        self._active_workers: set[QObject] = set()
        self._preview_dialog: MilestonePreviewDialog | None = None

        self._scroll_area, _content, layout = wrap_in_scroll_area(self, margins=(0, 30, 0, 40), spacing=22)
        self._back_btn = QPushButton("\u2190  Projects")
        self._back_btn.setObjectName("backButton")
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(self._back_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self._hero = project_hero.ProjectHeroSection(
            self._on_capture_requested, self._on_toggle_status, self._on_open_folder,
            self._on_relink_folder, self._on_export_bundle, self._on_change_cover, self._on_reset_cover,
        )
        self._title_label = self._hero.title_label
        self._capture_note_btn = self._hero.capture_note_btn
        self._toggle_status_btn = self._hero.toggle_status_btn
        self._open_folder_btn = self._hero.open_folder_btn
        self._pin_btn = make_button("Pin", "detailPinButton", self._on_toggle_pin)
        dh.insert_hero_pin_button(self._hero, self._pin_btn)
        layout.addLayout(self._hero.hero_layout)
        self._summary_panel = SummaryPanel()
        self._summary_panel.reference_clicked.connect(self._on_summary_reference_clicked)
        self._summary_panel.save_custom_requested.connect(self._on_save_custom_summary)
        self._summary_panel.regenerate_requested.connect(self._on_regenerate_summary)
        layout.addWidget(self._summary_panel)
        self._milestones_panel = MilestonesPanel()
        self._milestones_panel.unstar_requested.connect(self._on_milestone_toggled)
        self._milestones_panel.milestone_clicked.connect(self._on_milestone_clicked)
        layout.addWidget(self._milestones_panel)
        layout.addLayout(self._build_detail_split())
        layout.addStretch(1)

        if event_bus is not None:
            event_bus.project_updated.connect(self._on_project_updated)
            event_bus.observed_event_recorded.connect(self._on_observed_event)
            event_bus.capture_saved.connect(self._on_bus_refresh)
            event_bus.milestone_updated.connect(self._on_bus_milestone_updated)
            event_bus.calendar_updated.connect(self._refresh_active_project)

    def refresh_theme(self) -> None:
        """Re-apply active theme colors across detail panels, calendar, and timeline."""
        self._calendar.refresh_theme()
        self._summary_panel.refresh_theme()
        self._milestones_panel.refresh_theme()
        if self._project is not None:
            self._render_hero(self._project)
        self._refresh_active_project()

    @Slot(object)
    def _on_bus_refresh(self, _payload: object = None) -> None:
        self._refresh_active_project()

    @Slot(str, str, bool)
    def _on_bus_milestone_updated(self, _item_type: str, _item_id: str, _flag: bool) -> None:
        self._refresh_active_project()

    @property
    def scroll_area(self) -> QScrollArea:
        """Return this view's independent ``QScrollArea``."""
        return self._scroll_area

    def vertical_scroll_bar(self) -> QScrollBar:
        """Return this view's vertical scrollbar."""
        return self._scroll_area.verticalScrollBar()

    @property
    def active_project_id(self) -> str | None:
        """Return the currently displayed project ID."""
        return self._active_project_id

    def show_project(self, project_id: str, project: Project | None = None) -> None:
        """Display ``project_id``, reset scroll to top, and load details, calendar, and timeline."""
        self._active_project_id, self._selected_date = project_id, None
        self._scroll_area.verticalScrollBar().setValue(0)
        today = QDate.currentDate()
        self._calendar.set_month(today.year(), today.month())
        self._calendar.clear_selection()
        self._project = project
        self._summary_panel.set_summary(None)
        if project is not None:
            self._render_hero(project)
        self._update_timeline_header()
        self.refresh_project_async(project_id)

    def refresh_project_async(self, project_id: str) -> None:
        """Fetch latest project state, timeline, and month markers via ``QThreadPool``."""
        self._load_timeline_async(project_id)
        self._load_markers_async(project_id)

    def set_search_query(self, query: str) -> None:
        """Filter/search this project's file paths and notes live via HistoryService."""
        trimmed = query.strip()
        if trimmed == self._search_query:
            return
        self._search_query = trimmed
        self._update_timeline_header()
        if self._active_project_id is not None:
            self._load_timeline_async(self._active_project_id)

    def _build_detail_split(self) -> QHBoxLayout:
        self._timeline = TimelineWidget(show_project_names=False, thumbnail_service=self._thumbnail_service)
        self._calendar = MonthCalendarWidget(select_initial=False, allow_deselect=True)
        dh.wire_detail_calendar_timeline(
            self._timeline, self._calendar, self._on_milestone_toggled, self._on_file_open_requested,
            self._on_edit_event, self._on_event_status, self._on_calendar_date_selected,
            self._on_calendar_month_changed, on_file_reveal=self._on_file_reveal_requested,
            on_file_preview=self._on_file_preview_requested,
        )
        split, self._timeline_title, self._clear_date_btn, self._notes_list_layout = project_hero.build_detail_split_cards(
            self._timeline, self._calendar, self._on_clear_date, self._on_schedule_event, self._on_capture_requested,
        )
        return split

    def _on_edit_event(self, ev: object) -> None:
        if isinstance(ev, CalendarEvent):
            calendar_actions.open_edit_event_dialog(self, self._calendar_service, self._project_service, ev)

    def _on_event_status(self, event_id: str, status: str) -> None:
        calendar_actions.apply_event_status(self._calendar_service, event_id, status)  # type: ignore[arg-type]

    def _load_timeline_async(self, project_id: str) -> None:
        self._load_seq += 1
        seq, q, sd = self._load_seq, self._search_query, self._selected_date
        run_in_pool(self, self._active_workers, lambda: dh.fetch_project_detail_bundle(seq, project_id, q, sd, self._project_service, self._history_service, self._summary_service), self._on_loaded)

    def _load_markers_async(self, project_id: str) -> None:
        if (svc := self._history_service) is None:
            return
        year, month = self._calendar.current_year_month()
        self._markers_seq += 1
        seq = self._markers_seq
        run_in_pool(self, self._active_workers, lambda: (seq, project_id, year, month, svc.get_month_markers(year, month, project_id=project_id)), self._on_markers_loaded)

    def _on_loaded(self, payload: object) -> None:
        seq, project, timeline, notes, milestones, summary = payload  # type: ignore[misc]
        if seq != self._load_seq:
            return
        if project is not None:
            self._project = project
            self._render_hero(project)
        if isinstance(summary, ProjectSummaryView):
            self._summary_panel.set_summary(summary)
        self._milestones_panel.set_milestones(list(milestones))
        self._timeline.set_timeline(timeline, empty_text=dh.detail_empty_text(self._search_query, self._selected_date))
        self._timeline.updateGeometry()
        project_hero.render_project_notes_list(self._notes_list_layout, notes)

    def _on_capture_requested(self) -> None:
        self.capture_requested.emit(self._active_project_id or "")

    def _on_markers_loaded(self, payload: object) -> None:
        seq, project_id, year, month, markers = payload  # type: ignore[misc]
        if seq == self._markers_seq and self._active_project_id == project_id and (year, month) == self._calendar.current_year_month() and isinstance(markers, dict):
            self._calendar.set_markers(markers)  # type: ignore[arg-type]

    def _update_timeline_header(self) -> None:
        dh.update_detail_timeline_header(self._timeline_title, self._clear_date_btn, self._search_query, self._selected_date)

    def _set_selected_date(self, new_date: date | None) -> None:
        self._selected_date = new_date
        self._update_timeline_header()
        if self._active_project_id is not None:
            self._load_timeline_async(self._active_project_id)

    def _on_calendar_date_selected(self, qdate: QDate) -> None:
        self._set_selected_date(dh.qdate_to_date(qdate) if qdate.isValid() else None)

    def _on_calendar_month_changed(self, year: int, month: int) -> None:
        del year, month
        if self._selected_date is not None:
            self._set_selected_date(None)
        if self._active_project_id is not None:
            self._load_markers_async(self._active_project_id)

    def _on_clear_date(self) -> None:
        self._calendar.clear_selection()
        self._set_selected_date(None)

    def _on_toggle_status(self) -> None:
        if (svc := self._project_service) is not None and self._project is not None:
            pid = self._project.id
            run_in_pool(self, self._active_workers, lambda: svc.toggle_status(pid), lambda u: isinstance(u, Project) and self._render_hero(u))

    def _on_toggle_pin(self) -> None:
        if (svc := self._project_service) is not None and self._project is not None:
            pid = self._project.id
            run_in_pool(self, self._active_workers, lambda: svc.toggle_pin(pid), lambda _p: self._refresh_active_project())

    def _on_milestone_toggled(self, item_type: str, item_id: str) -> None:
        if (svc := self._history_service) is not None:
            run_in_pool(self, self._active_workers, lambda: svc.toggle_milestone(item_type, item_id), lambda _r: self._refresh_active_project())  # type: ignore[arg-type]

    def _on_milestone_clicked(self, item_type: str, item_id: str) -> None:
        if (svc := self._history_service) is not None:
            run_in_pool(self, self._active_workers, lambda: svc.get_milestone_detail(item_type, item_id), self._show_milestone_preview)  # type: ignore[arg-type]

    def _show_milestone_preview(self, detail: object) -> None:
        if isinstance(detail, MilestoneDetail):
            self._preview_dialog = dh.show_milestone_preview_dialog(
                self, self._preview_dialog, detail, self._on_jump_to_date, self._on_milestone_toggled,
                lambda rel, pid: self._on_file_open_requested(rel, pid, ""),
                on_reveal_file=lambda rel, pid: self._on_file_reveal_requested(rel, pid, ""),
            )

    def _on_jump_to_date(self, qdate: QDate) -> None:
        if not qdate.isValid():
            return
        self._calendar.set_month(qdate.year(), qdate.month())
        self._calendar.set_selected_date(qdate)
        self._set_selected_date(dh.qdate_to_date(qdate))
        if self._active_project_id is not None:
            self._load_markers_async(self._active_project_id)

    def _render_hero(self, project: Project) -> None:
        self._project = project
        dh.render_hero_section(
            self._hero, self._pin_btn, self._project_service, project, ca.load_cover_pixmap
        )

    @Slot(object)
    def _on_project_updated(self, project: object) -> None:
        if isinstance(project, Project) and self._project is not None and project.id == self._project.id:
            self._render_hero(project)

    @Slot(object)
    def _on_observed_event(self, event: object) -> None:
        if isinstance(event, ObservedEvent) and self._active_project_id == event.project_id:
            self.refresh_project_async(self._active_project_id)

    @Slot()
    def _refresh_active_project(self) -> None:
        if self._active_project_id is not None:
            self.refresh_project_async(self._active_project_id)

    def _on_schedule_event(self) -> None:
        calendar_actions.open_create_event_dialog(
            self, self._calendar_service, self._project_service,
            initial_date=self._selected_date or date.today(), initial_project_id=self._active_project_id,
        )

    def _on_summary_reference_clicked(self, ref: object) -> None:
        dh.dispatch_summary_reference(ref, self._on_milestone_clicked, self._on_jump_to_date)

    def _on_save_custom_summary(self, custom_text: str) -> None:
        if (svc := self._summary_service) and (pid := self._active_project_id):
            run_in_pool(self, self._active_workers, lambda: svc.save_custom_summary(pid, custom_text), self._on_summary_updated)

    def _on_regenerate_summary(self) -> None:
        if (svc := self._summary_service) and (pid := self._active_project_id):
            run_in_pool(self, self._active_workers, lambda: svc.regenerate_summary(pid), self._on_summary_updated)

    def _on_summary_updated(self, view: object) -> None:
        if isinstance(view, ProjectSummaryView) and view.project_id == self._active_project_id:
            self._summary_panel.set_summary(view)

    def _on_relink_folder(self) -> None:
        if (u := project_hero.relink_project_with_dialog(self, self._relink_service, self._project)) is not None:
            self._render_hero(u)

    def _on_open_folder(self) -> None:
        dh.open_project_folder_path(self, self._project)

    def _on_export_bundle(self) -> None:
        project_hero.export_project_with_dialog(self, self._manifest_service, self._project)

    def _on_change_cover(self) -> None:
        dh.handle_detail_cover_action(self, self._active_workers, self._project_service, self._project, reset=False, on_updated=self._render_hero)  # type: ignore[arg-type]

    def _on_reset_cover(self) -> None:
        dh.handle_detail_cover_action(self, self._active_workers, self._project_service, self._project, reset=True, on_updated=self._render_hero)  # type: ignore[arg-type]

    def _dispatch_file(self, action: str, rel_path: str, project_id: str, workspace_id: str) -> None:
        dh.dispatch_detail_file_action(
            self, self._active_workers, self._history_service, self._thumbnail_service,  # type: ignore[arg-type]
            self._project, self._active_project_id, action, rel_path, project_id, workspace_id,
            self.file_missing.emit, self.info_toast.emit,
        )

    def _on_file_open_requested(self, r: str, p: str, w: str) -> None:
        self._dispatch_file("open", r, p, w)

    def _on_file_reveal_requested(self, r: str, p: str, w: str) -> None:
        self._dispatch_file("reveal", r, p, w)

    def _on_file_preview_requested(self, r: str, p: str, w: str) -> None:
        self._dispatch_file("preview", r, p, w)
