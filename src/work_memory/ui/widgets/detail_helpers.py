"""Shared helpers for HistoryView and ProjectDetailView keeping views concise."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import (
    CaptureEntry,
    DayTimeline,
    MilestoneDetail,
    MilestoneItem,
    Project,
    ProjectSummaryView,
    SummaryReference,
)
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.services.history_service import HistoryService, group_observed_events
from work_memory.services.project_service import ProjectService
from work_memory.services.summary_service import SummaryService
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets import cover_actions as ca
from work_memory.ui.widgets.file_open_helper import (
    open_timeline_file_async,
    preview_timeline_file_async,
    reveal_timeline_file_async,
)
from work_memory.ui.widgets.milestone_preview_dialog import MilestonePreviewDialog


def update_detail_timeline_header(
    title_label: QLabel,
    clear_btn: QPushButton,
    search_query: str,
    selected_date: date | None,
) -> None:
    """Update the ProjectDetailView timeline title and clear-date visibility."""
    if search_query:
        title_label.setText(f'Search results for "{search_query}"')
        clear_btn.setVisible(False)
    elif selected_date is not None:
        title_label.setText(f"Activity on {selected_date.strftime('%Y-%m-%d')}")
        clear_btn.setVisible(True)
    else:
        title_label.setText("Recent activity & notes")
        clear_btn.setVisible(False)


def detail_empty_text(search_query: str, selected_date: date | None) -> str:
    """Return the calm empty-state copy for ProjectDetailView's timeline."""
    if search_query:
        return "No matching activity found."
    if selected_date is not None:
        return "No activity recorded on this date."
    return "No observed file activity recorded for this project yet."


def dispatch_summary_reference(
    ref: object,
    on_milestone: Callable[[str, str], None],
    on_jump_to_date: Callable[[QDate], None],
) -> None:
    """Route a clicked ``SummaryReference`` chip to preview dialog or calendar jump."""
    if not isinstance(ref, SummaryReference):
        return
    if ref.item_type in ("capture", "observed") and ref.item_id:
        on_milestone(ref.item_type, ref.item_id)
    elif (
        ref.item_type == "date"
        and ref.local_date
        and (qd := QDate.fromString(ref.local_date, "yyyy-MM-dd")).isValid()
    ):
        on_jump_to_date(qd)


def qdate_to_date(qdate: QDate) -> date:
    """Convert a ``QDate`` into a standard ``datetime.date``."""
    return date(qdate.year(), qdate.month(), qdate.day())


def format_day_heading(local_date: date) -> str:
    """Format a calendar date as ``Weekday, Month Day``."""
    return f"{local_date.strftime('%A')}, {local_date.strftime('%B')} {local_date.day}"


def render_matched_projects_chips(
    box: QWidget,
    layout: QVBoxLayout,
    projects: tuple[Project, ...],
    on_select: Callable[[str], None],
) -> None:
    """Populate clickable project-pill shortcuts above search results."""
    while layout.count():
        if (item := layout.takeAt(0)) is not None and (w := item.widget()) is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
    if not projects:
        box.setVisible(False)
        return
    pal = get_palette()
    hdr = QLabel(f"Matching projects \u00b7 {len(projects)}")
    hdr.setStyleSheet(f"color: {pal.section_title}; font-size: 12px; font-weight: 600;")
    layout.addWidget(hdr)
    row = QHBoxLayout()
    row.setSpacing(8)
    for proj in projects[:6]:
        btn = QPushButton(proj.name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {pal.panel_alt}; border: 1px solid {pal.border}; border-radius: 8px; color: {pal.soft}; padding: 5px 10px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {pal.hover_border}; color: {pal.text}; }}"
        )
        btn.clicked.connect(lambda _c=False, pid=proj.id: on_select(pid))
        row.addWidget(btn)
    row.addStretch(1)
    wrap = QWidget()
    wrap.setLayout(row)
    layout.addWidget(wrap)
    box.setVisible(True)


def wire_detail_calendar_timeline(
    timeline: object,
    calendar: object,
    on_milestone_toggled: Callable[[str, str], None],
    on_file_open: Callable[[str, str, str], None],
    on_edit_event: Callable[[object], None],
    on_event_status: Callable[[str, str], None],
    on_date_selected: Callable[[QDate], None],
    on_month_changed: Callable[[int, int], None],
    on_file_reveal: Callable[[str, str, str], None] | None = None,
    on_file_preview: Callable[[str, str, str], None] | None = None,
) -> None:
    """Connect timeline and calendar widget signals for ProjectDetailView."""
    timeline.milestone_toggled.connect(on_milestone_toggled)  # type: ignore[attr-defined]
    timeline.file_open_requested.connect(on_file_open)  # type: ignore[attr-defined]
    if on_file_reveal is not None:
        timeline.file_reveal_requested.connect(on_file_reveal)  # type: ignore[attr-defined]
    if on_file_preview is not None:
        timeline.file_preview_requested.connect(on_file_preview)  # type: ignore[attr-defined]
    timeline.event_edit_requested.connect(on_edit_event)  # type: ignore[attr-defined]
    timeline.event_status_requested.connect(on_event_status)  # type: ignore[attr-defined]
    calendar.date_selected.connect(on_date_selected)  # type: ignore[attr-defined]
    calendar.month_changed.connect(on_month_changed)  # type: ignore[attr-defined]


def apply_pin_button_style(pin_btn: QPushButton, is_pinned: bool) -> None:
    """Style the ProjectDetailView hero Pin button cleanly."""
    pal = get_palette()
    pin_btn.setText("Pinned" if is_pinned else "Pin")
    pin_btn.setStyleSheet(
        f"background-color: {pal.panel_alt}; color: {pal.amber}; border: 1px solid {pal.amber}; border-radius: 8px; padding: 7px 12px; font-size: 12px;"
        if is_pinned
        else f"background-color: {pal.panel_alt}; color: {pal.soft}; border: 1px solid {pal.border}; border-radius: 8px; padding: 7px 12px; font-size: 12px;"
    )


def render_hero_section(
    hero: object,
    pin_btn: QPushButton,
    proj_svc: ProjectService | None,
    project: Project,
    cover_loader: Callable[[Path | None], object],
) -> None:
    """Resolve cover image and populate ``ProjectHeroSection`` and ``pin_btn``."""
    cover_path = proj_svc.get_project_cover_path(project) if proj_svc is not None else None
    hero.render(project, cover_pixmap=cover_loader(cover_path))  # type: ignore[attr-defined]
    apply_pin_button_style(pin_btn, project.is_pinned)


def insert_hero_pin_button(hero: object, pin_btn: QPushButton) -> None:
    """Insert the Hero Pin button just before the trailing stretch in hero actions."""
    hero_lay = hero.hero_layout  # type: ignore[attr-defined]
    if (info_col := hero_lay.itemAt(1).layout()) is not None and (
        actions_row := info_col.itemAt(3).layout()
    ) is not None:
        actions_row.insertWidget(actions_row.count() - 1, pin_btn)


def open_project_folder_path(parent: QWidget, project: Project | None) -> None:
    """Open ``project.abs_path`` in Windows Explorer or inform the user if missing."""
    if project is None or not project.abs_path:
        return
    if not (target := Path(project.abs_path)).is_dir():
        QMessageBox.information(
            parent,
            "Folder unavailable",
            f"The project folder could not be found on disk:\n{target}",
        )
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def show_milestone_preview_dialog(
    parent: QWidget,
    previous: MilestonePreviewDialog | None,
    detail: MilestoneDetail,
    on_jump_to_date: Callable[[QDate], None],
    on_unstar: Callable[[str, str], None],
    on_open_file: Callable[[str, str], None],
    on_reveal_file: Callable[[str, str], None] | None = None,
) -> MilestonePreviewDialog:
    """Replace any open preview dialog and show ``detail``."""
    if previous is not None:
        previous.close()
        previous.deleteLater()
    dlg = MilestonePreviewDialog(detail, parent)
    dlg.jump_to_date_requested.connect(on_jump_to_date)
    dlg.unstar_requested.connect(on_unstar)
    dlg.file_open_requested.connect(on_open_file)
    if on_reveal_file is not None:
        dlg.file_reveal_requested.connect(on_reveal_file)
    dlg.show()
    return dlg


def fetch_project_detail_bundle(
    seq: int,
    project_id: str,
    query: str,
    sel_date: date | None,
    proj_svc: ProjectService | None,
    hist_svc: HistoryService | None,
    sum_svc: SummaryService | None,
) -> tuple[
    int,
    Project | None,
    DayTimeline,
    tuple[CaptureEntry, ...],
    list[MilestoneItem],
    ProjectSummaryView | None,
]:
    """Fetch project metadata, summary, milestones, notes, and timeline off the GUI thread."""
    proj = proj_svc.get_project(project_id) if proj_svc is not None else None
    summary = (
        sum_svc.get_project_summary(project_id)
        if (sum_svc is not None and proj is not None)
        else None
    )
    if hist_svc is not None:
        recent = hist_svc.get_recent_timeline(project_id, limit=20)
        milestones = hist_svc.get_project_milestones(project_id)
        if query:
            tl = hist_svc.search(query, project_id=project_id).timeline or DayTimeline(
                local_date=None
            )
        elif sel_date is not None:
            tl = hist_svc.get_day_timeline(sel_date, project_id=project_id)
        else:
            tl = recent
        return seq, proj, tl, recent.captures, milestones, summary

    events = proj_svc.list_project_events(project_id, limit=50) if proj_svc is not None else []
    if query:
        ql = query.lower()
        events = [
            e
            for e in events
            if ql in f"{e.rel_path} {e.old_rel_path or ''} {e.event_type}".lower()
        ]
    names = {proj.id: proj.name} if proj else {}
    tl = DayTimeline(
        local_date=None, observed_groups=group_observed_events(events, names)
    )
    return seq, proj, tl, (), [], summary


def handle_detail_cover_action(
    owner: QWidget,
    workers: set[object],
    proj_svc: ProjectService | None,
    project: Project | None,
    *,
    reset: bool,
    on_updated: Callable[[Project], None],
) -> None:
    """Invoke Change Cover or Reset Cover asynchronously for ``ProjectDetailView``."""
    if project is None:
        return
    if reset:
        ca.run_clear_cover_async(
            owner, workers, proj_svc, project.id,
            on_done=lambda u: isinstance(u, Project) and on_updated(u),
        )
    elif (chosen := ca.choose_cover_image_dialog(owner, project.name)) is not None:
        ca.run_set_cover_async(
            owner, workers, proj_svc, project.id, chosen,
            on_done=lambda u: isinstance(u, Project) and on_updated(u),
        )


def dispatch_detail_file_action(
    owner: QWidget,
    workers: set[object],
    hist_svc: HistoryService | None,
    thumb_svc: ThumbnailService | None,
    project: Project | None,
    active_project_id: str | None,
    action: str,
    rel_path: str,
    project_id: str,
    workspace_id: str,
    on_missing: Callable[[str], None],
    on_info: Callable[[str, str], None],
) -> None:
    """Dispatch open, reveal, or media-preview file requests for ``ProjectDetailView``."""
    eff_pid = project_id or (active_project_id or "")
    if action == "open":
        open_timeline_file_async(
            owner, workers, hist_svc, rel_path, eff_pid, workspace_id, on_missing, fallback_project=project
        )
    elif action == "reveal":
        reveal_timeline_file_async(
            owner, workers, hist_svc, rel_path, eff_pid, workspace_id, on_info, fallback_project=project
        )
    elif action == "preview":
        preview_timeline_file_async(
            owner, workers, hist_svc, thumb_svc, rel_path, eff_pid, workspace_id,
            on_missing, on_info, fallback_project=project,
        )
