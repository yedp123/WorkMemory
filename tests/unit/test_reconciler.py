"""Unit tests for baseline scanning, restart reconciliation, and workspace storage."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.main_window import MainWindow


def _create_sample_workspace(root: Path) -> None:
    (root / "scenes").mkdir(parents=True)
    (root / "exports").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / ".git" / "objects" / "ab").mkdir(parents=True)
    (root / "Auto-Save").mkdir(parents=True)

    (root / "scenes" / "character_v01.blend").write_bytes(b"BLEND-v01-data")
    (root / "scenes" / "prop_draft.fbx").write_bytes(b"FBX-prop-initial")
    (root / "docs" / "notes.md").write_text("Initial notes\n", encoding="utf-8")
    (root / "docs" / "obsolete.txt").write_text("To be deleted offline\n", encoding="utf-8")
    (root / "docs" / "Thumbs.db").write_bytes(b"thumb")
    (root / "scenes" / "temp_render.tmp").write_bytes(b"tmp")
    (root / "node_modules" / "pkg" / "index.js").write_text("ignored\n", encoding="utf-8")
    (root / ".git" / "objects" / "ab" / "1234").write_bytes(b"obj")
    (root / "Auto-Save" / "recovery.blend").write_bytes(b"autosave")


def test_initial_baseline_scan_emits_zero_created_events(tmp_path: Path) -> None:
    ws_root = tmp_path / "CreativeRoot"
    _create_sample_workspace(ws_root)

    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    service = WorkspaceService(db, EventBus(), window_ms=200)
    try:
        ws = service.add_workspace(ws_root, background_scan=False)
        assert ws.is_active is True

        events = service.list_events(ws.id)
        assert events == []

        event_repo = ObservedEventRepository(db)
        baseline = event_repo.get_baseline_map(ws.id)
        assert set(baseline.keys()) == {
            "docs/notes.md",
            "docs/obsolete.txt",
            "scenes/character_v01.blend",
            "scenes/prop_draft.fbx",
        }
        assert all(entry.file_id > 0 for entry in baseline.values())

        refreshed = WorkspaceRepository(db).get_by_id(ws.id)
        assert refreshed is not None
        assert refreshed.last_scan_utc is not None
    finally:
        service.shutdown()


def test_restart_reconciliation_recovers_offline_edits_and_st_ino_renames(
    tmp_path: Path,
) -> None:
    ws_root = tmp_path / "CreativeRoot"
    _create_sample_workspace(ws_root)
    db_path = tmp_path / "app" / "work_memory.db"

    db1 = Database(db_path)
    db1.run_migrations()
    service1 = WorkspaceService(db1, window_ms=200)
    ws = service1.add_workspace(ws_root, background_scan=False)
    service1.shutdown()

    # Simulate edits while Work Memory is stopped.
    notes_path = ws_root / "docs" / "notes.md"
    old_stat = notes_path.stat()
    notes_path.write_text("Initial notes\nAdded lighting pass feedback.\n", encoding="utf-8")
    os.utime(notes_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 2_000_000_000))

    (ws_root / "docs" / "new_brief.md").write_text("Client brief\n", encoding="utf-8")
    (ws_root / "docs" / "obsolete.txt").unlink()
    (ws_root / "scenes" / "character_v01.blend").replace(
        ws_root / "scenes" / "character_v02.blend"
    )
    (ws_root / "scenes" / "prop_draft.fbx").replace(ws_root / "exports" / "prop_final.fbx")
    (ws_root / "docs" / "~$notes_lock.docx").write_bytes(b"lock")
    (ws_root / "exports" / "scratch.tmp").write_bytes(b"temp")

    # Restart Work Memory with fresh service instance.
    db2 = Database(db_path)
    service2 = WorkspaceService(db2, window_ms=200)
    try:
        service2.start(background_scans=False)
        events = service2.list_events(ws.id)
        by_key = {(ev.event_type, ev.rel_path): ev for ev in events}

        assert ("created", "docs/new_brief.md") in by_key
        assert ("modified", "docs/notes.md") in by_key
        assert ("deleted", "docs/obsolete.txt") in by_key
        assert ("renamed", "scenes/character_v02.blend") in by_key
        assert by_key[("renamed", "scenes/character_v02.blend")].old_rel_path == (
            "scenes/character_v01.blend"
        )
        assert ("moved", "exports/prop_final.fbx") in by_key
        assert by_key[("moved", "exports/prop_final.fbx")].old_rel_path == (
            "scenes/prop_draft.fbx"
        )
        assert len(events) == 5
    finally:
        service2.shutdown()

    # A second restart with no disk changes must emit zero duplicate events.
    db3 = Database(db_path)
    service3 = WorkspaceService(db3, window_ms=200)
    try:
        service3.start(background_scans=False)
        assert len(service3.list_events(ws.id)) == 5
    finally:
        service3.shutdown()


def test_empty_workspace_baseline_still_detects_later_offline_creates(tmp_path: Path) -> None:
    empty_root = tmp_path / "EmptyWorkspace"
    empty_root.mkdir()
    db_path = tmp_path / "app" / "work_memory.db"

    db1 = Database(db_path)
    db1.run_migrations()
    s1 = WorkspaceService(db1, window_ms=200)
    ws = s1.add_workspace(empty_root, background_scan=False)
    assert s1.count_baseline(ws.id) == 0
    assert s1.list_events(ws.id) == []
    s1.shutdown()

    (empty_root / "first_file.txt").write_text("hello", encoding="utf-8")

    db2 = Database(db_path)
    s2 = WorkspaceService(db2, window_ms=200)
    try:
        s2.start(background_scans=False)
        events = s2.list_events(ws.id)
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].rel_path == "first_file.txt"
        assert s2.count_baseline(ws.id) == 1
    finally:
        s2.shutdown()


def test_workspace_repository_crud_and_cascade_remove(tmp_path: Path) -> None:
    ws_root = tmp_path / "Studio"
    ws_root.mkdir()
    (ws_root / "asset.txt").write_text("abc", encoding="utf-8")

    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    ws_repo = WorkspaceRepository(db)
    ev_repo = ObservedEventRepository(db)

    service = WorkspaceService(db, window_ms=200)
    try:
        ws = service.add_workspace(ws_root, background_scan=False)
        assert ws_repo.set_active(ws.id, False) is not None
        assert ws_repo.list_all(active_only=True) == []
        assert ws_repo.set_active(ws.id, True) is not None
        assert len(ws_repo.list_all(active_only=True)) == 1
        assert ev_repo.count_baseline(ws.id) == 1

        assert service.remove_workspace(ws.id) is True
        assert ws_repo.get_by_id(ws.id) is None
        assert ev_repo.count_baseline(ws.id) == 0
        # Original file on disk MUST remain untouched after workspace removal.
        assert (ws_root / "asset.txt").read_text(encoding="utf-8") == "abc"
    finally:
        service.shutdown()


def test_settings_view_and_status_dot_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    ws_root = tmp_path / "UIWorkspace"
    ws_root.mkdir()
    (ws_root / "scene.blend").write_bytes(b"blend")

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    service = WorkspaceService(db, bus, window_ms=200)
    window = MainWindow(event_bus=bus, app_paths=app_paths, workspace_service=service)
    try:
        service.add_workspace(ws_root, background_scan=False)
        QCoreApplication.processEvents()
        assert window._status_dot.property("paused") is False
        assert "Observing" in window._status_dot.toolTip()
        assert window._settings_view._toggle_monitor_btn.text() == "Pause monitoring"

        service.pause_monitoring()
        QCoreApplication.processEvents()
        assert window._status_dot.property("paused") is True
        assert window._status_dot.toolTip() == "Monitoring paused"
        assert window._settings_view._toggle_monitor_btn.text() == "Resume monitoring"

        service.resume_monitoring()
        QCoreApplication.processEvents()
        assert window._status_dot.property("paused") is False
        assert window._settings_view._toggle_monitor_btn.text() == "Pause monitoring"
    finally:
        window.close()
        service.shutdown()
        app.processEvents()
