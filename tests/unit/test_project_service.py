"""Unit tests for ProjectService registration, nested path resolution, status, and UI."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QThreadPool
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import Workspace
from work_memory.services.project_service import ProjectService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.main_window import MainWindow
from work_memory.ui.views.register_project_dialog import RegisterProjectDialog
from work_memory.ui.widgets.project_card import ProjectCard


def _snapshot_tree(root: Path) -> tuple[set[str], dict[str, tuple[str, int]]]:
    dirs: set[str] = set()
    files: dict[str, tuple[str, int]] = {}
    for entry in root.rglob("*"):
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            dirs.add(rel)
        elif entry.is_file():
            files[rel] = (hashlib.sha256(entry.read_bytes()).hexdigest(), entry.stat().st_mtime_ns)
    return dirs, files


def _wait_qt_pool() -> None:
    for _ in range(4):
        QThreadPool.globalInstance().waitForDone(3000)
        QCoreApplication.processEvents()


def test_nested_project_longest_prefix_segment_matching(tmp_path: Path) -> None:
    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    ws_root = tmp_path / "Work"
    client_dir = ws_root / "Client"
    sub_dir = client_dir / "Sub"
    alpha_dir = ws_root / "Alpha"
    alpha_2_dir = ws_root / "Alpha_2"
    for folder in (sub_dir / "scenes", alpha_dir, alpha_2_dir):
        folder.mkdir(parents=True)

    WorkspaceRepository(db).create(Workspace(name="Work", root_path=str(ws_root.resolve())))
    service = ProjectService(db)

    client_proj = service.register_existing_project(client_dir, name="Client")
    sub_proj = service.register_existing_project(sub_dir, name="Client Sub")
    alpha_proj = service.register_existing_project(alpha_dir, name="Alpha")

    assert service.resolve_project_for_path(sub_dir / "scenes" / "hero.blend") == sub_proj
    assert service.resolve_project_for_path(client_dir / "brief.md") == client_proj
    assert service.resolve_project_for_path(alpha_dir / "mesh.fbx") == alpha_proj
    assert service.resolve_project_for_path(alpha_2_dir / "mesh.fbx") is None


def test_observed_events_associate_deepest_project_and_update_last_activity(tmp_path: Path) -> None:
    ws_root = tmp_path / "Work"
    parent_proj_dir = ws_root / "Client"
    sub_proj_dir = parent_proj_dir / "Sub"
    (sub_proj_dir / "scenes").mkdir(parents=True)
    (parent_proj_dir / "notes.txt").write_text("parent", encoding="utf-8")

    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    bus = EventBus()
    ws_service = WorkspaceService(db, bus, window_ms=150)
    proj_service = ProjectService(db, bus, workspace_service=ws_service)
    ws_service.set_project_service(proj_service)

    try:
        ws_service.add_workspace(ws_root, background_scan=False)
        parent_proj = proj_service.register_existing_project(parent_proj_dir, name="Client")
        sub_proj = proj_service.register_existing_project(sub_proj_dir, name="Sub")

        time.sleep(0.2)
        (sub_proj_dir / "scenes" / "shot_01.blend").write_bytes(b"BLEND")
        (parent_proj_dir / "notes.txt").write_text("parent updated", encoding="utf-8")

        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and (
            len(proj_service.list_project_events(sub_proj.id)) < 1
            or len(proj_service.list_project_events(parent_proj.id)) < 1
        ):
            time.sleep(0.05)
        ws_service.flush_observer()
    finally:
        ws_service.shutdown()

    sub_events = proj_service.list_project_events(sub_proj.id)
    parent_events = proj_service.list_project_events(parent_proj.id)
    assert [e.rel_path for e in sub_events] == ["Client/Sub/scenes/shot_01.blend"]
    assert [e.rel_path for e in parent_events] == ["Client/notes.txt"]

    refreshed_sub = proj_service.get_project(sub_proj.id)
    refreshed_parent = proj_service.get_project(parent_proj.id)
    assert refreshed_sub is not None and refreshed_sub.last_activity_utc == sub_events[0].occurred_at_utc
    assert refreshed_parent is not None and refreshed_parent.last_activity_utc == parent_events[0].occurred_at_utc


def test_manual_status_toggle_and_completed_projects_remain_searchable(tmp_path: Path) -> None:
    folder = tmp_path / "RetopoCAD"
    folder.mkdir()
    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    service = ProjectService(db)

    proj = service.register_existing_project(folder, name="RetopoCAD", description="STEP export utility")
    assert proj.status == "ongoing"

    completed = service.toggle_status(proj.id)
    assert completed is not None
    assert completed.status == "completed"

    hits = service.search_projects("Retopo")
    assert [item.id for item in hits] == [proj.id]
    assert ProjectRepository(db).search("STEP")[0].status == "completed"

    reopened = service.toggle_status(proj.id)
    assert reopened is not None
    assert reopened.status == "ongoing"


def test_register_existing_folder_does_not_create_or_modify_files_and_new_folder_requires_opt_in(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "StudioRig"
    (existing / "scenes").mkdir(parents=True)
    (existing / "scenes" / "rig_v01.ma").write_text("// maya ascii\n", encoding="utf-8")
    before_dirs, before_files = _snapshot_tree(existing)

    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    service = ProjectService(db)

    registered = service.register_existing_project(existing, name="StudioRig")
    assert registered.abs_path == str(existing.resolve())
    assert _snapshot_tree(existing) == (before_dirs, before_files)

    unconfirmed_target = tmp_path / "ShouldNotExist"
    with pytest.raises(PermissionError):
        service.create_new_project(unconfirmed_target, name="Nope", confirm_create_folder=False)
    assert not unconfirmed_target.exists()

    confirmed_target = tmp_path / "ExplicitNewFolder"
    created_proj = service.create_new_project(
        confirmed_target,
        name="ExplicitNew",
        description="Created on user confirmation",
        confirm_create_folder=True,
    )
    assert confirmed_target.is_dir()
    assert list(confirmed_target.iterdir()) == []
    assert created_proj.abs_path == str(confirmed_target.resolve())


def test_ui_projects_grid_detail_navigation_search_and_open_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    opened_urls: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened_urls.append(url.toLocalFile()) or True)

    ws_root = tmp_path / "Workspace"
    proj_a = ws_root / "Action_Director"
    proj_b = ws_root / "Archive_Book"
    proj_c = ws_root / "Suggested_Node"
    proj_d = ws_root / "Whisper_Confirm"
    for folder in (proj_a, proj_b, proj_c, proj_d):
        folder.mkdir(parents=True)
    (proj_c / "node.blend").write_bytes(b"BLEND")
    (proj_d / "art.psd").write_bytes(b"8BPS")

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    bus = EventBus()
    ws_service = WorkspaceService(db, bus, window_ms=150)
    proj_service = ProjectService(db, bus, workspace_service=ws_service)
    ws_service.set_project_service(proj_service)

    ws_service.add_workspace(ws_root, background_scan=False)
    p1 = proj_service.register_existing_project(proj_a, name="Action Director", description="Character tool")
    p2 = proj_service.register_existing_project(proj_b, name="Archive Book", description="Completed manual")
    proj_service.toggle_status(p2.id)

    window = MainWindow(
        event_bus=bus,
        app_paths=app_paths,
        workspace_service=ws_service,
        project_service=proj_service,
    )
    window.show()
    try:
        _wait_qt_pool()
        assert window._projects_view._whisper_bar.isVisible() is True

        # Confirm one suggestion via whisper Register, then dismiss the remaining one via ×.
        window._projects_view._whisper_register_btn.click()
        _wait_qt_pool()
        assert len(proj_service.list_projects()) == 3
        assert window._projects_view._whisper_bar.isVisible() is True

        window._projects_view._whisper_dismiss_btn.click()
        _wait_qt_pool()
        assert window._projects_view._whisper_bar.isVisible() is False
        assert proj_service.discover_suggestions(ws_service.cached_workspaces()[0].id) == []

        cards = window._projects_view.findChildren(ProjectCard)
        assert len(cards) == 3

        # Live search filters cards while keeping completed projects searchable.
        window._search_input.setText("Archive")
        QCoreApplication.processEvents()
        filtered_cards = window._projects_view.findChildren(ProjectCard)
        assert [c.project_id for c in filtered_cards] == [p2.id]

        window._search_input.setText("")
        QCoreApplication.processEvents()

        # Click project card -> opens ProjectDetailView -> toggle status -> Open folder -> Back.
        window._projects_view.project_selected.emit(p1.id)
        _wait_qt_pool()
        assert window._stack.currentWidget() is window._project_detail_view
        assert window._project_detail_view._title_label.text() == "Action Director"

        window._project_detail_view._toggle_status_btn.click()
        _wait_qt_pool()
        assert proj_service.get_project(p1.id).status == "completed"  # type: ignore[union-attr]
        assert window._project_detail_view._toggle_status_btn.text() == "Reopen ongoing"

        window._project_detail_view._open_folder_btn.click()
        assert os.path.normcase(opened_urls[-1]) == os.path.normcase(str(proj_a.resolve()))

        window._project_detail_view._back_btn.click()
        QCoreApplication.processEvents()
        assert window._stack.currentWidget() is window._projects_view
    finally:
        window.close()
        ws_service.shutdown()
        app.processEvents()


def test_register_project_dialog_validation_and_opt_in_create_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    existing_dir = tmp_path / "ExistingStudy"
    existing_dir.mkdir()

    dialog = RegisterProjectDialog()
    assert dialog._create_checkbox.isChecked() is False

    # Missing folder rejects with inline error when opt-in is unchecked.
    missing_dir = tmp_path / "MissingFolder"
    dialog._name_input.setText("Missing")
    dialog._path_input.setText(str(missing_dir))
    dialog._on_confirm()
    assert dialog.result_input() is None
    assert dialog._error_label.isHidden() is False

    # Checking opt-in allows creating a new empty folder on confirmation.
    dialog._create_checkbox.setChecked(True)
    dialog._on_confirm()
    created_input = dialog.result_input()
    assert created_input is not None
    assert created_input.create_folder is True
    assert created_input.name == "Missing"

    # Unchecked with existing directory yields read-only registration input.
    dialog2 = RegisterProjectDialog()
    dialog2._path_input.setText(str(existing_dir))
    dialog2._name_input.setText("Existing Study")
    dialog2._desc_input.setText("Rig study")
    dialog2._on_confirm()
    existing_input = dialog2.result_input()
    assert existing_input is not None
    assert existing_input.create_folder is False
    assert existing_input.description == "Rig study"
    dialog.close()
    dialog2.close()
    app.processEvents()
