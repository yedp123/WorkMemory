"""Unit tests for Phase 7: Calendar Events & Sleep-Safe Desktop Reminders."""

from __future__ import annotations

from datetime import UTC, date, time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QThreadPool
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import CaptureEntry, ObservedEvent, Project, Workspace
from work_memory.services.calendar_service import CalendarService
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.notification_service import NotificationPayload
from work_memory.services.project_service import ProjectService
from work_memory.storage.database import Database
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.capture.toast_popup import ToastPopup
from work_memory.ui.main_window import MainWindow
from work_memory.ui.views.history_view import HistoryView
from work_memory.ui.views.project_detail_view import ProjectDetailView
from work_memory.ui.widgets.event_dialog import EventDialog
from work_memory.ui.widgets.timeline_widget import TimelineWidget


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _setup_env(
    tmp_path: Path,
) -> tuple[Database, EventBus, Workspace, Project, Project, CalendarService, HistoryService]:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(tmp_path / "studio")))
    proj_a = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Alpha", rel_path="Alpha"))
    proj_b = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Beta", rel_path="Beta"))
    bus = EventBus()
    cal_svc = CalendarService(db, bus, tz=UTC)
    hist_svc = HistoryService(db, bus, app_paths=paths, tz=UTC)
    return db, bus, ws, proj_a, proj_b, cal_svc, hist_svc


def test_calendar_crud_status_and_fts_search(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, _bus, _ws, proj_a, _proj_b, cal_svc, hist_svc = _setup_env(tmp_path)

    ev = cal_svc.create_event(
        title="Client sculpt review",
        local_date=date(2026, 11, 25),
        local_time=time(15, 0),
        project_id=proj_a.id,
        reminder_minutes=10,
        description="Zoom link in Slack",
    )
    assert ev.event_at_utc == "2026-11-25T15:00:00Z"
    assert ev.remind_at_utc == "2026-11-25T14:50:00Z"
    assert ev.status == "scheduled"
    assert any(e.id == ev.id for e in hist_svc.search("sculpt").calendar_events)

    updated = cal_svc.update_event(
        ev.id,
        title="Final rig signoff",
        local_date=date(2026, 11, 25),
        local_time=time(16, 30),
        project_id=proj_a.id,
        reminder_minutes=30,
        description="Prepare turntable",
    )
    assert updated is not None
    assert updated.event_at_utc == "2026-11-25T16:30:00Z"
    assert updated.remind_at_utc == "2026-11-25T16:00:00Z"
    assert any(e.id == ev.id for e in hist_svc.search("turntable").calendar_events)
    assert not any(e.id == ev.id for e in hist_svc.search("sculpt").calendar_events)

    completed = cal_svc.set_status(ev.id, "completed")
    assert completed is not None
    assert completed.status == "completed"

    cancelled = cal_svc.set_status(ev.id, "cancelled")
    assert cancelled is not None
    assert cancelled.status == "cancelled"

    assert cal_svc.delete_event(ev.id) is True
    assert cal_svc.get_event(ev.id) is None
    assert hist_svc.search("turntable").calendar_events == ()


def test_history_markers_and_timeline_separate_calendar_events(tmp_path: Path) -> None:
    _ensure_qapp()
    db, _bus, ws, proj_a, proj_b, cal_svc, hist_svc = _setup_env(tmp_path)

    ObservedEventRepository(db).insert_batch(
        [ObservedEvent(ws.id, "Alpha/rig.ma", "modified", "2026-11-24T10:00:00Z", project_id=proj_a.id)]
    )
    CaptureRepository(db).create(
        CaptureEntry(project_id=proj_a.id, note_text="Note text", captured_at_utc="2026-11-24T11:00:00Z")
    )
    ev_a = cal_svc.create_event(
        title="Alpha sync",
        local_date=date(2026, 11, 24),
        local_time=time(14, 0),
        project_id=proj_a.id,
    )
    ev_b = cal_svc.create_event(
        title="Beta milestone",
        local_date=date(2026, 11, 26),
        local_time=time(9, 0),
        project_id=proj_b.id,
    )

    global_markers = hist_svc.get_month_markers(2026, 11)
    assert global_markers[24].has_observed is True
    assert global_markers[24].has_captures is True
    assert global_markers[24].has_events is True
    assert global_markers[26].has_events is True
    assert global_markers[26].has_observed is False

    proj_a_markers = hist_svc.get_month_markers(2026, 11, project_id=proj_a.id)
    assert proj_a_markers[24].has_events is True
    assert 26 not in proj_a_markers

    day_tl = hist_svc.get_day_timeline(date(2026, 11, 24))
    assert len(day_tl.observed_groups) == 1
    assert len(day_tl.captures) == 1
    assert [e.id for e in day_tl.scheduled_events] == [ev_a.id]

    day_26_b = hist_svc.get_day_timeline(date(2026, 11, 26), project_id=proj_b.id)
    assert [e.id for e in day_26_b.scheduled_events] == [ev_b.id]


def test_sleep_safe_reminders_fire_once_and_never_auto_complete_past_events(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, _bus, _ws, proj_a, _proj_b, cal_svc, _hist_svc = _setup_env(tmp_path)

    emitted: list[NotificationPayload] = []
    cal_svc.reminder_triggered.connect(emitted.append)

    ev_due = cal_svc.create_event(
        title="Client meeting",
        local_date=date(2026, 11, 24),
        local_time=time(15, 0),
        project_id=proj_a.id,
        reminder_minutes=10,
    )
    ev_done = cal_svc.create_event(
        title="Already done",
        local_date=date(2026, 11, 24),
        local_time=time(15, 0),
        project_id=proj_a.id,
        reminder_minutes=10,
    )
    cal_svc.set_status(ev_done.id, "completed")

    ev_cancelled = cal_svc.create_event(
        title="Cancelled call",
        local_date=date(2026, 11, 24),
        local_time=time(15, 0),
        project_id=proj_a.id,
        reminder_minutes=10,
    )
    cal_svc.set_status(ev_cancelled.id, "cancelled")

    # Before remind_at_utc (14:50:00Z): nothing fires
    assert cal_svc.check_due_reminders("2026-11-24T14:49:59Z") == []

    # Simulate waking from sleep well past event_at_utc (15:30:00Z): fires once for ev_due only
    fired = cal_svc.check_due_reminders("2026-11-24T15:30:00Z")
    assert len(fired) == 1
    assert fired[0].kind == "calendar_event"
    assert fired[0].event_id == ev_due.id
    assert "Client meeting starts in 10 minutes" in fired[0].title
    assert "Alpha" in fired[0].title

    # Repeated ticks must never duplicate
    assert cal_svc.check_due_reminders("2026-11-24T15:35:00Z") == []

    # Past scheduled event MUST remain 'scheduled' until explicit user action
    reloaded = cal_svc.get_event(ev_due.id)
    assert reloaded is not None
    assert reloaded.notified_at_utc == "2026-11-24T15:30:00Z"
    assert reloaded.status == "scheduled"


def test_calendar_ui_toast_views_timeline_and_event_dialog(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, bus, _ws, proj_a, _proj_b, cal_svc, hist_svc = _setup_env(tmp_path)

    payload = NotificationPayload(
        notif_id="n1",
        kind="calendar_event",
        title="Client meeting starts in 10 minutes \u2014 Alpha",
        message="Scheduled for 15:00",
        project_id=proj_a.id,
        event_id="e1",
        rel_path=None,
        duration_sec=10,
    )
    toast = ToastPopup(payload)
    assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert bool(toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert toast.findChild(QPushButton, "toastOpenProjectButton") is not None
    assert toast.findChild(QPushButton, "toastDismissActionButton") is not None
    assert toast.findChild(QPushButton, "toastAddNoteButton") is None

    hv = HistoryView(hist_svc, bus, calendar_service=cal_svc)
    assert hv.findChild(QPushButton, "scheduleEventButton") is not None

    pdv = ProjectDetailView(history_service=hist_svc, event_bus=bus, calendar_service=cal_svc)
    assert pdv.findChild(QPushButton, "detailAddEventButton") is not None

    ev = cal_svc.create_event(
        title="Lookdev review",
        local_date=date(2026, 11, 24),
        local_time=time(15, 0),
        project_id=proj_a.id,
    )
    tl = hist_svc.get_day_timeline(date(2026, 11, 24))
    tw = TimelineWidget()
    tw.set_timeline(tl)
    assert tw.findChild(QPushButton, "eventEditButton") is not None
    assert tw.findChild(QPushButton, "eventCompleteButton") is not None
    assert tw.findChild(QPushButton, "eventCancelButton") is not None

    dlg = EventDialog([proj_a], event=ev)
    title_input = dlg.findChild(QLineEdit, "eventTitleInput")
    assert title_input is not None
    assert title_input.text() == "Lookdev review"
    assert dlg.findChild(QPushButton, "eventDeleteButton") is not None

    dlg.close()
    tw.close()
    pdv.close()
    hv.close()
    toast.close()


def _flush_ui() -> None:
    for _ in range(6):
        QThreadPool.globalInstance().waitForDone(2000)
        QCoreApplication.processEvents()


def test_mainwindow_renders_all_three_events_with_nonzero_geometry(tmp_path: Path) -> None:
    _ensure_qapp()
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(tmp_path / "studio")))
    proj = ProjectRepository(db).create(Project(workspace_id=ws.id, name="test", rel_path="test"))
    bus = EventBus()
    ps = ProjectService(db, bus)
    hs = HistoryService(db, bus, app_paths=paths)
    cs = CaptureService(db, paths, bus)
    cal = CalendarService(db, bus)

    win = MainWindow(bus, paths, None, ps, hs, cs, None, None, cal)
    win.show()
    _flush_ui()

    win._open_project_detail(proj.id)
    _flush_ui()

    today = date.today()
    for idx, hr in enumerate((15, 16, 17), start=1):
        cal.create_event(
            title=f"Event {idx}",
            local_date=today,
            local_time=time(hr, 0),
            project_id=proj.id,
        )
        _flush_ui()

    pdv_btns = win._project_detail_view._timeline.findChildren(QPushButton, "eventEditButton")
    assert len(pdv_btns) == 3
    assert all(b.isVisible() and b.width() > 0 and b.height() > 0 for b in pdv_btns)

    win._show_page("history")
    _flush_ui()
    hv_btns = win._history_view._timeline.findChildren(QPushButton, "eventEditButton")
    assert len(hv_btns) == 3
    assert all(b.isVisible() and b.width() > 0 and b.height() > 0 for b in hv_btns)
    win.close()


def test_reopen_completed_or_cancelled_event_resets_reminder_and_fires_again(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, _bus, _ws, proj_a, _proj_b, cal_svc, _hist_svc = _setup_env(tmp_path)

    ev = cal_svc.create_event(
        title="Postponable review",
        local_date=date(2026, 11, 24),
        local_time=time(15, 0),
        project_id=proj_a.id,
        reminder_minutes=10,
    )
    assert len(cal_svc.check_due_reminders("2026-11-24T14:55:00Z")) == 1
    cal_svc.set_status(ev.id, "completed")

    dlg = EventDialog([proj_a], event=cal_svc.get_event(ev.id))
    status_combo = dlg.findChild(QComboBox, "eventStatusCombo")
    assert status_combo is not None
    assert status_combo.currentData() == "completed"
    idx = status_combo.findData("scheduled")
    assert idx >= 0
    status_combo.setCurrentIndex(idx)
    dlg._on_save()
    assert dlg.form_data is not None
    assert dlg.form_data.status == "scheduled"
    dlg.close()

    reopened = cal_svc.update_event(
        ev.id,
        title="Postponable review",
        local_date=date(2026, 11, 24),
        local_time=time(17, 0),
        project_id=proj_a.id,
        reminder_minutes=10,
        status="scheduled",
    )
    assert reopened is not None
    assert reopened.status == "scheduled"
    assert reopened.notified_at_utc is None
    assert reopened.remind_at_utc == "2026-11-24T16:50:00Z"
    assert cal_svc.check_due_reminders("2026-11-24T16:49:00Z") == []
    assert len(cal_svc.check_due_reminders("2026-11-24T16:51:00Z")) == 1
