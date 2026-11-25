"""Unit and UI tests for Polish Pass D: project deletion, Year/Month grouping, and creation date."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDate, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QLabel,
    QLineEdit,
    QPushButton,
)

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import Project, Workspace
from work_memory.services.project_service import ProjectService
from work_memory.storage.database import Database
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.views.delete_project_dialog import DeleteProjectDialog
from work_memory.ui.views.projects_view import ProjectsView
from work_memory.ui.views.register_project_dialog import (
    RegisterProjectDialog,
    local_date_to_created_utc,
)
from work_memory.ui.widgets.project_card import ProjectCard
from work_memory.ui.widgets.project_date_groups import (
    CollapsibleYearSection,
    group_projects_by_creation_date,
)


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _flush_qt() -> None:
    for _ in range(5):
        QThreadPool.globalInstance().waitForDone(2000)
        QCoreApplication.processEvents()


def test_register_dialog_mm_dd_yyyy_picker_and_custom_created_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RegisterProjectDialog provides MM/DD/YYYY picker and persists custom created_at_utc."""
    _ensure_qapp(monkeypatch)
    proj_dir = tmp_path / "RetroRig"
    proj_dir.mkdir()
    sample = proj_dir / "rig.blend"
    sample.write_bytes(b"BLEND")
    before_sha = hashlib.sha256(sample.read_bytes()).hexdigest()

    dlg = RegisterProjectDialog()
    date_edit = dlg.findChild(QDateEdit, "regCreatedDateEdit")
    assert date_edit is not None
    assert date_edit.displayFormat() == "MM/dd/yyyy"
    assert date_edit.date() == QDate.currentDate()

    dlg._name_input.setText("Retro Rig")
    dlg._path_input.setText(str(proj_dir))
    date_edit.setDate(QDate(2024, 3, 15))
    dlg._on_confirm()

    res = dlg.result_input()
    assert res is not None and res.created_date == date(2024, 3, 15)
    dlg.close()

    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    svc = ProjectService(db, EventBus(), app_paths=paths)

    created_utc = local_date_to_created_utc(res.created_date)
    proj = svc.register_existing_project(
        res.folder_path, name=res.name, created_at_utc=created_utc
    )
    assert proj.created_at_utc.startswith("2024-03-1")
    assert hashlib.sha256(sample.read_bytes()).hexdigest() == before_sha


def test_delete_project_dialog_guard_card_isolation_and_readonly_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete requires typing 'delete', deletes DB+cover only, and never mutates disk."""
    _ensure_qapp(monkeypatch)
    dlg = DeleteProjectDialog("Alpha Studio")
    inp = dlg.findChild(QLineEdit, "deleteConfirmInput")
    btn = dlg.findChild(QPushButton, "deleteConfirmButton")
    assert inp is not None and btn is not None
    assert btn.isEnabled() is False

    for bad in ("", "yes", "del", "remove"):
        inp.setText(bad)
        assert btn.isEnabled() is False

    inp.setText(" DELETE ")
    assert btn.isEnabled() is True
    dlg.close()

    # ProjectCard delete button emits delete_requested WITHOUT card.clicked.
    ws_dir = tmp_path / "Workspace"
    p_dir = ws_dir / "Alpha"
    p_dir.mkdir(parents=True)
    disk_file = p_dir / "asset.png"
    img = QImage(64, 40, QImage.Format.Format_ARGB32)
    img.fill(QColor("#4477aa"))
    assert img.save(str(disk_file), "PNG")
    before_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in p_dir.iterdir()}

    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    svc = ProjectService(db, EventBus(), app_paths=paths)
    proj = svc.register_existing_project(p_dir, name="Alpha")
    proj = svc.set_project_cover(proj.id, disk_file)
    cover_file = svc.get_project_cover_path(proj)
    assert cover_file is not None and cover_file.is_file()

    card = ProjectCard(proj, view_mode="medium")
    card_clicks: list[str] = []
    card_deletes: list[str] = []
    card.clicked.connect(card_clicks.append)
    card.delete_requested.connect(card_deletes.append)
    del_btn = card.findChild(QPushButton, "projectDeleteButton")
    assert del_btn is not None
    QTest.mouseClick(del_btn, Qt.MouseButton.LeftButton)
    assert card_deletes == [proj.id] and card_clicks == []
    card.close()

    assert svc.delete_project(proj.id) is True
    assert svc.get_project(proj.id) is None
    assert not cover_file.exists()
    after_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in p_dir.iterdir()}
    assert after_files == before_files


def test_projects_view_year_collapsible_and_vertical_month_grouping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ProjectsView groups by collapsible bold Year + vertical Month in creation order."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    bus = EventBus()

    ws_dir = tmp_path / "Work"
    for folder in ("Nov26", "May26", "Mar24"):
        (ws_dir / folder).mkdir(parents=True)
    ws = WorkspaceRepository(db).create(Workspace(name="Work", root_path=str(ws_dir)))
    repo = ProjectRepository(db)
    p_nov = repo.create(
        Project(
            workspace_id=ws.id, name="Nov Shot", rel_path="Nov26", abs_path=str(ws_dir / "Nov26"),
            created_at_utc="2026-11-18T12:00:00Z",
        )
    )
    p_may = repo.create(
        Project(
            workspace_id=ws.id, name="May Lookdev", rel_path="May26", abs_path=str(ws_dir / "May26"),
            created_at_utc="2026-05-04T12:00:00Z",
        )
    )
    p_mar = repo.create(
        Project(
            workspace_id=ws.id, name="Old Study", rel_path="Mar24", abs_path=str(ws_dir / "Mar24"),
            created_at_utc="2024-03-15T12:00:00Z",
        )
    )

    pinned, buckets = group_projects_by_creation_date([p_may, p_mar, p_nov])
    assert pinned == []
    assert [y for y, _m in buckets] == [2026, 2024]
    assert [m for m, _items in buckets[0][1]] == [11, 5]

    svc = ProjectService(db, bus, app_paths=paths)
    view = ProjectsView(svc, bus, app_paths=paths)
    view.resize(1120, 720)
    view.show()
    _flush_qt()
    try:
        cards = view.findChildren(ProjectCard)
        assert len(cards) == 3

        hdr_2026 = view.findChild(QPushButton, "projectYearHeader_2026")
        hdr_2024 = view.findChild(QPushButton, "projectYearHeader_2024")
        m_nov = view.findChild(QLabel, "projectMonthHeader_2026_11")
        m_may = view.findChild(QLabel, "projectMonthHeader_2026_05")
        m_mar = view.findChild(QLabel, "projectMonthHeader_2024_03")
        assert all(w is not None for w in (hdr_2026, hdr_2024, m_nov, m_may, m_mar))
        assert m_nov.mapTo(view, m_nov.rect().topLeft()).y() < m_may.mapTo(view, m_may.rect().topLeft()).y()  # type: ignore[union-attr]

        # Collapse 2024 and confirm body hides cleanly and stays collapsed on view mode switch.
        hdr_2024.click()  # type: ignore[union-attr]
        QCoreApplication.processEvents()
        sec_2024 = hdr_2024.parentWidget()  # type: ignore[union-attr]
        assert isinstance(sec_2024, CollapsibleYearSection)
        assert sec_2024._body.isVisible() is False

        view.set_view_mode("list")
        _flush_qt()
        hdr_2024_list = view.findChild(QPushButton, "projectYearHeader_2024")
        assert hdr_2024_list is not None
        assert hdr_2024_list.parentWidget()._body.isVisible() is False  # type: ignore[union-attr]
        assert len(view.findChildren(ProjectCard)) == 3
    finally:
        view.close()
        view.deleteLater()
        _flush_qt()
