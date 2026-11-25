"""Unit and UI tests for Phase 9A UI polish, gallery modes, scrolling, and file opening."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDate, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

from work_memory.config.paths import AppPaths, resolve_app_paths
from work_memory.config.settings import AppSettings, load_settings, save_settings
from work_memory.core.event_bus import EventBus
from work_memory.core.models import ObservedEvent, Project, Workspace
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.project_service import ProjectService
from work_memory.services.relink_service import RelinkService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.main_window import MainWindow
from work_memory.ui.theme import build_stylesheet
from work_memory.ui.widgets.gallery_controls import compute_gallery_columns
from work_memory.ui.widgets.milestone_preview_dialog import MilestonePreviewDialog
from work_memory.ui.widgets.project_card import ProjectCard


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _cleanup_widget(widget: object) -> None:
    widget.close()  # type: ignore[attr-defined]
    widget.deleteLater()  # type: ignore[attr-defined]
    _flush_qt()


def _flush_qt() -> None:
    for _ in range(5):
        QThreadPool.globalInstance().waitForDone(2000)
        QCoreApplication.processEvents()


def _snapshot_tree(root: Path) -> dict[str, tuple[str, int]]:
    return {
        p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in root.rglob("*") if p.is_file()
    }


def _init_test_env(tmp_path: Path) -> tuple[AppPaths, Database, Path]:
    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    db = Database(app_paths.db_path)
    db.run_migrations()
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    return app_paths, db, ws_dir


def test_gallery_view_mode_persists_and_falls_back(tmp_path: Path) -> None:
    """All 4 gallery view modes persist cleanly in settings.json and invalid values fall back."""
    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    for mode in ("list", "small", "medium", "large"):
        save_settings(app_paths, AppSettings(gallery_view_mode=mode))
        assert load_settings(app_paths).gallery_view_mode == mode

    settings_file = app_paths.base_dir / "settings.json"
    raw = json.loads(settings_file.read_text(encoding="utf-8"))
    raw["gallery_view_mode"] = "giant_invalid"
    settings_file.write_text(json.dumps(raw), encoding="utf-8")
    assert load_settings(app_paths).gallery_view_mode == "medium"


def test_theme_dark_scrollbars_and_shell_tab_nofocus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Theme QSS styles dark scrollbars and shell tabs/buttons disable focus rects."""
    _ensure_qapp(monkeypatch)
    qss = build_stylesheet()
    for token in ("QScrollBar:vertical", "QScrollBar:horizontal", "#17191d", "#2d323b", "#3d4450", "outline: none"):
        assert token in qss

    app_paths = resolve_app_paths(tmp_path / "app")
    app_paths.ensure_directories()
    win = MainWindow(EventBus(), app_paths)
    try:
        assert win._projects_tab.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert win._history_tab.focusPolicy() == Qt.FocusPolicy.NoFocus
        for obj_name in ("brandButton", "captureButton", "settingsButton", "statusDotButton"):
            btn = win.findChild(QPushButton, obj_name)
            assert btn is not None and btn.focusPolicy() == Qt.FocusPolicy.NoFocus
    finally:
        _cleanup_widget(win)


def test_projects_view_modes_responsive_columns_and_list_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ProjectsView switches List/S/M/L modes, persists choice, and keeps pin clicks separate."""
    _ensure_qapp(monkeypatch)
    app_paths, db, ws_dir = _init_test_env(tmp_path)
    bus = EventBus()
    ps = ProjectService(db, bus)
    for idx in range(5):
        p_dir = ws_dir / f"Proj_{idx}"
        p_dir.mkdir()
        ps.register_existing_project(p_dir, name=f"Project {idx}", description=f"Desc {idx}")

    settings = AppSettings()
    from work_memory.ui.views.projects_view import ProjectsView

    view = ProjectsView(ps, bus, settings=settings, app_paths=app_paths)
    view.resize(1120, 720)
    view.show()
    _flush_qt()
    try:
        assert compute_gallery_columns("list", 1120) == 1
        assert compute_gallery_columns("small", 1120) == 4
        assert compute_gallery_columns("medium", 1120) == 3
        assert compute_gallery_columns("large", 1120) == 2

        for mode, exp_cols in (("small", 4), ("large", 2), ("list", 1), ("medium", 3)):
            btn = view.findChild(QPushButton, f"viewModeBtn_{mode}")
            assert btn is not None and btn.focusPolicy() == Qt.FocusPolicy.NoFocus
            btn.click()
            _flush_qt()
            assert view.view_mode == mode
            assert view._grid_columns == exp_cols
            assert load_settings(app_paths).gallery_view_mode == mode

        view.findChild(QPushButton, "viewModeBtn_list").click()  # type: ignore[union-attr]
        _flush_qt()
        list_cards = view.findChildren(ProjectCard)
        assert list_cards and list_cards[0].view_mode == "list"
        assert list_cards[0]._cover.width() == 96 and list_cards[0]._cover.height() == 60

        clicked: list[str] = []
        pinned: list[str] = []
        list_cards[0].clicked.connect(clicked.append)
        list_cards[0].pin_toggled.connect(pinned.append)
        pin_btn = list_cards[0].findChild(QPushButton, "projectPinButton")
        assert pin_btn is not None
        QTest.mouseClick(pin_btn, Qt.MouseButton.LeftButton)
        assert pinned == [list_cards[0].project_id] and clicked == []

        grid_card = ProjectCard(list_cards[0]._project, view_mode="medium")
        grid_card.resize(320, 260)
        grid_card.show()
        _flush_qt()
        assert grid_card._cover.height() == 200
        _cleanup_widget(grid_card)
    finally:
        _cleanup_widget(view)


def test_independent_page_scrolling_and_history_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each page scrolls independently; History pins calendar top-left and resets detail scroll."""
    _ensure_qapp(monkeypatch)
    app_paths, db, ws_dir = _init_test_env(tmp_path)
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(ws_dir)))
    projs = []
    for idx in range(12):
        p_dir = ws_dir / f"P_{idx:02d}"
        p_dir.mkdir()
        projs.append(ProjectRepository(db).create(Project(workspace_id=ws.id, name=f"Project {idx:02d}", rel_path=f"P_{idx:02d}", abs_path=str(p_dir))))
    today_utc = f"{date.today().strftime('%Y-%m-%d')}T12:00:00Z"
    ObservedEventRepository(db).insert_batch([
        ObservedEvent(ws.id, f"P_00/file_{i:02d}.exr", "modified", today_utc, project_id=projs[0].id)
        for i in range(28)
    ])

    bus = EventBus()
    win = MainWindow(
        bus, app_paths,
        workspace_service=WorkspaceService(db, bus, window_ms=200),
        project_service=ProjectService(db, bus),
        history_service=HistoryService(db, bus, app_paths=app_paths),
    )
    win.resize(1040, 560)
    win.show()
    _flush_qt()
    try:
        assert not isinstance(win._stack.parentWidget().parentWidget(), QScrollArea)
        assert len({win._projects_view.scroll_area, win._history_view.scroll_area, win._settings_view.scroll_area, win._project_detail_view.scroll_area}) == 4

        win._projects_view.vertical_scroll_bar().setValue(60)
        assert win._projects_view.vertical_scroll_bar().value() > 0

        win._show_page("settings")
        _flush_qt()
        win._settings_view.vertical_scroll_bar().setValue(80)
        assert win._settings_view.vertical_scroll_bar().value() > 0
        assert win._projects_view.vertical_scroll_bar().value() > 0

        win._show_page("history")
        _flush_qt()
        cal_h = win._history_view._calendar_card.height()
        assert 260 <= cal_h <= 460
        assert win._history_view.vertical_scroll_bar().maximum() > 0
        win._history_view.vertical_scroll_bar().setValue(90)
        assert win._history_view.vertical_scroll_bar().value() > 0
        assert win._history_view._calendar_card.height() == cal_h

        other_day = QDate(date.today().year, date.today().month, 1 if date.today().day != 1 else 2)
        win._history_view._on_date_selected(other_day)
        assert win._history_view.vertical_scroll_bar().value() == 0

        win._open_project_detail(projs[0].id)
        _flush_qt()
        win._project_detail_view.vertical_scroll_bar().setValue(100)
        assert win._project_detail_view.vertical_scroll_bar().value() > 0
        win._open_project_detail(projs[1].id)
        assert win._project_detail_view.vertical_scroll_bar().value() == 0
    finally:
        _cleanup_widget(win)


def test_readonly_file_resolution_and_click_to_open_with_missing_toast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File resolver locates real files read-only, rejects traversal, and toasts when missing."""
    _ensure_qapp(monkeypatch)
    app_paths, db, ws_dir = _init_test_env(tmp_path)
    alpha_dir = ws_dir / "Alpha"
    (alpha_dir / "scenes").mkdir(parents=True)
    (alpha_dir / "notes").mkdir(parents=True)
    (alpha_dir / "renders").mkdir(parents=True)
    rig_file = alpha_dir / "scenes" / "rig.blend"
    design_file = alpha_dir / "notes" / "design.txt"
    frame1 = alpha_dir / "renders" / "shot_0001.exr"
    rig_file.write_bytes(b"BLEND")
    design_file.write_text("notes", encoding="utf-8")
    frame1.write_bytes(b"EXR1")

    relinked_dir = tmp_path / "MovedBeta"
    relinked_dir.mkdir(parents=True)
    beta_obj = relinked_dir / "model.obj"
    beta_obj.write_text("v 0 0 0\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")

    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(ws_dir)))
    alpha = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="Alpha", rel_path="Alpha", abs_path=str(alpha_dir))
    )
    beta = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="Beta", rel_path="Beta", abs_path=str(ws_dir / "Beta"))
    )
    (ws_dir / "Beta").mkdir(exist_ok=True)
    RelinkService(db).relink_project(beta.id, relinked_dir)

    today_utc = f"{date.today().strftime('%Y-%m-%d')}T10:00:00Z"
    ev = ObservedEventRepository(db).insert(
        ObservedEvent(ws.id, "Alpha/scenes/rig.blend", "modified", today_utc, project_id=alpha.id, is_milestone=True)
    )
    cap, _atts = CaptureService(db, app_paths).create_capture(
        project_id=alpha.id, note_text="Checked rig", linked_file="notes/design.txt", is_milestone=True
    )
    hist = HistoryService(db, app_paths=app_paths)

    before = _snapshot_tree(ws_dir)
    assert hist.resolve_file_path("Alpha/scenes/rig.blend", project_id=alpha.id).resolved_path == rig_file.resolve()
    assert hist.resolve_file_path("notes/design.txt", project_id=alpha.id).resolved_path == design_file.resolve()
    seq_res = hist.resolve_file_path("Alpha/renders/shot_0001.exr .. shot_0004.exr (4 frames)", project_id=alpha.id)
    assert seq_res.found and seq_res.resolved_path == frame1.resolve()
    assert hist.resolve_file_path("Beta/model.obj", project_id=beta.id).resolved_path == beta_obj.resolve()
    assert hist.resolve_file_path("../../secret.txt", project_id=alpha.id).found is False
    assert hist.resolve_file_path("Alpha/../secret.txt", project_id=alpha.id).found is False
    assert hist.resolve_file_path("Alpha/scenes/missing.blend", project_id=alpha.id).found is False
    assert _snapshot_tree(ws_dir) == before

    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)

    bus = EventBus()
    win = MainWindow(bus, app_paths, project_service=ProjectService(db, bus), history_service=hist)
    win.show()
    _flush_qt()
    try:
        win._show_page("history")
        _flush_qt()

        # Star button click must NOT open file; file row click opens file.
        star_btn = win._history_view._timeline.findChild(QPushButton, "timelineStarButton")
        assert star_btn is not None
        QTest.mouseClick(star_btn, Qt.MouseButton.LeftButton)
        _flush_qt()
        assert opened == []

        file_row = win._history_view._timeline.findChild(object, "timelineFileRow")
        assert file_row is not None
        QTest.mouseClick(file_row, Qt.MouseButton.LeftButton)  # type: ignore[arg-type]
        _flush_qt()
        assert Path(opened[-1].toLocalFile()).resolve() == rig_file.resolve()

        cap_link = win._history_view._timeline.findChild(QPushButton, "captureLinkedFileLink")
        assert cap_link is not None
        QTest.mouseClick(cap_link, Qt.MouseButton.LeftButton)
        _flush_qt()
        assert Path(opened[-1].toLocalFile()).resolve() == design_file.resolve()

        # MilestonePreviewDialog path link emits file_open_requested.
        detail = hist.get_milestone_detail("observed", ev.id)
        assert detail is not None
        dlg = MilestonePreviewDialog(detail)
        dlg_opened: list[tuple[str, str]] = []
        dlg.file_open_requested.connect(lambda r, p: dlg_opened.append((r, p)))
        dlg_link = dlg.findChild(QPushButton, "milestoneFileLink")
        assert dlg_link is not None
        QTest.mouseClick(dlg_link, Qt.MouseButton.LeftButton)
        assert dlg_opened == [("Alpha/scenes/rig.blend", alpha.id)]
        dlg.close()

        # ProjectDetailView also opens clicked timeline files.
        win._open_project_detail(alpha.id)
        _flush_qt()
        detail_file_row = win._project_detail_view._timeline.findChild(object, "timelineFileRow")
        assert detail_file_row is not None
        QTest.mouseClick(detail_file_row, Qt.MouseButton.LeftButton)  # type: ignore[arg-type]
        _flush_qt()
        assert Path(opened[-1].toLocalFile()).resolve() == rig_file.resolve()

        # Missing file click shows quiet info toast without crashing or opening URL.
        rig_file.unlink()
        prev_count = len(opened)
        QTest.mouseClick(detail_file_row, Qt.MouseButton.LeftButton)  # type: ignore[arg-type]
        _flush_qt()
        assert len(opened) == prev_count
        assert any("File not found on disk: rig.blend" in lbl.text() for t in win._active_toasts for lbl in t.findChildren(QLabel))
        assert win._active_toasts[-1].findChild(QPushButton, "toastAddNoteButton") is None
        assert cap.id
    finally:
        _cleanup_widget(win)
