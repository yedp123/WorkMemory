"""Unit and UI tests for Phase 4 Quick Capture, Draft Recovery, and Screenshot Annotation."""

from __future__ import annotations

from datetime import UTC, date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import CaptureEntry, Project, Workspace
from work_memory.media.screenshot import pixmap_to_png_bytes
from work_memory.services.capture_service import CaptureService, ScreenshotData
from work_memory.services.history_service import HistoryService
from work_memory.services.project_service import ProjectService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.attachments import AttachmentStorage
from work_memory.storage.database import Database
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.capture.annotator_canvas import AnnotatorCanvas
from work_memory.ui.capture.quick_capture_dialog import QuickCaptureDialog
from work_memory.ui.main_window import MainWindow


def _wait_qt_pool() -> None:
    for _ in range(4):
        QThreadPool.globalInstance().waitForDone(3000)
        QCoreApplication.processEvents()


def _make_png_bytes(width: int = 80, height: int = 60, color: str = "#335577") -> bytes:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    return pixmap_to_png_bytes(QPixmap.fromImage(img))


def test_combined_capture_saves_entry_with_multiple_attachments_and_is_searchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    emitted: list[CaptureEntry] = []
    bus.capture_saved.connect(emitted.append)

    ws = WorkspaceRepository(db).create(Workspace(name="Work", root_path=str(tmp_path / "work")))
    proj = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Action Director", rel_path="Action_Director"))

    ext_img = tmp_path / "external_ref.png"
    ext_bytes = _make_png_bytes(40, 40, "#884422")
    ext_img.write_bytes(ext_bytes)

    orig_bytes = _make_png_bytes(100, 80, "#224466")
    ann_bytes = _make_png_bytes(100, 80, "#664422")

    cap_svc = CaptureService(db, app_paths, bus)
    entry, attachments = cap_svc.save_capture(
        project_id=proj.id,
        note_text="Verified standalone export preset compatibility.",
        linked_file=r"export\character_export.py",
        original_screenshot_bytes=orig_bytes,
        annotated_screenshot_bytes=ann_bytes,
        external_image_paths=[ext_img],
    )

    assert len(emitted) == 1 and emitted[0].id == entry.id
    assert entry.rel_path == "export/character_export.py"
    assert [a.kind for a in attachments] == ["screenshot", "annotated_screenshot", "image"]
    assert attachments[1].original_attachment_id == attachments[0].id

    # Original and annotated screenshots are stored separately without overwriting each other.
    orig_file = app_paths.attachments_dir / attachments[0].stored_rel_path
    ann_file = app_paths.attachments_dir / attachments[1].stored_rel_path
    ext_copy = app_paths.attachments_dir / attachments[2].stored_rel_path
    assert orig_file.read_bytes() == orig_bytes
    assert ann_file.read_bytes() == ann_bytes
    assert ext_copy.read_bytes() == ext_bytes
    assert orig_file != ann_file

    hist_svc = HistoryService(db, bus, app_paths=app_paths, tz=UTC)
    hits = hist_svc.search("standalone preset")
    assert [c.id for c in hits.captures] == [entry.id]
    assert hits.timeline is not None
    assert len(hits.timeline.capture_attachments[entry.id]) == 3

    today_utc = date.fromisoformat(entry.captured_at_utc[:10])
    markers = hist_svc.get_month_markers(today_utc.year, today_utc.month, project_id=proj.id)
    assert markers[today_utc.day].has_captures is True


def test_draft_recovery_saves_reloads_and_discards_inside_app_drafts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    cap_svc = CaptureService(db, app_paths)

    preview_bytes = _make_png_bytes(60, 40, "#336655")
    saved = cap_svc.save_draft(
        project_id="proj-1",
        linked_file="scenes/rig.ma",
        note_text="Unfinished rigging note",
        preview_image_bytes=preview_bytes,
    )
    assert (app_paths.drafts_dir / "draft.json").is_file()
    assert (app_paths.drafts_dir / "draft_preview.png").is_file()
    assert saved.temp_image_path is not None

    loaded = cap_svc.load_draft()
    assert loaded is not None
    assert loaded.project_id == "proj-1"
    assert loaded.linked_file == "scenes/rig.ma"
    assert loaded.note_text == "Unfinished rigging note"
    assert loaded.temp_image_path == str((app_paths.drafts_dir / "draft_preview.png").resolve())

    cap_svc.clear_draft()
    assert cap_svc.load_draft() is None
    assert not (app_paths.drafts_dir / "draft.json").exists()
    assert not (app_paths.drafts_dir / "draft_preview.png").exists()


def test_annotator_canvas_preserves_original_and_supports_tools_crop_undo_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])

    img = QImage(200, 120, QImage.Format.Format_ARGB32)
    img.fill(QColor("#1e2430"))
    orig = QPixmap.fromImage(img)

    canvas = AnnotatorCanvas()
    canvas.resize(420, 240)
    canvas.set_pixmap(orig)
    orig_bytes = pixmap_to_png_bytes(canvas.original_pixmap())
    assert canvas.has_annotations() is False

    # Draw rectangle via mouse drag
    canvas.set_tool("rect")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(80, 60))
    QTest.mouseMove(canvas, pos=QPoint(220, 150))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(220, 150))
    assert canvas.has_annotations() is True
    assert pixmap_to_png_bytes(canvas.annotated_pixmap()) != orig_bytes
    assert pixmap_to_png_bytes(canvas.original_pixmap()) == orig_bytes

    # Add text label + crop
    canvas.add_text_label(QPointF(25, 35), "Check pose")
    canvas.set_tool("crop")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 50))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 170))
    cropped = canvas.annotated_pixmap()
    assert cropped.width() < 200 and cropped.height() < 120
    assert pixmap_to_png_bytes(canvas.original_pixmap()) == orig_bytes

    # Undo restores pre-crop dimensions; Reset restores original unannotated bytes
    assert canvas.undo() is True
    assert canvas.annotated_pixmap().size() == orig.size()
    canvas.reset()
    assert canvas.has_annotations() is False
    assert pixmap_to_png_bytes(canvas.annotated_pixmap()) == orig_bytes


def test_quick_capture_dialog_draft_recovery_and_project_detail_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    ws_root = tmp_path / "Work"
    proj_dir = ws_root / "Action_Director"
    proj_dir.mkdir(parents=True)

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    ws_svc = WorkspaceService(db, bus, window_ms=150)
    proj_svc = ProjectService(db, bus, workspace_service=ws_svc)
    ws_svc.set_project_service(proj_svc)
    hist_svc = HistoryService(db, bus, app_paths=app_paths)
    cap_svc = CaptureService(db, app_paths, bus, workspace_service=ws_svc)

    ws_svc.add_workspace(ws_root, background_scan=False)
    proj = proj_svc.register_existing_project(proj_dir, name="Action Director")

    # 1. Draft save on close without saving
    dlg1 = QuickCaptureDialog(cap_svc, [proj], initial_project_id=proj.id)
    dlg1.show()
    assert dlg1._attachments.isVisible() is False
    dlg1._note_input.setPlainText("Draft note before closing")
    dlg1.reject()
    assert cap_svc.has_draft() is True

    # 2. Reopening recovers draft banner, then saving persists entry & clears draft
    dlg2 = QuickCaptureDialog(cap_svc, [proj])
    dlg2.show()
    assert dlg2._draft_bar.isVisible() is True
    assert dlg2._note_input.toPlainText() == "Draft note before closing"
    dlg2._attachments.add_screenshot(_make_png_bytes(80, 60, "#224466"))
    dlg2._on_save_entry()
    assert cap_svc.has_draft() is False

    # 3. MainWindow + ProjectDetailView display saved capture & notes
    win = MainWindow(
        bus, app_paths, workspace_service=ws_svc, project_service=proj_svc,
        history_service=hist_svc, capture_service=cap_svc,
    )
    win.show()
    try:
        win._open_project_detail(proj.id)
        _wait_qt_pool()
        note_labels = [
            lbl.text() for lbl in win._project_detail_view.findChildren(QLabel)
            if "Draft note before closing" in lbl.text()
        ]
        assert note_labels
    finally:
        win.close()
        ws_svc.shutdown()
        app.processEvents()


def test_attachment_storage_blocks_writes_inside_monitored_workspace(tmp_path: Path) -> None:
    ws_dir = tmp_path / "UserWorkspace"
    ws_dir.mkdir()
    storage = AttachmentStorage(ws_dir / "attachments", workspace_roots_provider=lambda: [ws_dir])
    with pytest.raises(PermissionError):
        storage.save_image_bytes(b"PNGDATA", "png")


def test_save_capture_supports_multiple_screenshots_with_separate_originals_and_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    cap_svc = CaptureService(db, app_paths)

    shot1_orig = _make_png_bytes(90, 60, "#112233")
    shot1_ann = _make_png_bytes(90, 60, "#aa4433")
    shot2_orig = _make_png_bytes(110, 70, "#225544")
    ext_img = tmp_path / "ref.png"
    ext_img.write_bytes(_make_png_bytes(40, 40, "#778899"))

    entry, attachments = cap_svc.save_capture(
        project_id=None,
        note_text="Two viewport shots and one ref image.",
        screenshots=[
            ScreenshotData(original_bytes=shot1_orig, annotated_bytes=shot1_ann),
            ScreenshotData(original_bytes=shot2_orig, annotated_bytes=None),
        ],
        external_image_paths=[ext_img],
    )

    assert [a.kind for a in attachments] == [
        "screenshot",
        "annotated_screenshot",
        "screenshot",
        "image",
    ]
    assert attachments[1].original_attachment_id == attachments[0].id
    assert (app_paths.attachments_dir / attachments[0].stored_rel_path).read_bytes() == shot1_orig
    assert (app_paths.attachments_dir / attachments[1].stored_rel_path).read_bytes() == shot1_ann
    assert (app_paths.attachments_dir / attachments[2].stored_rel_path).read_bytes() == shot2_orig
    assert len(cap_svc.list_attachments(entry.id)) == 4


def test_capture_is_milestone_persists_in_save_and_draft_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    cap_svc = CaptureService(db, app_paths, event_bus=bus)

    cap_svc.save_draft(
        project_id=None,
        linked_file="rig/hero.py",
        note_text="Important milestone draft",
        is_milestone=True,
    )
    loaded = cap_svc.load_draft()
    assert loaded is not None
    assert loaded.is_milestone is True

    milestone_signals: list[tuple[str, str, bool]] = []
    bus.milestone_updated.connect(lambda t, i, m: milestone_signals.append((t, i, m)))
    entry, _atts = cap_svc.create_capture(
        project_id=None,
        note_text="Saved directly as milestone",
        is_milestone=True,
    )
    assert entry.is_milestone is True
    assert milestone_signals == [("capture", entry.id, True)]
    assert cap_svc.load_draft() is None
