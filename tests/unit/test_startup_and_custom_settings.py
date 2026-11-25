"""Unit tests for Phase 9B startup registry, single-instance guard, and custom settings."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QSpinBox

from work_memory.config.paths import resolve_app_paths
from work_memory.config.settings import (
    DEFAULT_REMINDER_MESSAGE,
    AppSettings,
    load_settings,
    save_settings,
)
from work_memory.core.models import ObservedEvent
from work_memory.services.bootstrap_service import configure_logging
from work_memory.services.notification_service import NotificationPayload, NotificationService
from work_memory.services.startup_service import (
    STARTUP_RUN_KEY,
    StartupService,
    build_startup_command,
)
from work_memory.ui.single_instance import SingleInstanceGuard
from work_memory.ui.views.settings_view import SettingsView


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


class _FakeRegistry:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_writes = fail_writes

    def get_value(self, subkey: str, name: str) -> str | None:
        return self.values.get((subkey, name))

    def set_value(self, subkey: str, name: str, value: str) -> None:
        if self.fail_writes:
            raise OSError("Registry write denied")
        self.values[(subkey, name)] = value

    def delete_value(self, subkey: str, name: str) -> None:
        if self.fail_writes:
            raise OSError("Registry delete denied")
        self.values.pop((subkey, name), None)


def test_build_startup_command_variants(tmp_path: Path) -> None:
    """Selects pythonw.exe in venv dev mode, falls back to python.exe, and supports frozen exe."""
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    py_exe = scripts / "python.exe"
    pyw_exe = scripts / "pythonw.exe"
    py_exe.write_bytes(b"")

    fallback_cmd = build_startup_command(executable=py_exe, is_frozen=False)
    assert fallback_cmd == f'"{py_exe}" -m work_memory.main --minimized'

    pyw_exe.write_bytes(b"")
    pyw_cmd = build_startup_command(executable=py_exe, is_frozen=False)
    assert pyw_cmd == f'"{pyw_exe}" -m work_memory.main --minimized'

    frozen_exe = tmp_path / "dist" / "WorkMemory.exe"
    assert build_startup_command(executable=frozen_exe, is_frozen=True) == f'"{frozen_exe}" --minimized'


def test_startup_service_mocked_registry_and_error_handling(tmp_path: Path) -> None:
    """StartupService reads/writes HKCU Run via injectable backend and handles errors."""
    reg = _FakeRegistry()
    svc = StartupService(reg, command_builder=lambda: '"C:\\App\\pythonw.exe" -m work_memory.main --minimized')

    assert svc.is_startup_enabled() is False
    assert svc.set_startup_enabled(True) is True
    assert svc.is_startup_enabled() is True
    assert reg.values[(STARTUP_RUN_KEY, "WorkMemory")].endswith("--minimized")

    assert svc.set_startup_enabled(False) is True
    assert svc.is_startup_enabled() is False

    failing = StartupService(_FakeRegistry(fail_writes=True))
    assert failing.set_startup_enabled(True) is False
    assert failing.set_startup_enabled(False) is False

    # Windowless pythonw.exe has sys.stderr = None; configure_logging must still work.
    orig_handlers = list(logging.getLogger().handlers)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", None)
            configure_logging(tmp_path / "logs")
            assert (tmp_path / "logs" / "work_memory.log").is_file()
    finally:
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        for h in orig_handlers:
            root.addHandler(h)


def test_single_instance_guard_signals_primary_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second instance notifies primary via QLocalSocket and primary releases on close."""
    _ensure_qapp(monkeypatch)
    server_name = f"WorkMemory_Test_{uuid4().hex}"
    primary = SingleInstanceGuard(server_name=server_name)
    secondary = SingleInstanceGuard(server_name=server_name)
    activated: list[bool] = []
    primary.activate_requested.connect(lambda: activated.append(True))

    try:
        assert primary.acquire() is True
        assert primary.is_primary is True
        assert secondary.acquire() is False
        assert secondary.is_primary is False

        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        while not activated:
            QCoreApplication.processEvents()
            if activated:
                break
            loop.exec()
            break
        assert activated == [True]
    finally:
        secondary.close()
        primary.close()

    reclaimed = SingleInstanceGuard(server_name=server_name)
    try:
        assert reclaimed.acquire() is True
    finally:
        reclaimed.close()


def test_custom_intervals_persist_and_drive_notification_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom intervals persist in settings.json and configure NotificationService."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()

    custom = AppSettings(
        repeated_save_interval=7,
        notification_duration_sec=45,
        save_reminder_minutes=12,
        save_reminder_message="  Save Blender scene  ",
        launch_at_startup=True,
    )
    save_settings(paths, custom)
    loaded = load_settings(paths)
    assert loaded == custom
    assert loaded.save_reminder_message == "Save Blender scene"
    assert AppSettings(save_reminder_message="   ").save_reminder_message == DEFAULT_REMINDER_MESSAGE

    now = [100.0]
    svc = NotificationService(loaded, suppress_fn=lambda _t: False, clock_fn=lambda: now[0])
    emitted: list[NotificationPayload] = []
    svc.notification_triggered.connect(emitted.append)

    for idx in range(7):
        now[0] = 100.0 + idx * 15.0
        res = svc.handle_observed_event(
            ObservedEvent("ws1", "shot.blend", "modified", "2026-11-25T10:00:00Z", project_id="p1")
        )
        assert (res is not None) == (idx == 6)
    assert emitted[0].duration_sec == 45
    assert "(7 saves)" in emitted[0].message

    assert svc._reminder_timer.isActive() is True
    assert svc._reminder_timer.interval() == 12 * 60_000
    timed = svc.trigger_timed_reminder()
    assert timed is not None
    assert timed.message == "Save Blender scene"
    assert timed.duration_sec == 45

    svc.update_settings(AppSettings(save_reminder_minutes=0))
    assert svc._reminder_timer.isActive() is False


def test_settings_view_custom_spinbox_disclosure_and_startup_checkbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SettingsView reveals custom spinboxes for non-preset values and persists toggles."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    reg = _FakeRegistry()
    startup_svc = StartupService(reg, command_builder=lambda: '"pythonw.exe" -m work_memory.main --minimized')
    settings = AppSettings(
        repeated_save_interval=7,
        notification_duration_sec=45,
        save_reminder_minutes=12,
        save_reminder_message="Save milestone",
    )
    notif_svc = NotificationService(settings, suppress_fn=lambda _t: False)
    view = SettingsView(
        paths, settings=settings, notification_service=notif_svc, startup_service=startup_svc
    )
    view.show()
    try:
        repeat_spin = view.findChild(QSpinBox, "repeatedSaveSpinBox")
        dur_spin = view.findChild(QSpinBox, "notifDurationSpinBox")
        rem_spin = view.findChild(QSpinBox, "saveReminderSpinBox")
        msg_edit = view.findChild(QLineEdit, "saveReminderMessageEdit")
        startup_cb = view.findChild(QCheckBox, "launchAtStartupCheckBox")
        assert all(w is not None for w in (repeat_spin, dur_spin, rem_spin, msg_edit, startup_cb))

        assert repeat_spin.isVisible() and repeat_spin.value() == 7  # type: ignore[union-attr]
        assert dur_spin.isVisible() and dur_spin.value() == 45  # type: ignore[union-attr]
        assert rem_spin.isVisible() and rem_spin.value() == 12  # type: ignore[union-attr]
        assert msg_edit.isVisible() and msg_edit.text() == "Save milestone"  # type: ignore[union-attr]

        rem_spin.setValue(18)  # type: ignore[union-attr]
        assert load_settings(paths).save_reminder_minutes == 18
        assert notif_svc._reminder_timer.interval() == 18 * 60_000

        view._reminder_combo.setCurrentIndex(view._reminder_combo.findData(0))
        assert view._notif_card.reminder_message_row.isVisible() is False
        assert load_settings(paths).save_reminder_minutes == 0

        startup_cb.setChecked(True)  # type: ignore[union-attr]
        assert startup_svc.is_startup_enabled() is True
        assert load_settings(paths).launch_at_startup is True
    finally:
        view.close()
