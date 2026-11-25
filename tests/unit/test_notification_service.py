"""Unit tests for Phase 5B AppSettings, NotificationService, and ToastPopup."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.config.settings import AppSettings, load_settings, save_settings
from work_memory.core.models import ObservedEvent
from work_memory.services.notification_service import NotificationPayload, NotificationService
from work_memory.ui.capture.toast_popup import ToastPopup


def test_app_settings_save_reload_and_workspace_guard(tmp_path: Path) -> None:
    """AppSettings persists to app-owned settings.json and blocks monitored workspace paths."""
    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()

    custom = AppSettings(
        new_file_notifications=False,
        repeated_save_interval=3,
        notification_duration_sec=30,
        save_reminder_minutes=15,
        minimize_to_tray_on_close=False,
        global_hotkey_enabled=False,
    )
    saved_path = save_settings(app_paths, custom)
    assert saved_path == (app_paths.base_dir / "settings.json").resolve()

    reloaded = load_settings(app_paths)
    assert reloaded == custom

    ws_root = tmp_path / "user_workspace"
    ws_root.mkdir()
    bad_paths = resolve_app_paths(ws_root / ".work_memory")
    with pytest.raises(PermissionError):
        save_settings(bad_paths, custom, workspace_roots=[ws_root])


def test_new_file_notifications_and_cooldown() -> None:
    """CREATED events emit new_file payloads and respect per-project 30s cooldown."""
    _app = QApplication.instance() or QApplication([])
    now = [100.0]
    svc = NotificationService(
        AppSettings(new_file_notifications=True, repeated_save_interval=5),
        suppress_fn=lambda _t: False,
        clock_fn=lambda: now[0],
    )
    emitted: list[NotificationPayload] = []
    svc.notification_triggered.connect(emitted.append)

    ev1 = ObservedEvent(
        workspace_id="ws-1",
        project_id="proj-1",
        rel_path="shots/s01.exr",
        event_type="created",
        occurred_at_utc="2026-05-10T10:00:00Z",
    )
    assert svc.handle_observed_event(ev1) is not None
    assert len(emitted) == 1
    assert emitted[0].kind == "new_file"
    assert emitted[0].event_id == ev1.id

    # Within 30s cooldown -> suppressed.
    now[0] = 115.0
    ev2 = ObservedEvent(
        workspace_id="ws-1",
        project_id="proj-1",
        rel_path="shots/s02.exr",
        event_type="created",
        occurred_at_utc="2026-05-10T10:00:15Z",
    )
    assert svc.handle_observed_event(ev2) is None
    assert len(emitted) == 1

    # After 30s cooldown -> fires again.
    now[0] = 135.0
    assert svc.handle_observed_event(ev2) is not None
    assert len(emitted) == 2


def test_repeated_save_counter_dedupe_and_reset() -> None:
    """MODIFIED events count saves (10s burst dedupe), fire at interval, and reset."""
    _app = QApplication.instance() or QApplication([])
    now = [10.0]
    svc = NotificationService(
        AppSettings(repeated_save_interval=3),
        suppress_fn=lambda _t: False,
        clock_fn=lambda: now[0],
    )
    emitted: list[NotificationPayload] = []
    svc.notification_triggered.connect(emitted.append)

    def _mod(ts: float) -> NotificationPayload | None:
        now[0] = ts
        return svc.handle_observed_event(
            ObservedEvent(
                workspace_id="ws-1",
                project_id="proj-1",
                rel_path="scenes/rig.ma",
                event_type="modified",
                occurred_at_utc="2026-05-10T10:00:00Z",
            )
        )

    assert _mod(10.0) is None   # save #1
    assert _mod(12.0) is None   # burst within 10s -> ignored
    assert _mod(25.0) is None   # save #2
    res = _mod(40.0)            # save #3 -> fires and resets
    assert res is not None
    assert res.kind == "repeated_save"
    assert len(emitted) == 1

    # Counter was reset; next save is #1, not #4.
    assert _mod(55.0) is None
    assert _mod(70.0) is None
    svc.reset_save_counter("proj-1")
    assert _mod(85.0) is None   # reset back to #1
    assert len(emitted) == 1


def test_timed_reminder_generic_wording_and_suppression() -> None:
    """Timed reminders use generic wording and are suppressed when idle or fullscreen."""
    _app = QApplication.instance() or QApplication([])
    suppressed = [False]
    svc = NotificationService(
        AppSettings(save_reminder_minutes=30),
        suppress_fn=lambda _t: suppressed[0],
    )
    emitted: list[NotificationPayload] = []
    svc.notification_triggered.connect(emitted.append)

    suppressed[0] = True
    assert svc.trigger_timed_reminder() is None
    assert emitted == []

    suppressed[0] = False
    payload = svc.trigger_timed_reminder()
    assert payload is not None
    assert payload.kind == "timed_reminder"
    assert payload.message == "Remember to save your work"
    assert len(emitted) == 1


def test_toast_popup_is_non_focus_stealing_and_emits_milestone() -> None:
    """ToastPopup sets WindowDoesNotAcceptFocus/WA_ShowWithoutActivating and emits milestone_requested."""
    _app = QApplication.instance() or QApplication([])
    payload = NotificationPayload(
        notif_id="n-1",
        kind="new_file",
        title="New file in Alpha",
        message="shot_01.exr",
        project_id="proj-1",
        event_id="ev-1",
        rel_path="shots/shot_01.exr",
        duration_sec=0,
    )
    toast = ToastPopup(payload)
    assert bool(toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    star_btn = toast.findChild(QPushButton, "toastMilestoneButton")
    assert star_btn is not None
    assert star_btn.focusPolicy() == Qt.FocusPolicy.NoFocus

    starred: list[NotificationPayload] = []
    toast.milestone_requested.connect(starred.append)
    QTest.mouseClick(star_btn, Qt.MouseButton.LeftButton)
    assert starred == [payload]
