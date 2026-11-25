"""Unit and UI tests for Phase 3 History calendar, timeline, search, and card badge."""

from __future__ import annotations

from datetime import UTC, date, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QThreadPool
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.ids import new_id
from work_memory.core.models import (
    CalendarEvent,
    CaptureEntry,
    DayMarkers,
    DayTimeline,
    ObservedEvent,
    Project,
    Workspace,
)
from work_memory.services.history_service import HistoryService
from work_memory.services.project_service import ProjectService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.main_window import MainWindow
from work_memory.ui.widgets.month_calendar import MonthCalendarWidget
from work_memory.ui.widgets.project_card import (
    STATUS_COMPLETED_COLOR,
    STATUS_ONGOING_COLOR,
    ProjectCard,
)
from work_memory.ui.widgets.timeline_widget import TimelineWidget


def _wait_qt_pool() -> None:
    for _ in range(4):
        QThreadPool.globalInstance().waitForDone(3000)
        QCoreApplication.processEvents()


def _seed_capture(db: Database, cap: CaptureEntry, *, title: str = "Note") -> None:
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO capture_entries (id, project_id, rel_path, note_text, transcript_text, "
            "audio_retention, captured_at_utc, created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (cap.id, cap.project_id, cap.rel_path, cap.note_text, cap.transcript_text, cap.audio_retention, cap.captured_at_utc, cap.created_at_utc, cap.updated_at_utc),
        )
        conn.execute(
            "INSERT INTO fts_search (entity_type, entity_id, project_id, title, body, rel_path) VALUES (?, ?, ?, ?, ?, ?);",
            ("capture", cap.id, cap.project_id or "", title, f"{cap.note_text} {cap.transcript_text}", cap.rel_path or ""),
        )


def _seed_calendar_event(db: Database, ev: CalendarEvent) -> None:
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO calendar_events (id, project_id, title, description, starts_at_utc, "
            "status, remind_at_utc, notified_at_utc, created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (ev.id, ev.project_id, ev.title, ev.description, ev.starts_at_utc, ev.status, ev.remind_at_utc, ev.notified_at_utc, ev.created_at_utc, ev.updated_at_utc),
        )


def test_local_date_to_utc_boundaries_map_late_night_saves_to_true_local_date(tmp_path: Path) -> None:
    db = Database(tmp_path / "work_memory.db")
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(tmp_path / "studio")))
    proj = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Rig", rel_path="Rig"))

    # 2026-11-23 00:30+08:00 == 2026-11-22T16:30:00Z; 2026-11-23 23:45+08:00 == 2026-11-23T15:45:00Z
    # 2026-11-23 23:30-05:00 == 2026-11-24T04:30:00Z; 2026-11-30 23:30-05:00 == 2026-12-01T04:30:00Z
    ObservedEventRepository(db).insert_batch([
        ObservedEvent(ws.id, "Rig/early_plus8.blend", "modified", "2026-11-22T16:30:00Z", project_id=proj.id),
        ObservedEvent(ws.id, "Rig/late_plus8.blend", "modified", "2026-11-23T15:45:00Z", project_id=proj.id),
        ObservedEvent(ws.id, "Rig/late_minus5.blend", "modified", "2026-11-24T04:30:00Z", project_id=proj.id),
        ObservedEvent(ws.id, "Rig/month_end_minus5.blend", "created", "2026-12-01T04:30:00Z", project_id=proj.id),
    ])

    svc_p8 = HistoryService(db, tz=timezone(timedelta(hours=8)))
    tl_p8_23 = svc_p8.get_day_timeline(date(2026, 11, 23))
    assert {ev.rel_path for grp in tl_p8_23.observed_groups for ev in grp.events} == {"Rig/early_plus8.blend", "Rig/late_plus8.blend"}
    assert svc_p8.get_day_timeline(date(2026, 11, 22)).observed_groups == ()

    svc_m5 = HistoryService(db, tz=timezone(timedelta(hours=-5)))
    tl_m5_23 = svc_m5.get_day_timeline(date(2026, 11, 23))
    assert {ev.rel_path for grp in tl_m5_23.observed_groups for ev in grp.events} == {"Rig/late_plus8.blend", "Rig/late_minus5.blend"}
    tl_m5_22 = svc_m5.get_day_timeline(date(2026, 11, 22))
    assert {ev.rel_path for grp in tl_m5_22.observed_groups for ev in grp.events} == {"Rig/early_plus8.blend"}
    assert svc_m5.get_day_timeline(date(2026, 11, 24)).observed_groups == ()
    assert svc_m5.get_month_markers(2026, 11)[30].has_observed is True
    assert svc_m5.get_month_markers(2026, 12) == {}


def test_month_markers_and_day_timeline_separation_and_grouping(tmp_path: Path) -> None:
    db = Database(tmp_path / "work_memory.db")
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Work", root_path=str(tmp_path / "work")))
    proj_a = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Alpha", rel_path="Alpha"))
    proj_b = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Beta", rel_path="Beta"))

    ObservedEventRepository(db).insert_batch([
        ObservedEvent(ws.id, "Alpha/f1.py", "modified", "2026-11-23T09:00:00Z", project_id=proj_a.id),
        ObservedEvent(ws.id, "Alpha/f2.py", "modified", "2026-11-23T09:00:30Z", project_id=proj_a.id),
        ObservedEvent(ws.id, "Alpha/f3.py", "created", "2026-11-23T09:01:00Z", project_id=proj_a.id),
        ObservedEvent(ws.id, "Alpha/f4.py", "modified", "2026-11-23T09:01:30Z", project_id=proj_a.id),
        ObservedEvent(ws.id, "Alpha/f5.py", "modified", "2026-11-23T09:02:00Z", project_id=proj_a.id),
        ObservedEvent(ws.id, "Alpha/afternoon.py", "modified", "2026-11-23T12:15:00Z", project_id=proj_a.id),
        ObservedEvent(ws.id, "Beta/scene.blend", "modified", "2026-11-23T09:01:20Z", project_id=proj_b.id),
        ObservedEvent(ws.id, "Alpha/base.txt", "created", "2026-11-23T08:00:00Z", project_id=proj_a.id, is_baseline=True),
        ObservedEvent(ws.id, "Beta/prev.blend", "modified", "2026-11-20T10:00:00Z", project_id=proj_b.id),
    ])
    _seed_capture(db, CaptureEntry(project_id=proj_a.id, rel_path="Alpha/f1.py", note_text="Checked export", captured_at_utc="2026-11-23T11:00:00Z"))
    _seed_calendar_event(db, CalendarEvent(project_id=proj_b.id, title="Client sync", starts_at_utc="2026-11-24T15:00:00Z"))

    svc = HistoryService(db, tz=UTC)
    gm = svc.get_month_markers(2026, 11)
    assert gm[20] == DayMarkers(has_observed=True, has_captures=False, has_events=False)
    assert gm[23] == DayMarkers(has_observed=True, has_captures=True, has_events=False)
    assert gm[24] == DayMarkers(has_observed=False, has_captures=False, has_events=True)
    am = svc.get_month_markers(2026, 11, project_id=proj_a.id)
    assert am == {23: DayMarkers(has_observed=True, has_captures=True, has_events=False)}

    tl = svc.get_day_timeline(date(2026, 11, 23))
    assert [(g.project_name, len(g.events)) for g in tl.observed_groups] == [("Alpha", 1), ("Alpha", 5), ("Beta", 1)]
    assert [c.note_text for c in tl.captures] == ["Checked export"]
    assert tl.scheduled_events == ()
    tl_24 = svc.get_day_timeline(date(2026, 11, 24))
    assert tl_24.observed_groups == () and [e.title for e in tl_24.scheduled_events] == ["Client sync"]


def test_search_handles_special_characters_without_fts5_syntax_errors(tmp_path: Path) -> None:
    db = Database(tmp_path / "work_memory.db")
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Work", root_path=r"C:\Work"))
    proj = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="Hero Rig", rel_path="Hero_Rig", abs_path=r"C:\Work\Hero_Rig", description="Character rigging")
    )
    other = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Other", rel_path="Other"))
    ObservedEventRepository(db).insert_batch([
        ObservedEvent(ws.id, "Hero_Rig/scenes/hero-v2.mb", "modified", "2026-11-23T10:00:00Z", project_id=proj.id),
        ObservedEvent(ws.id, "Other/scenes/hero-v2.mb", "created", "2026-11-23T10:05:00Z", project_id=other.id),
    ])
    _seed_capture(
        db,
        CaptureEntry(id=new_id(), project_id=proj.id, rel_path="Hero_Rig/scenes/hero-v2.mb", note_text='Verify "quoted" weight skinning', captured_at_utc="2026-11-23T10:10:00Z"),
        title="Skin weights",
    )

    svc = HistoryService(db, tz=UTC)
    assert len(svc.search("hero-v2.mb").observed_events) == 2
    assert [e.project_id for e in svc.search("hero-v2.mb", project_id=proj.id).observed_events] == [proj.id]
    assert [p.id for p in svc.search("C:\\Work\\").projects] == [proj.id]
    assert len(svc.search('"quoted"').captures) == 1
    for tricky in ("AND OR NOT NEAR", "col:val -neg +pos * ^ ()", "---", '"""', ":::", ""):
        assert svc.search(tricky).query == tricky.strip()


def test_ui_card_badge_calendar_timeline_and_mainwindow_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    ws_root = tmp_path / "Work"
    p_dir_a, p_dir_b = ws_root / "Action_Director", ws_root / "Archive_Book"
    (p_dir_a / "scenes").mkdir(parents=True)
    p_dir_b.mkdir(parents=True)

    proj_a = Project(workspace_id="ws1", name="Action Director", rel_path="Action_Director", status="ongoing", last_activity_utc="2026-11-23T10:00:00Z")
    proj_b = Project(workspace_id="ws1", name="Archive Book", rel_path="Archive_Book", status="completed", last_activity_utc="2026-11-20T10:00:00Z")
    card_a, card_b = ProjectCard(proj_a), ProjectCard(proj_b)
    assert card_a._status_badge.parent() is card_a._cover
    assert STATUS_ONGOING_COLOR in card_a._status_label.styleSheet()
    assert STATUS_COMPLETED_COLOR in card_b._status_label.styleSheet()
    bottom_texts = [lbl.text() for lbl in card_a.findChildren(QLabel) if lbl is not card_a._status_label]
    assert all("Ongoing" not in t and "Completed" not in t for t in bottom_texts)

    picked: list[QDate] = []
    months: list[tuple[int, int]] = []
    cal_widget = MonthCalendarWidget(initial_date=QDate(2026, 11, 23))
    cal_widget.date_selected.connect(picked.append)
    cal_widget.month_changed.connect(lambda y, m: months.append((y, m)))
    cal_widget._next_btn.click()
    assert months == [(2026, 12)] and picked[-1] == QDate(2026, 12, 1)

    tl_widget = TimelineWidget()
    tl_widget.set_timeline(DayTimeline(local_date=None))
    assert tl_widget.findChild(QLabel, "timelineEmptyLabel") is not None

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    ws_svc = WorkspaceService(db, bus, window_ms=150)
    proj_svc = ProjectService(db, bus, workspace_service=ws_svc)
    ws_svc.set_project_service(proj_svc)
    hist_svc = HistoryService(db, bus)

    ws_svc.add_workspace(ws_root, background_scan=False)
    reg_a = proj_svc.register_existing_project(p_dir_a, name="Action Director")
    today_local = date.today()
    today_noon_utc = f"{today_local.strftime('%Y-%m-%d')}T12:00:00Z"
    ObservedEventRepository(db).insert_batch([
        ObservedEvent(reg_a.workspace_id, f"Action_Director/scenes/hero-v{i}.mb", "modified", today_noon_utc, project_id=reg_a.id)
        for i in range(1, 6)
    ])

    win = MainWindow(bus, app_paths, workspace_service=ws_svc, project_service=proj_svc, history_service=hist_svc)
    win.show()
    try:
        _wait_qt_pool()
        win._history_tab.click()
        _wait_qt_pool()
        assert win._stack.currentWidget() is win._history_view
        cal = win._history_view.findChild(MonthCalendarWidget)
        assert cal is not None and (tb := cal.day_button(today_local.day)) is not None and tb.markers.has_observed
        assert win._history_view._today_tag.isVisible() is True

        more_btn = win._history_view.findChild(QPushButton, "moreFilesButton")
        assert more_btn is not None and more_btn.text() == "+ Show 2 more files"
        more_btn.click()
        assert more_btn.text() == "\u2212 Show fewer files"
        more_btn.click()
        assert more_btn.text() == "+ Show 2 more files"

        files_hdr = win._history_view.findChild(QPushButton, "timelineSection_files")
        assert files_hdr is not None and (sec := files_hdr.parentWidget()) is not None
        assert sec.is_expanded is True  # type: ignore[attr-defined]
        files_hdr.click()
        assert sec.is_expanded is False  # type: ignore[attr-defined]
        files_hdr.click()
        assert sec.is_expanded is True  # type: ignore[attr-defined]

        win._search_input.setText("hero-v2.mb")
        _wait_qt_pool()
        assert "Search results" in win._history_view._day_heading.text()

        win._search_input.setText("")
        win._open_project_detail(reg_a.id)
        _wait_qt_pool()
        assert win._stack.currentWidget() is win._project_detail_view
        detail_day_btn = win._project_detail_view._calendar.day_button(today_local.day)
        assert detail_day_btn is not None and detail_day_btn.markers.has_observed is True
        detail_day_btn.click()
        _wait_qt_pool()
        assert win._project_detail_view._clear_date_btn.isVisible() is True
        win._project_detail_view._clear_date_btn.click()
        _wait_qt_pool()
        assert win._project_detail_view._clear_date_btn.isVisible() is False

        win._search_input.setText("hero-v3.mb")
        _wait_qt_pool()
        assert "Search results" in win._project_detail_view._timeline_title.text()
    finally:
        cal_widget.close()
        win.close()
        ws_svc.shutdown()
        app.processEvents()


def test_collapse_repeated_file_saves_in_timeline() -> None:
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from work_memory.core.models import DayTimeline, ObservedGroup
    from work_memory.ui.widgets.timeline_format import collapse_group_events
    from work_memory.ui.widgets.timeline_widget import TimelineWidget

    app = QApplication.instance() or QApplication([])
    events = tuple(
        ObservedEvent(
            workspace_id="ws1",
            project_id="p1",
            rel_path="scenes/Burger_Mold_v12.blend",
            event_type="modified",
            occurred_at_utc=f"2026-11-25T15:{minute:02d}:00Z",
        )
        for minute in (8, 5, 3, 1)
    )
    collapsed = collapse_group_events(events)
    assert len(collapsed) == 1
    assert collapsed[0].count == 4
    assert collapsed[0].latest_event.occurred_at_utc == "2026-11-25T15:08:00Z"
    assert collapsed[0].first_occurred_at_utc == "2026-11-25T15:01:00Z"

    group = ObservedGroup(
        project_id="p1",
        project_name="Burger",
        occurred_at_utc="2026-11-25T15:08:00Z",
        local_date_label="2026-11-25",
        local_time_label="15:08",
        events=events,
    )
    widget = TimelineWidget()
    widget.set_timeline(DayTimeline(local_date=date(2026, 11, 25), observed_groups=(group,)))
    try:
        rows = widget.findChildren(QWidget, "timelineFileRow")
        assert len(rows) == 1
        labels = [lbl.text() for lbl in rows[0].findChildren(QLabel)]
        assert any("4 changes" in txt for txt in labels)
    finally:
        widget.close()
        app.processEvents()
