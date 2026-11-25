"""Unit and UI tests for Polish Pass A: project covers, fixed grid sizing, and folder reveal."""

from __future__ import annotations

import hashlib
import os
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt, QThreadPool
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import DayTimeline, ObservedEvent, ObservedGroup, Workspace
from work_memory.services.backup_service import BackupService
from work_memory.services.project_service import ProjectService
from work_memory.storage.database import Database
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.file_actions import build_reveal_command
from work_memory.ui.views.project_detail_view import ProjectDetailView
from work_memory.ui.views.projects_view import ProjectsView
from work_memory.ui.widgets.cover_banner import CoverBanner
from work_memory.ui.widgets.project_card import ProjectCard
from work_memory.ui.widgets.timeline_widget import TimelineWidget


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _flush_qt() -> None:
    for _ in range(5):
        QThreadPool.globalInstance().waitForDone(2000)
        QCoreApplication.processEvents()


def _write_test_png(path: Path, width: int, height: int, color: str) -> None:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    assert img.save(str(path), "PNG")


def test_project_cover_resize_readonly_persistence_backup_and_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """set_project_cover stores resized copy in covers/, keeps source untouched, and backs up."""
    _ensure_qapp(monkeypatch)
    ws_root = tmp_path / "Studio"
    proj_dir = ws_root / "Alpha"
    proj_dir.mkdir(parents=True)
    src_img = proj_dir / "hero_render.png"
    _write_test_png(src_img, 2400, 1500, "#336699")
    src_sha = hashlib.sha256(src_img.read_bytes()).hexdigest()
    src_mtime = src_img.stat().st_mtime_ns

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    proj_svc = ProjectService(db, EventBus(), app_paths=app_paths)
    proj = proj_svc.register_existing_project(proj_dir, name="Alpha")

    updated = proj_svc.set_project_cover(proj.id, src_img)
    assert updated.cover_image_path is not None
    stored_cover = proj_svc.get_project_cover_path(updated)
    assert stored_cover is not None and stored_cover.parent == app_paths.covers_dir
    saved_img = QImage(str(stored_cover))
    assert saved_img.width() == 1280 and saved_img.height() == 800

    # Original user file inside monitored workspace must be 100% untouched.
    assert hashlib.sha256(src_img.read_bytes()).hexdigest() == src_sha
    assert src_img.stat().st_mtime_ns == src_mtime

    # Replacing cover cleans up old file; DB reload preserves filename.
    src_img2 = proj_dir / "hero_render_v2.png"
    _write_test_png(src_img2, 800, 500, "#994433")
    replaced = proj_svc.set_project_cover(proj.id, src_img2)
    assert not stored_cover.exists()
    stored2 = proj_svc.get_project_cover_path(replaced)
    assert stored2 is not None and QImage(str(stored2)).width() == 800
    assert ProjectRepository(db).get(proj.id).cover_image_path == replaced.cover_image_path  # type: ignore[union-attr]

    # Backup & restore preserves covers/.
    bak_zip = tmp_path / "backup.zip"
    BackupService(db, app_paths, EventBus()).create_full_backup(bak_zip)
    restored_paths = resolve_app_paths(tmp_path / "restored_app")
    restored_paths.ensure_directories()
    restored_db = Database(restored_paths.db_path)
    restored_db.run_migrations()
    BackupService(restored_db, restored_paths, EventBus()).restore_full_backup(bak_zip)
    assert (restored_paths.covers_dir / replaced.cover_image_path).is_file()  # type: ignore[operator]

    # Clear cover deletes stored file and resets cover_image_path.
    cleared = proj_svc.clear_project_cover(proj.id)
    assert cleared.cover_image_path is None
    assert not stored2.exists()


def test_grid_cards_keep_fixed_aspect_sizes_and_hero_cover_buttons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Grid cards do not stretch when parent resizes; hero buttons render custom cover."""
    _ensure_qapp(monkeypatch)
    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    proj_svc = ProjectService(db, bus, app_paths=app_paths)

    ws_dir = tmp_path / "Work"
    p_dir = ws_dir / "Gamma"
    p_dir.mkdir(parents=True)
    img_path = p_dir / "cover.png"
    _write_test_png(img_path, 1000, 625, "#447755")
    proj = proj_svc.register_existing_project(p_dir, name="Gamma")
    proj = proj_svc.set_project_cover(proj.id, img_path)

    pm = QPixmap(str(proj_svc.get_project_cover_path(proj)))
    banner = CoverBanner("c1")
    banner.resize(320, 200)
    banner.set_pixmap(pm)
    assert banner._pixmap is not None

    view = ProjectsView(proj_svc, bus, app_paths=app_paths)
    try:
        for mode, exp_w, exp_h in (("small", 240, 150), ("medium", 320, 200), ("large", 440, 275)):
            view.set_view_mode(mode)
            view.resize(1600, 800)
            view.show()
            _flush_qt()
            cards = view.findChildren(ProjectCard)
            assert cards and cards[0].width() == exp_w
            assert cards[0]._cover.width() == exp_w and cards[0]._cover.height() == exp_h
    finally:
        view.close()

    detail = ProjectDetailView(proj_svc, None, bus)
    try:
        detail.show_project(proj.id, project=proj)
        detail.show()
        _flush_qt()
        assert detail.findChild(QPushButton, "changeCoverButton") is not None
        reset_btn = detail.findChild(QPushButton, "resetCoverButton")
        assert reset_btn is not None and reset_btn.isVisible() is True
    finally:
        detail.close()


def test_build_reveal_command_and_timeline_folder_button_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_reveal_command handles existing/deleted/missing paths; folder button stays isolated."""
    _ensure_qapp(monkeypatch)
    ws_root = tmp_path / "Workspace"
    sub = ws_root / "Proj" / "scenes"
    sub.mkdir(parents=True)
    target = sub / "rig.blend"
    target.write_bytes(b"BLEND")

    cmd_hit, status_hit = build_reveal_command(target, root_bound=ws_root)
    assert status_hit == "revealed"
    assert cmd_hit == ["explorer", "/select,", os.path.normpath(str(target))]

    target.unlink()
    cmd_parent, status_parent = build_reveal_command(target, root_bound=ws_root)
    assert status_parent == "parent_opened"
    assert cmd_parent == ["explorer", os.path.normpath(str(sub))]

    outside_missing = tmp_path / "Gone" / "sub" / "file.txt"
    cmd_none, status_none = build_reveal_command(outside_missing, root_bound=tmp_path / "Gone")
    assert cmd_none is None and status_none == "missing"

    opened_urls: list[object] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened_urls.append(u) or True)

    tl = TimelineWidget()
    ev = ObservedEvent("ws-1", "Proj/scenes/rig.blend", "modified", "2026-11-25T10:00:00Z", project_id="p-1")
    grp = ObservedGroup(
        project_id="p-1",
        project_name="Proj",
        occurred_at_utc="2026-11-25T10:00:00Z",
        local_date_label="2026-11-25",
        local_time_label="10:00",
        events=(ev,),
    )
    tl.set_timeline(DayTimeline(local_date=date(2026, 11, 25), observed_groups=(grp,)))
    tl.show()
    try:
        revealed: list[tuple[str, str, str]] = []
        starred: list[tuple[str, str]] = []
        tl.file_reveal_requested.connect(lambda r, p, w: revealed.append((r, p, w)))
        tl.milestone_toggled.connect(lambda t, i: starred.append((t, i)))
        folder_btn = tl.findChild(QPushButton, "revealInFolderButton")
        assert folder_btn is not None
        QTest.mouseClick(folder_btn, Qt.MouseButton.LeftButton)
        assert revealed == [("Proj/scenes/rig.blend", "p-1", "ws-1")]
        assert opened_urls == [] and starred == []
    finally:
        tl.close()
        _ = Workspace, WorkspaceRepository
