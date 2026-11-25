"""Safety proof that Work Memory never mutates monitored user workspaces."""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

import pytest
from watchdog.events import EventsLostEvent

from work_memory.config.paths import (
    assert_not_inside_monitored_workspace,
    resolve_app_paths,
)
from work_memory.main import bootstrap
from work_memory.services.capture_service import CaptureService
from work_memory.services.project_service import ProjectService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.watcher.observer import WorkspaceObserver, _WorkspaceEventHandler


def _snapshot_tree(root: Path) -> tuple[set[str], dict[str, tuple[str, int]]]:
    dirs: set[str] = set()
    files: dict[str, tuple[str, int]] = {}
    for entry in root.rglob("*"):
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            dirs.add(rel)
        elif entry.is_file():
            digest = hashlib.sha256(entry.read_bytes()).hexdigest()
            files[rel] = (digest, entry.stat().st_mtime_ns)
    return dirs, files


def _build_fixture_workspace(root: Path) -> None:
    (root / "Project_Alpha" / "scenes").mkdir(parents=True)
    (root / "Project_Alpha" / "renders").mkdir(parents=True)
    (root / "Project_Beta" / "notes").mkdir(parents=True)
    (root / "Empty_Folder").mkdir(parents=True)

    (root / "README.md").write_text("# User Workspace\n", encoding="utf-8")
    (root / "Project_Alpha" / "scenes" / "character_v03.blend").write_bytes(
        b"\x00BLENDER-v306\x01\x02\x03"
    )
    (root / "Project_Alpha" / "renders" / "shot_0001.exr").write_bytes(b"EXR\x01\x00\x00")
    (root / "Project_Beta" / "notes" / "client_brief.txt").write_text(
        "Keep warm key light.\n", encoding="utf-8"
    )


def _create_directory_link(target: Path, link_path: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link_path))
    else:
        os.symlink(target, link_path, target_is_directory=True)


def _close_root_logging_handlers() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()


def test_monitored_workspace_is_never_modified_and_writes_are_blocked(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "user_workspace"
    _build_fixture_workspace(workspace_root)
    before_dirs, before_files = _snapshot_tree(workspace_root)

    app_data_root = tmp_path / "isolated_app_data"
    try:
        app_paths, _db, _bus = bootstrap(base_dir=app_data_root)
    finally:
        _close_root_logging_handlers()

    assert app_paths.base_dir == app_data_root.resolve()
    assert app_paths.db_path.is_file()
    assert app_paths.attachments_dir.is_dir()
    assert app_paths.drafts_dir.is_dir()
    assert app_paths.logs_dir.is_dir()

    # Guard must allow app-owned storage and sibling directories outside the workspace.
    sibling_export = tmp_path / "user_workspace_export" / "bundle.wmem"
    assert_not_inside_monitored_workspace(app_paths.db_path, [workspace_root])
    assert_not_inside_monitored_workspace(
        app_paths.attachments_dir / "capture.png", [workspace_root]
    )
    assert_not_inside_monitored_workspace(sibling_export, [workspace_root])

    # Guard must block direct, nested, traversal, and linked paths inside the workspace.
    with pytest.raises(PermissionError):
        assert_not_inside_monitored_workspace(workspace_root, [workspace_root])

    with pytest.raises(PermissionError):
        assert_not_inside_monitored_workspace(
            workspace_root / "Project_Alpha" / "scenes" / "character_v03.blend",
            [workspace_root],
        )

    with pytest.raises(PermissionError):
        assert_not_inside_monitored_workspace(
            workspace_root / "Project_Alpha" / "work_memory.db",
            [workspace_root],
        )

    with pytest.raises(PermissionError):
        assert_not_inside_monitored_workspace(
            tmp_path / "other" / ".." / "user_workspace" / "sidecar.json",
            [workspace_root],
        )

    linked_alias = tmp_path / "linked_workspace_alias"
    _create_directory_link(workspace_root / "Project_Alpha", linked_alias)
    try:
        with pytest.raises(PermissionError):
            assert_not_inside_monitored_workspace(
                linked_alias / "scenes" / "sidecar.json",
                [workspace_root],
            )
    finally:
        if linked_alias.exists() or linked_alias.is_symlink():
            linked_alias.unlink() if linked_alias.is_symlink() else linked_alias.rmdir()

    after_dirs, after_files = _snapshot_tree(workspace_root)
    assert after_dirs == before_dirs
    assert after_files == before_files


def test_default_app_paths_use_localappdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    paths = resolve_app_paths()

    assert paths.base_dir == (fake_local / "WorkMemory").resolve(strict=False)
    assert paths.db_path == paths.base_dir / "work_memory.db"
    assert paths.attachments_dir == paths.base_dir / "attachments"
    assert paths.drafts_dir == paths.base_dir / "drafts"
    assert paths.logs_dir == paths.base_dir / "logs"


def test_ui_layer_has_no_banned_storage_or_watchdog_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    ui_dir = repo_root / "src" / "work_memory" / "ui"
    banned_prefixes = ("sqlite3", "watchdog", "work_memory.storage")

    for py_file in ui_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(banned_prefixes), (
                        f"Banned import {alias.name!r} in {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(banned_prefixes), (
                    f"Banned import {node.module!r} in {py_file}"
                )


def test_baseline_scan_and_live_observer_never_mutate_fixture_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "fixture_workspace"
    _build_fixture_workspace(workspace_root)
    before_dirs, before_files = _snapshot_tree(workspace_root)

    db = Database(tmp_path / "isolated_app_data" / "work_memory.db")
    db.run_migrations()
    service = WorkspaceService(db, window_ms=250)
    try:
        ws = service.add_workspace(workspace_root, background_scan=False)
        assert service.list_events(ws.id) == []
        scan_dirs, scan_files = _snapshot_tree(workspace_root)
        assert scan_dirs == before_dirs
        assert scan_files == before_files

        # Allow Watchdog emitter to initialize before simulating user edits.
        time.sleep(0.25)

        brief = workspace_root / "Project_Beta" / "notes" / "client_brief.txt"
        brief.write_text("Keep warm key light and subtle rim.\n", encoding="utf-8")

        old_blend = workspace_root / "Project_Alpha" / "scenes" / "character_v03.blend"
        new_blend = workspace_root / "Project_Alpha" / "scenes" / "character_v04.blend"
        old_blend.replace(new_blend)

        target_exr = workspace_root / "Project_Alpha" / "renders" / "shot_0001.exr"
        temp_exr = workspace_root / "Project_Alpha" / "renders" / "shot_0001.exr.tmp"
        temp_exr.write_bytes(b"EXR\x02\x00\x00\xff")
        target_exr.unlink()
        temp_exr.replace(target_exr)

        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and len(service.list_events(ws.id)) < 3:
            time.sleep(0.1)
        service.flush_observer()
    finally:
        service.shutdown()

    after_dirs, after_files = _snapshot_tree(workspace_root)
    expected_keys = (set(before_files) - {"Project_Alpha/scenes/character_v03.blend"}) | {
        "Project_Alpha/scenes/character_v04.blend"
    }
    assert after_dirs == before_dirs
    assert set(after_files) == expected_keys
    assert after_files["README.md"] == before_files["README.md"]

    events = service.list_events(ws.id)
    types_by_path = {ev.rel_path: ev.event_type for ev in events}
    assert types_by_path["Project_Beta/notes/client_brief.txt"] == "modified"
    assert types_by_path["Project_Alpha/renders/shot_0001.exr"] == "modified"
    assert types_by_path["Project_Alpha/scenes/character_v04.blend"] == "renamed"


def test_observer_pause_resume_and_overflow_recovery(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    (ws_root / "base.txt").write_text("base", encoding="utf-8")
    before_dirs, before_files = _snapshot_tree(ws_root)

    overflows: list[str] = []
    observer = WorkspaceObserver(window_ms=100, on_overflow=overflows.append)
    observer.start()
    observer.watch_workspace("ws-1", ws_root)
    observer.pause()
    assert observer.is_paused is True
    observer.resume()
    assert observer.is_paused is False

    handler = _WorkspaceEventHandler(
        "ws-1", ws_root, observer._filter, lambda _ev: None, overflows.append
    )
    handler.on_any_event(EventsLostEvent(str(ws_root), is_directory=True))
    observer.stop()

    assert overflows == ["ws-1"]
    assert _snapshot_tree(ws_root) == (before_dirs, before_files)


def test_project_discovery_and_registration_never_mutate_fixture_workspace(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "safety_workspace"
    _build_fixture_workspace(workspace_root)
    before_dirs, before_files = _snapshot_tree(workspace_root)

    db = Database(tmp_path / "isolated_app_data" / "work_memory.db")
    db.run_migrations()
    ws_service = WorkspaceService(db, window_ms=200)
    proj_service = ProjectService(db, workspace_service=ws_service)
    ws_service.set_project_service(proj_service)
    try:
        ws = ws_service.add_workspace(workspace_root, background_scan=False)
        suggestions = proj_service.discover_suggestions(ws.id)
        assert any(s.rel_path == "Project_Alpha" for s in suggestions)
        assert proj_service.list_projects() == []

        registered = proj_service.register_existing_project(
            workspace_root / "Project_Alpha",
            name="Project Alpha",
            description="3D character assets",
        )
        assert registered.abs_path == str((workspace_root / "Project_Alpha").resolve())
    finally:
        ws_service.shutdown()

    after_dirs, after_files = _snapshot_tree(workspace_root)
    assert after_dirs == before_dirs
    assert after_files == before_files


def test_importing_workspace_image_into_capture_never_mutates_original(tmp_path: Path) -> None:
    workspace_root = tmp_path / "capture_safety_workspace"
    _build_fixture_workspace(workspace_root)
    ref_img = workspace_root / "Project_Alpha" / "renders" / "preview_ref.png"
    ref_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-mock-image")
    before_dirs, before_files = _snapshot_tree(workspace_root)

    app_paths = resolve_app_paths(tmp_path / "isolated_app_data")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    ws_service = WorkspaceService(db, window_ms=200)
    cap_service = CaptureService(db, app_paths, workspace_service=ws_service)
    try:
        ws_service.add_workspace(workspace_root, background_scan=False)
        entry, attachments = cap_service.save_capture(
            project_id=None,
            note_text="Imported reference image",
            linked_file="Project_Alpha/renders/preview_ref.png",
            external_image_paths=[ref_img],
        )
        assert entry.id
        assert len(attachments) == 1
        copied = app_paths.attachments_dir / attachments[0].stored_rel_path
        assert copied.is_file() and copied.read_bytes() == ref_img.read_bytes()
    finally:
        ws_service.shutdown()

    after_dirs, after_files = _snapshot_tree(workspace_root)
    assert after_dirs == before_dirs
    assert after_files == before_files
