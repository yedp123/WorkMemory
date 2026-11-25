"""Unit tests for Phase 8A: Project Summaries (Last Known State & Recent Activity)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThreadPool
from PySide6.QtWidgets import QApplication, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import (
    CalendarEvent,
    CaptureEntry,
    ObservedEvent,
    Project,
    SummaryReference,
    Workspace,
)
from work_memory.services.history_service import HistoryService
from work_memory.services.project_service import ProjectService
from work_memory.services.summary_service import SummaryService
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.views.project_detail_view import ProjectDetailView
from work_memory.ui.widgets.summary_panel import SummaryPanel


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _setup_db(tmp_path: Path) -> tuple[Database, Project]:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(tmp_path / "studio")))
    proj = ProjectRepository(db).create(Project(workspace_id=ws.id, name="FilmCut", rel_path="FilmCut"))
    return db, proj


def test_confirmed_empty_without_notes_and_prioritizes_explicit_notes(tmp_path: Path) -> None:
    db, proj = _setup_db(tmp_path)
    ev_repo = ObservedEventRepository(db)
    cap_repo = CaptureRepository(db)
    svc = SummaryService(db, tz=UTC)

    # Baseline-only or empty project must never fabricate confirmed claims.
    ev_repo.insert(
        ObservedEvent(
            workspace_id=proj.workspace_id,
            project_id=proj.id,
            rel_path="FilmCut/render_v01.exr",
            event_type="created",
            is_baseline=True,
            occurred_at_utc="2026-11-20T10:00:00Z",
        )
    )
    empty_view = svc.get_project_summary(proj.id)
    assert empty_view.confirmed_text == ""
    assert "No file activity" in empty_view.inferred_text

    # Add non-baseline file change -> inferred_text populates, confirmed_text still empty.
    ev_repo.insert(
        ObservedEvent(
            workspace_id=proj.workspace_id,
            project_id=proj.id,
            rel_path="FilmCut/shot_02.blend",
            event_type="modified",
            is_baseline=False,
            occurred_at_utc="2026-11-22T14:30:00Z",
        )
    )
    obs_only = svc.get_project_summary(proj.id)
    assert obs_only.confirmed_text == ""
    assert "shot_02.blend" in obs_only.inferred_text
    assert "1 file changed" in obs_only.recent_summary

    # Add explicit user note -> appears in confirmed_text and takes priority.
    note = cap_repo.create(
        CaptureEntry(
            project_id=proj.id,
            note_text="Color grading pass locked for scene 3.",
            captured_at_utc="2026-11-23T09:15:00Z",
        )
    )
    with_note = svc.get_project_summary(proj.id)
    assert "Color grading pass locked for scene 3." in with_note.confirmed_text
    assert "shot_02.blend" in with_note.inferred_text
    assert any(r.item_type == "capture" and r.item_id == note.id for r in with_note.references)


def test_inferred_includes_upcoming_calendar_and_recent_session(tmp_path: Path) -> None:
    db, proj = _setup_db(tmp_path)
    ev_repo = ObservedEventRepository(db)
    cap_repo = CaptureRepository(db)
    cal_repo = CalendarRepo(db)
    svc = SummaryService(db, tz=UTC)

    ev_repo.insert(
        ObservedEvent(
            workspace_id=proj.workspace_id,
            project_id=proj.id,
            rel_path="FilmCut/edit_v4.prproj",
            event_type="modified",
            occurred_at_utc="2026-11-24T11:00:00Z",
        )
    )
    cap_repo.create(
        CaptureEntry(
            project_id=proj.id,
            note_text="Audio mix exported.",
            is_milestone=True,
            captured_at_utc="2026-11-24T11:10:00Z",
        )
    )
    future_utc = (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cal_repo.create(
        CalendarEvent(
            project_id=proj.id,
            title="Director review call",
            event_at_utc=future_utc,
            status="scheduled",
        )
    )

    view = svc.get_project_summary(proj.id)
    assert "edit_v4.prproj" in view.inferred_text
    assert "Director review call" in view.inferred_text
    assert "1 file changed, 1 note captured" in view.recent_summary
    assert any(r.item_type == "date" and r.local_date == "2026-11-24" for r in view.references)


def test_custom_summary_persists_across_refresh_and_clears_on_regenerate(tmp_path: Path) -> None:
    db, proj = _setup_db(tmp_path)
    ev_repo = ObservedEventRepository(db)
    svc = SummaryService(db, tz=UTC)

    saved = svc.save_custom_summary(proj.id, "Waiting on client VFX sign-off before final render.")
    assert saved.custom_text == "Waiting on client VFX sign-off before final render."

    # New observed event triggers refresh_generated_summary -> must NOT overwrite custom_text.
    ev_repo.insert(
        ObservedEvent(
            workspace_id=proj.workspace_id,
            project_id=proj.id,
            rel_path="FilmCut/comp_v9.nk",
            event_type="modified",
            occurred_at_utc="2026-11-24T12:00:00Z",
        )
    )
    svc.refresh_generated_summary(proj.id)

    reloaded = SummaryService(db, tz=UTC).get_project_summary(proj.id)
    assert reloaded.custom_text == "Waiting on client VFX sign-off before final render."
    proj_row = ProjectRepository(db).get(proj.id)
    assert proj_row is not None
    assert proj_row.summary_generated is not None and "comp_v9.nk" in proj_row.summary_generated

    # Regenerate clears custom override and returns fresh rule-based view.
    regen = svc.regenerate_summary(proj.id)
    assert regen.custom_text is None
    assert "comp_v9.nk" in regen.inferred_text


def test_summary_panel_and_detail_view_wiring(tmp_path: Path) -> None:
    _ensure_qapp()
    db, proj = _setup_db(tmp_path)
    cap_repo = CaptureRepository(db)
    cap = cap_repo.create(
        CaptureEntry(
            project_id=proj.id,
            note_text="Check lighting rig on shot 5.",
            is_milestone=False,
            captured_at_utc="2026-11-24T10:00:00Z",
        )
    )

    panel = SummaryPanel()
    svc = SummaryService(db, tz=UTC)
    view = svc.get_project_summary(proj.id)
    panel.set_summary(view)

    clicked_refs: list[SummaryReference] = []
    saved_texts: list[str] = []
    regen_count = 0
    panel.reference_clicked.connect(clicked_refs.append)
    panel.save_custom_requested.connect(saved_texts.append)
    panel.regenerate_requested.connect(lambda: nonlocal_inc())

    def nonlocal_inc() -> None:
        nonlocal regen_count
        regen_count += 1

    # Click reference chip
    note_btn = next(b for b in panel.findChildren(QPushButton) if b.text() == "Open latest note")
    note_btn.click()
    assert len(clicked_refs) == 1 and clicked_refs[0].item_id == cap.id

    # Edit and save custom summary
    panel._edit_btn.click()
    panel._editor.setPlainText("Custom state note")
    panel._save_btn.click()
    assert saved_texts == ["Custom state note"]

    panel._regen_btn.click()
    assert regen_count == 1

    # ProjectDetailView integration: load project and jump to date via summary reference
    bus = EventBus()
    proj_svc = ProjectService(db, bus)
    hist_svc = HistoryService(db, bus)
    detail = ProjectDetailView(
        project_service=proj_svc,
        history_service=hist_svc,
        event_bus=bus,
        summary_service=svc,
    )
    detail.show_project(proj.id, proj)
    QThreadPool.globalInstance().waitForDone(2000)
    QCoreApplication.processEvents()

    detail._on_summary_reference_clicked(
        SummaryReference(label="Jump to Nov 24", item_type="date", local_date="2026-11-24")
    )
    assert detail._selected_date is not None
    assert detail._selected_date.isoformat() == "2026-11-24"
