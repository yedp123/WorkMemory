"""Unit tests for Phase 5A Project Pinning and Milestone Starring."""

from __future__ import annotations

from datetime import UTC, date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import CaptureEntry, ObservedEvent, Project, Workspace
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.project_service import ProjectService
from work_memory.storage.database import Database
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.widgets.milestone_preview_dialog import MilestonePreviewDialog
from work_memory.ui.widgets.milestones_panel import MilestonesPanel
from work_memory.ui.widgets.project_card import ProjectCard


def _setup_db(tmp_path: Path) -> tuple[Database, Project, Project, Workspace]:
    paths = resolve_app_paths(tmp_path / "app")
    db = Database(paths.db_path)
    db.run_migrations()
    ws_dir = tmp_path / "workspace"
    (ws_dir / "alpha").mkdir(parents=True)
    (ws_dir / "beta").mkdir(parents=True)
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(ws_dir)))
    proj_repo = ProjectRepository(db)
    alpha = proj_repo.create(
        Project(
            workspace_id=ws.id,
            name="Alpha",
            rel_path="alpha",
            abs_path=str(ws_dir / "alpha"),
            last_activity_utc="2026-05-01T10:00:00Z",
        )
    )
    beta = proj_repo.create(
        Project(
            workspace_id=ws.id,
            name="Beta",
            rel_path="beta",
            abs_path=str(ws_dir / "beta"),
            last_activity_utc="2026-05-10T10:00:00Z",
        )
    )
    return db, alpha, beta, ws


def test_pinned_projects_sort_first_and_persist(tmp_path: Path) -> None:
    """Pinned projects sort ahead of newer unpinned projects and persist across DB reloads."""
    db, alpha, beta, _ws = _setup_db(tmp_path)
    bus = EventBus()
    service = ProjectService(db, event_bus=bus)

    # Initially Beta has newer activity so Beta comes first.
    initial = service.list_projects()
    assert [p.id for p in initial] == [beta.id, alpha.id]

    updated_events: list[Project] = []
    bus.project_updated.connect(lambda p: updated_events.append(p))

    assert service.toggle_pin(alpha.id) is True
    assert len(updated_events) == 1
    assert updated_events[0].id == alpha.id
    assert updated_events[0].is_pinned is True

    reordered = service.list_projects()
    assert [p.id for p in reordered] == [alpha.id, beta.id]
    assert reordered[0].is_pinned is True

    # Reload from a fresh Database instance against the same SQLite file.
    db2 = Database(db.db_path)
    db2.run_migrations()
    service2 = ProjectService(db2)
    reloaded = service2.list_projects()
    assert [p.id for p in reloaded] == [alpha.id, beta.id]
    assert reloaded[0].is_pinned is True

    # Unpinning restores activity ordering.
    assert service2.toggle_pin(alpha.id) is False
    assert [p.id for p in service2.list_projects()] == [beta.id, alpha.id]


def test_milestones_star_unstar_and_preserve_timeline(tmp_path: Path) -> None:
    """Starring observed/capture items surfaces them as milestones while keeping timeline intact."""
    db, alpha, _beta, ws = _setup_db(tmp_path)
    bus = EventBus()
    ev_repo = ObservedEventRepository(db)
    cap_repo = CaptureRepository(db)
    history = HistoryService(db, event_bus=bus, tz=UTC)

    ev1 = ev_repo.insert(
        ObservedEvent(
            workspace_id=ws.id,
            project_id=alpha.id,
            rel_path="alpha/shot_01.exr",
            event_type="created",
            occurred_at_utc="2026-05-10T09:00:00Z",
        )
    )
    ev2 = ev_repo.insert(
        ObservedEvent(
            workspace_id=ws.id,
            project_id=alpha.id,
            rel_path="alpha/shot_02.exr",
            event_type="modified",
            occurred_at_utc="2026-05-10T11:00:00Z",
        )
    )
    cap1 = cap_repo.create(
        CaptureEntry(
            project_id=alpha.id,
            rel_path="alpha/shot_01.exr",
            note_text="Client approved lighting pass",
            captured_at_utc="2026-05-10T12:00:00Z",
        )
    )

    milestone_signals: list[tuple[str, str, bool]] = []
    bus.milestone_updated.connect(lambda t, i, m: milestone_signals.append((t, i, m)))

    assert history.toggle_milestone("observed", ev1.id) is True
    assert history.toggle_milestone("capture", cap1.id) is True
    assert milestone_signals == [("observed", ev1.id, True), ("capture", cap1.id, True)]

    milestones = history.get_project_milestones(alpha.id)
    assert [(m.item_type, m.item_id) for m in milestones] == [
        ("capture", cap1.id),
        ("observed", ev1.id),
    ]

    # Critical: original chronological timeline MUST keep starred items intact.
    timeline = history.get_day_timeline(date(2026, 5, 10), project_id=alpha.id)
    observed_ids = [ev.id for grp in timeline.observed_groups for ev in grp.events]
    assert observed_ids == [ev2.id, ev1.id]
    assert [c.id for c in timeline.captures] == [cap1.id]
    assert timeline.captures[0].is_milestone is True
    starred_obs = next(ev for grp in timeline.observed_groups for ev in grp.events if ev.id == ev1.id)
    assert starred_obs.is_milestone is True

    # Unstarring removes from milestones without deleting underlying records.
    assert history.toggle_milestone("observed", ev1.id) is False
    assert history.toggle_milestone("capture", cap1.id) is False
    assert history.get_project_milestones(alpha.id) == []
    assert ev_repo.get(ev1.id) is not None
    assert cap_repo.get(cap1.id) is not None

    timeline_after = history.get_day_timeline(date(2026, 5, 10), project_id=alpha.id)
    assert [ev.id for grp in timeline_after.observed_groups for ev in grp.events] == [ev2.id, ev1.id]
    assert [c.id for c in timeline_after.captures] == [cap1.id]


def test_project_card_pin_button_does_not_open_detail() -> None:
    """Clicking ProjectCard's pin button emits pin_toggled without emitting clicked."""
    _app = QApplication.instance() or QApplication([])
    proj = Project(workspace_id="ws-1", name="Alpha", rel_path="alpha", is_pinned=False)
    card = ProjectCard(proj)

    clicked_ids: list[str] = []
    pinned_ids: list[str] = []
    card.clicked.connect(clicked_ids.append)
    card.pin_toggled.connect(pinned_ids.append)

    pin_btn = card.findChild(QPushButton, "projectPinButton")
    assert pin_btn is not None
    QTest.mouseClick(pin_btn, Qt.MouseButton.LeftButton)

    assert pinned_ids == [proj.id]
    assert clicked_ids == []

    panel = MilestonesPanel()
    assert panel.findChild(object, "milestonesEmptyLabel") is not None


def test_capture_milestone_detail_and_preview_dialog(tmp_path: Path) -> None:
    """Creating a milestone capture surfaces in milestones+timeline and loads full MilestoneDetail."""
    _app = QApplication.instance() or QApplication([])
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    ws_dir = tmp_path / "workspace"
    (ws_dir / "alpha").mkdir(parents=True)
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(ws_dir)))
    alpha = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="Alpha", rel_path="alpha", abs_path=str(ws_dir / "alpha"))
    )

    cap_svc = CaptureService(db, paths)
    history = HistoryService(db, app_paths=paths, tz=UTC)
    ev = ObservedEventRepository(db).insert(
        ObservedEvent(
            workspace_id=ws.id,
            project_id=alpha.id,
            rel_path="alpha/shot_01.exr",
            event_type="created",
            file_size=2048,
            is_milestone=True,
            occurred_at_utc="2026-05-10T09:00:00Z",
        )
    )
    entry, _atts = cap_svc.create_capture(
        project_id=alpha.id,
        note_text="Final lookdev sign-off",
        linked_file="alpha/shot_01.exr",
        is_milestone=True,
    )

    milestones = history.get_project_milestones(alpha.id)
    assert any(m.item_id == entry.id and m.item_type == "capture" for m in milestones)
    day_tl = history.get_day_timeline(date.today(), project_id=alpha.id)
    assert any(c.id == entry.id for c in day_tl.captures)

    cap_detail = history.get_milestone_detail("capture", entry.id)
    assert cap_detail is not None
    assert cap_detail.body_text == "Final lookdev sign-off"
    assert cap_detail.rel_path == "alpha/shot_01.exr"

    obs_detail = history.get_milestone_detail("observed", ev.id)
    assert obs_detail is not None
    assert obs_detail.event_type == "created"
    assert "alpha/shot_01.exr" in obs_detail.body_text

    dlg = MilestonePreviewDialog(cap_detail)
    jumped: list[object] = []
    dlg.jump_to_date_requested.connect(jumped.append)
    jump_btn = dlg.findChild(QPushButton, "milestoneJumpDateButton")
    assert jump_btn is not None
    QTest.mouseClick(jump_btn, Qt.MouseButton.LeftButton)
    assert len(jumped) == 1

