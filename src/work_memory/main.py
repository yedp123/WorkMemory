"""Thin application bootstrap entry point for Work Memory."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from work_memory.services.bootstrap_service import bootstrap, build_app_services, configure_logging
from work_memory.ui import app_icon, hotkeys, main_window, single_instance, tray
from work_memory.ui.theme import build_stylesheet, set_active_theme

__all__ = ["bootstrap", "configure_logging", "main"]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--minimized", action="store_true")
    args, _unknown = parser.parse_known_args(list(argv) if argv is not None else sys.argv[1:])
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the Work Memory desktop application or frozen transcription worker."""
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if len(raw_argv) >= 3 and raw_argv[0] == "--transcribe-worker":
        from work_memory.media.transcribe_worker import main as worker_main

        return worker_main(raw_argv[1:3])

    args = _parse_args(raw_argv)
    app_icon.set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # type: ignore[union-attr]
    app.setWindowIcon(app_icon.build_app_icon())  # type: ignore[union-attr]
    guard = single_instance.SingleInstanceGuard(parent=app)
    if not guard.acquire():
        return 0

    svcs = build_app_services()
    set_active_theme(svcs.settings.theme_mode)
    app.setStyleSheet(build_stylesheet(svcs.settings.theme_mode))  # type: ignore[union-attr]
    theme_filter = app_icon.TitleBarThemeFilter(svcs.settings.theme_mode, app)
    app.installEventFilter(theme_filter)
    win = main_window.MainWindow(
        svcs.bus, svcs.paths, svcs.workspace_service, svcs.project_service, svcs.history_service,
        svcs.capture_service, svcs.settings, svcs.notification_service, svcs.calendar_service,
        summary_service=svcs.summary_service, relink_service=svcs.relink_service,
        manifest_service=svcs.manifest_service, backup_service=svcs.backup_service,
        thumbnail_service=svcs.thumbnail_service, sound_player=svcs.sound_player,
        startup_service=svcs.startup_service,
    )
    win.theme_changed.connect(theme_filter.set_theme_mode)
    tray_ctrl, hotkey = tray.SystemTrayController(app), hotkeys.GlobalHotkeyManager(app)
    hotkey.set_enabled(svcs.settings.global_hotkey_enabled)
    for sig, slot in (
        (guard.activate_requested, win.open_from_tray), (tray_ctrl.open_requested, win.open_from_tray),
        (tray_ctrl.quick_capture_requested, win._open_quick_capture),
        (tray_ctrl.toggle_monitoring_requested, lambda: svcs.workspace_service.set_monitoring_paused_async(not svcs.workspace_service.is_monitoring_paused())),
        (tray_ctrl.quit_requested, win.quit_application), (svcs.bus.monitoring_paused_changed, tray_ctrl.set_paused),
        (hotkey.quick_capture_triggered, win._open_quick_capture),
    ):
        sig.connect(slot)
    for fn in (hotkey.unregister, tray_ctrl.hide, guard.close, svcs.calendar_service.stop_poller, svcs.workspace_service.shutdown):
        app.aboutToQuit.connect(fn)

    svcs.calendar_service.start_poller()
    svcs.workspace_service.start_async()
    if not args.minimized:
        win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
