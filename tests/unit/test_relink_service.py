"""Unit tests for Phase 8B: Project & Workspace Relinking and Missing-File Detection."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import CaptureEntry, ObservedEvent, Project, Workspace
from work_memory.services.relink_service import RelinkService, is_project_folder_missing
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.theme import build_stylesheet
from work_memory.ui.widgets.project_card import ProjectCard
from work_memory.ui.widgets.project_hero import ProjectHeroSection


def test_relink_project_preserves_history_and_detects_missing_files(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    bus = EventBus()

    ws_root = tmp_path / "WorkDrive"
    proj_dir = ws_root / "FilmCut"
    proj_dir.mkdir(parents=True)
    (proj_dir / "shot_01.blend").write_text("blend-data", encoding="utf-8")

    ws = WorkspaceRepository(db).create(Workspace(name="WorkDrive", root_path=str(ws_root)))
    proj = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="FilmCut", rel_path="FilmCut", abs_path=str(proj_dir))
    )
    ObservedEventRepository(db).insert_batch(
        [
            ObservedEvent(
                workspace_id=ws.id,
                project_id=proj.id,
                rel_path="FilmCut/shot_01.blend",
                event_type="created",
                occurred_at_utc="2026-11-24T09:00:00Z",
            ),
            ObservedEvent(
                workspace_id=ws.id,
                project_id=proj.id,
                rel_path="FilmCut/missing_ref.png",
                event_type="modified",
                occurred_at_utc="2026-11-24T09:05:00Z",
            ),
        ]
    )
    CaptureRepository(db).create(
        CaptureEntry(
            project_id=proj.id,
            rel_path="FilmCut/notes_doc.txt",
            note_text="Key lighting note",
            captured_at_utc="2026-11-24T09:10:00Z",
        )
    )

    relink = RelinkService(db, bus)
    assert is_project_folder_missing(proj) is False
    # Prefix must not be doubled: returns project-relative missing paths only.
    assert relink.check_project_missing_files(proj.id) == ["missing_ref.png", "notes_doc.txt"]

    # Move folder on disk -> missing detected, DB history preserved.
    moved_dir = tmp_path / "ExternalDrive" / "FilmCut_Moved"
    moved_dir.parent.mkdir(parents=True)
    shutil.move(str(proj_dir), str(moved_dir))

    assert is_project_folder_missing(proj) is True
    assert len(ObservedEventRepository(db).list_by_project(proj.id)) == 2
    assert len(CaptureRepository(db).list_recent(project_id=proj.id)) == 1

    updated = relink.relink_project(proj.id, moved_dir)
    assert updated.abs_path == str(moved_dir.resolve())
    assert is_project_folder_missing(updated) is False
    assert relink.check_project_missing_files(proj.id) == ["missing_ref.png", "notes_doc.txt"]


def test_relink_workspace_updates_root_and_all_child_projects(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    bus = EventBus()

    old_root = tmp_path / "OldDrive"
    (old_root / "ProjA").mkdir(parents=True)
    (old_root / "Nested" / "ProjB").mkdir(parents=True)

    ws_svc = WorkspaceService(db, bus)
    try:
        ws = ws_svc.add_workspace(old_root, background_scan=False)
        proj_repo = ProjectRepository(db)
        pa = proj_repo.create(
            Project(workspace_id=ws.id, name="ProjA", rel_path="ProjA", abs_path=str(old_root / "ProjA"))
        )
        pb = proj_repo.create(
            Project(
                workspace_id=ws.id,
                name="ProjB",
                rel_path="Nested/ProjB",
                abs_path=str(old_root / "Nested" / "ProjB"),
            )
        )

        new_root = tmp_path / "NewDrive"
        shutil.move(str(old_root), str(new_root))

        relink = RelinkService(db, bus, workspace_service=ws_svc)
        count = relink.relink_workspace(ws.id, new_root, background_scan=False)
        assert count == 2

        ws_after = WorkspaceRepository(db).get_by_id(ws.id)
        assert ws_after is not None and Path(ws_after.root_path) == new_root.resolve()
        pa_after = proj_repo.get(pa.id)
        pb_after = proj_repo.get(pb.id)
        assert pa_after is not None and not is_project_folder_missing(pa_after)
        assert pb_after is not None and not is_project_folder_missing(pb_after)
    finally:
        ws_svc.shutdown()


def test_missing_folder_ui_badges_relink_buttons_and_dark_messagebox_theme(tmp_path: Path) -> None:
    _app = QApplication.instance() or QApplication([])
    qss = build_stylesheet()
    assert "QMessageBox QLabel" in qss
    assert "QMessageBox QPushButton" in qss

    missing_proj = Project(
        workspace_id="ws-1",
        name="zbrush",
        rel_path="zbrush",
        abs_path=str(tmp_path / "does_not_exist" / "zbrush"),
    )
    card = ProjectCard(missing_proj)
    pill = card.findChild(QLabel, "cardFolderMissingPill")
    relink_btn = card.findChild(QPushButton, "cardRelinkButton")
    assert pill is not None and pill.text() == "Folder missing"
    assert relink_btn is not None and relink_btn.text() == "Relink"

    clicked_ids: list[str] = []
    relink_ids: list[str] = []
    card.clicked.connect(clicked_ids.append)
    card.relink_requested.connect(relink_ids.append)
    relink_btn.click()
    assert relink_ids == [missing_proj.id]
    assert clicked_ids == []

    hero = ProjectHeroSection(lambda: None, lambda: None, lambda: None)
    hero.render(missing_proj)
    assert hero.missing_pill.isHidden() is False
    assert hero.relink_btn.isHidden() is False
