"""Lifecycle, multi-monitor HiDPI, and thumbnail attachment tests for Quick Capture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import Project, Workspace
from work_memory.media import screenshot as screenshot_mod
from work_memory.services.capture_service import CaptureService
from work_memory.services.project_service import ProjectService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.capture import quick_capture_dialog as qcd_mod
from work_memory.ui.capture.capture_overlay import CaptureOverlay
from work_memory.ui.capture.quick_capture_dialog import QuickCaptureDialog
from work_memory.ui.main_window import MainWindow


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def _solid_pixmap(width: int, height: int, color: str, *, dpr: float = 1.0) -> QPixmap:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def _wait_until(predicate: object, timeout_ms: int = 1200) -> bool:
    loop = QEventLoop()
    elapsed = [0]

    def _poll() -> None:
        if predicate():  # type: ignore[operator]
            loop.quit()
            return
        elapsed[0] += 20
        if elapsed[0] >= timeout_ms:
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(_poll)
    timer.start(20)
    if not predicate():  # type: ignore[operator]
        loop.exec()
    timer.stop()
    return bool(predicate())  # type: ignore[operator]


@dataclass
class _FakeScreen:
    _geometry: QRect
    _dpr: float
    _pixmap: QPixmap

    def name(self) -> str:
        return "FakeScreen"

    def geometry(self) -> QRect:
        return self._geometry

    def devicePixelRatio(self) -> float:
        return self._dpr

    def grabWindow(self, _wid: int) -> QPixmap:
        return self._pixmap


def test_hiding_during_screen_capture_never_saves_draft_or_destroys_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _ensure_qapp(monkeypatch)
    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    cap_svc = CaptureService(db, app_paths)

    dlg = QuickCaptureDialog(cap_svc, [])
    dlg.show()
    try:
        dlg._note_input.setPlainText("Unsaved note while capturing")
        dlg._capturing_screen = True
        dlg.hide()
        app.processEvents()

        assert cap_svc.has_draft() is False
        assert dlg.isVisible() is False

        dlg.reject()
        dlg.close()
        app.processEvents()
        assert cap_svc.has_draft() is False

        dlg._capturing_screen = False
        dlg.showNormal()
        assert dlg.isVisible() is True
        assert dlg._note_input.toPlainText() == "Unsaved note while capturing"
    finally:
        dlg.force_close_on_shutdown()


def test_canceling_overlay_capture_restores_dialog_with_note_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _ensure_qapp(monkeypatch)
    app.setQuitOnLastWindowClosed(False)

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    cap_svc = CaptureService(db, app_paths, bus)

    frozen = _solid_pixmap(400, 300, "#243040", dpr=1.0)
    monkeypatch.setattr(qcd_mod, "grab_virtual_desktop", lambda: (frozen, QRect(0, 0, 400, 300)))

    orig_show_event = CaptureOverlay.showEvent

    def _auto_escape(self: CaptureOverlay, event: object) -> None:
        orig_show_event(self, event)  # type: ignore[arg-type]
        QTimer.singleShot(30, self, lambda: QTest.keyClick(self, Qt.Key.Key_Escape))

    monkeypatch.setattr(CaptureOverlay, "showEvent", _auto_escape)

    win = MainWindow(bus, app_paths, capture_service=cap_svc)
    win.show()
    try:
        win._open_quick_capture()
        dlg = win._capture_dialog
        assert dlg is not None and dlg.isVisible() is True
        dlg._note_input.setPlainText("Keep this exact note after Esc")

        shot_btn = dlg.findChild(QPushButton, "takeScreenshotButton")
        assert shot_btn is not None
        shot_btn.click()

        assert _wait_until(lambda: dlg.is_capturing_screen is True, timeout_ms=200) is True
        assert dlg.isVisible() is False
        assert cap_svc.has_draft() is False

        assert _wait_until(lambda: dlg.is_capturing_screen is False and dlg.isVisible(), timeout_ms=1500) is True
        assert win._capture_dialog is dlg
        assert dlg._note_input.toPlainText() == "Keep this exact note after Esc"
        assert dlg._attachments.count() == 0
        assert cap_svc.has_draft() is False
    finally:
        win.close()
        app.processEvents()


def test_confirming_overlay_capture_adds_thumbnail_supports_discard_and_multiple_captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _ensure_qapp(monkeypatch)
    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    ws = WorkspaceRepository(db).create(Workspace(name="Work", root_path=str(tmp_path / "work")))
    proj = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Rigging", rel_path="Rigging"))
    cap_svc = CaptureService(db, app_paths, bus)

    frozen = _solid_pixmap(600, 450, "#335588", dpr=1.5)
    monkeypatch.setattr(qcd_mod, "grab_virtual_desktop", lambda: (frozen, QRect(0, 0, 400, 300)))

    orig_show_event = CaptureOverlay.showEvent
    capture_turn = [0]

    def _auto_capture(self: CaptureOverlay, event: object) -> None:
        orig_show_event(self, event)  # type: ignore[arg-type]
        turn = capture_turn[0]
        capture_turn[0] += 1

        def _interact() -> None:
            QTest.mousePress(self, Qt.MouseButton.LeftButton, pos=QPoint(40, 30))
            QTest.mouseMove(self, pos=QPoint(239, 149))
            QTest.mouseRelease(self, Qt.MouseButton.LeftButton, pos=QPoint(239, 149))
            if turn == 0:
                rect_btn = self.findChild(QPushButton, "toolbarTool_rect")
                assert rect_btn is not None
                rect_btn.click()
                QTest.mousePress(self, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
                QTest.mouseMove(self, pos=QPoint(160, 110))
                QTest.mouseRelease(self, Qt.MouseButton.LeftButton, pos=QPoint(160, 110))
            confirm_btn = self.findChild(QPushButton, "toolbarConfirmButton")
            assert confirm_btn is not None
            confirm_btn.click()

        QTimer.singleShot(30, self, _interact)

    monkeypatch.setattr(CaptureOverlay, "showEvent", _auto_capture)

    dlg = QuickCaptureDialog(cap_svc, [proj], initial_project_id=proj.id)
    dlg.show()
    try:
        dlg._note_input.setPlainText("WeChat-style capture with 2 screenshots")
        shot_btn = dlg.findChild(QPushButton, "takeScreenshotButton")
        assert shot_btn is not None

        # 1. Capture first screenshot (with annotation) -> thumbnail card appears with KeepAspectRatio
        shot_btn.click()
        assert _wait_until(lambda: not dlg.is_capturing_screen and dlg._attachments.count() == 1) is True
        assert dlg._attachments.isVisible() is True
        cards = dlg._attachments.findChildren(QLabel)
        assert any(lbl.pixmap() and not lbl.pixmap().isNull() for lbl in cards)

        # 2. Click Screenshot again to add a second capture + attach/discard an external image
        shot_btn.click()
        assert _wait_until(lambda: not dlg.is_capturing_screen and dlg._attachments.count() == 2) is True

        ext_img = tmp_path / "discard_me.png"
        _solid_pixmap(32, 32, "#994422").save(str(ext_img), "PNG")
        dlg._attachments.add_external_image(ext_img)
        assert dlg._attachments.count() == 3

        discard_buttons = dlg._attachments.findChildren(QPushButton, "discardAttachmentButton")
        assert len(discard_buttons) == 3
        discard_buttons[-1].click()
        assert dlg._attachments.count() == 2

        dlg._on_save_entry()
        assert dlg.result() == QDialog.DialogCode.Accepted

        entries = cap_svc.list_project_captures(proj.id)
        assert len(entries) == 1
        atts = cap_svc.list_attachments(entries[0].id)
        assert [a.kind for a in atts] == ["screenshot", "annotated_screenshot", "screenshot"]
        assert atts[1].original_attachment_id == atts[0].id
        for att in atts:
            assert (app_paths.attachments_dir / att.stored_rel_path).is_file()
    finally:
        dlg.force_close_on_shutdown()
        app.processEvents()


def test_grab_virtual_desktop_negative_coords_hidpi_and_right_click_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_qapp(monkeypatch)
    left_screen = _FakeScreen(QRect(-800, -100, 800, 600), 1.0, _solid_pixmap(800, 600, "#11aa22", dpr=1.0))
    right_screen = _FakeScreen(QRect(0, 0, 1000, 600), 2.0, _solid_pixmap(2000, 1200, "#2244cc", dpr=2.0))
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [left_screen, right_screen]))
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: right_screen))

    canvas, vrect = screenshot_mod.grab_virtual_desktop()
    assert vrect == QRect(-800, -100, 1800, 700)
    assert canvas.size() == QSize(3600, 1400)
    assert canvas.devicePixelRatio() == 2.0

    img = canvas.toImage()
    assert img.pixelColor(20, 20).name() == "#11aa22"
    assert img.pixelColor(1620, 220).name() == "#2244cc"

    overlay = CaptureOverlay(canvas, vrect)
    QTimer.singleShot(30, overlay, lambda: QTest.mousePress(overlay, Qt.MouseButton.RightButton, pos=QPoint(50, 50)))
    assert overlay.exec() == QDialog.DialogCode.Rejected
    assert overlay.capture_result is None


def test_default_project_selection_and_main_window_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _ensure_qapp(monkeypatch)
    app.setQuitOnLastWindowClosed(False)

    ws_root = tmp_path / "Work"
    (ws_root / "Alpha").mkdir(parents=True)
    (ws_root / "Beta").mkdir(parents=True)

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    ws_svc = WorkspaceService(db, bus, window_ms=150)
    proj_svc = ProjectService(db, bus, workspace_service=ws_svc)
    ws_svc.set_project_service(proj_svc)
    cap_svc = CaptureService(db, app_paths, bus, workspace_service=ws_svc)

    ws_svc.add_workspace(ws_root, background_scan=False)
    proj_old = proj_svc.register_existing_project(ws_root / "Alpha", name="Alpha")
    proj_recent = proj_svc.register_existing_project(ws_root / "Beta", name="Beta")
    ProjectRepository(db).update_last_activity(proj_old.id, "2026-11-20T10:00:00Z")
    ProjectRepository(db).update_last_activity(proj_recent.id, "2026-11-24T09:00:00Z")

    win = MainWindow(
        bus, app_paths, workspace_service=ws_svc, project_service=proj_svc, capture_service=cap_svc
    )
    win.show()
    try:
        win._open_quick_capture()
        assert win._capture_dialog is not None
        assert win._capture_dialog._project_combo.currentData() == proj_recent.id
        win._capture_dialog.close()

        win._open_project_detail(proj_old.id)
        win._open_quick_capture()
        assert win._capture_dialog is not None
        assert win._capture_dialog._project_combo.currentData() == proj_old.id

        QTimer.singleShot(40, win.close)
        rc = app.exec()
        assert rc == 0
    finally:
        ws_svc.shutdown()
        QCoreApplication.processEvents()
