"""Unit and UI tests for Polish Pass C fixes, themes, branding, audio controls, and hardening."""

from __future__ import annotations

import hashlib
import json
import sys
import wave
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QSlider,
)

from work_memory.config.paths import resolve_app_paths
from work_memory.config.settings import AppSettings, load_settings, save_settings
from work_memory.core.event_bus import EventBus
from work_memory.core.models import DayMarkers, ObservedEvent, Project, Workspace
from work_memory.media import sound_effects
from work_memory.services import archive_safety, windows_state
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.notification_service import NotificationPayload
from work_memory.storage.database import Database
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui import app_icon
from work_memory.ui.capture.quick_capture_dialog import QuickCaptureDialog
from work_memory.ui.capture.toast_controller import ToastController
from work_memory.ui.main_window import MainWindow
from work_memory.ui.theme import build_stylesheet, set_active_theme
from work_memory.ui.theme_palettes import LIGHT_PALETTE
from work_memory.ui.views.settings_view import SettingsView
from work_memory.ui.widgets.calendar_day_button import CalendarDayButton
from work_memory.ui.widgets.video_player_panel import VideoPlayerPanel


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _flush_qt() -> None:
    for _ in range(5):
        QThreadPool.globalInstance().waitForDone(2000)
        QCoreApplication.processEvents()


def test_settings_roundtrip_audio_and_theme_mode(tmp_path: Path) -> None:
    """AppSettings persists sound_volume, sound_muted, and theme_mode with safe fallbacks."""
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()

    custom = AppSettings(sound_volume=42, sound_muted=True, theme_mode="light")
    save_settings(paths, custom)
    loaded = load_settings(paths)
    assert loaded.sound_volume == 42
    assert loaded.sound_muted is True
    assert loaded.theme_mode == "light"

    settings_file = paths.base_dir / "settings.json"
    raw = json.loads(settings_file.read_text(encoding="utf-8"))
    raw["theme_mode"] = "neon_ultra"
    raw["sound_volume"] = 500
    settings_file.write_text(json.dumps(raw), encoding="utf-8")

    fallback = load_settings(paths)
    assert fallback.theme_mode == "dark"
    assert fallback.sound_volume == 100


def test_sound_engine_wakeup_buffer_volume_mute_and_test_cues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Click WAV includes Bluetooth wake-up lead-in (>0.12s); volume/mute & tests work cleanly."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()

    click_wav, ding_wav = sound_effects.ensure_sound_assets(paths.sounds_cache_dir, volume=75)
    with wave.open(str(click_wav), "rb") as wf:
        duration_sec = wf.getnframes() / float(wf.getframerate())
    assert duration_sec > 0.12
    assert ding_wav.is_file()

    played: list[tuple[str, float]] = []
    settings = AppSettings(enable_sounds=True, sound_volume=60, sound_muted=False)
    player = sound_effects.SoundEffectsPlayer(paths.sounds_cache_dir, settings)
    monkeypatch.setattr(
        player,
        "_play_qt_effect",
        lambda kind, _path, vol: played.append((kind, vol)) or True,
    )
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    assert player.play_screenshot_click() is True
    assert played[-1] == ("click", pytest.approx(0.60))

    settings.sound_volume = 0
    assert player.play_notification_ding() is False
    # Test cue uses minimum audible 15% floor when unmuted at 0%.
    assert player.play_test_ding() is True
    assert played[-1] == ("ding", pytest.approx(0.15))

    settings.sound_muted = True
    assert player.play_test_click() is False
    assert player.play_notification_ding() is False


def test_windows_state_allows_quns_busy_on_multimonitor(monkeypatch: pytest.MonkeyPatch) -> None:
    """QUNS_BUSY (2) does NOT suppress notifications; D3D fullscreen (3) and presentation (4) do."""

    class _FakeShell32:
        def __init__(self, state_val: int) -> None:
            self._val = state_val

        def SHQueryUserNotificationState(self, ptr: object) -> int:
            import ctypes

            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_int)).contents.value = self._val  # type: ignore[arg-type]
            return 0

    class _FakeWindll:
        def __init__(self, state_val: int) -> None:
            self.shell32 = _FakeShell32(state_val)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_state.ctypes, "windll", _FakeWindll(2), raising=False)
    assert windows_state.is_fullscreen_or_busy() is False

    for suppressed in (3, 4):
        monkeypatch.setattr(windows_state.ctypes, "windll", _FakeWindll(suppressed), raising=False)
        assert windows_state.is_fullscreen_or_busy() is True


def test_toast_milestone_stars_observed_idempotently_and_opens_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clicking ★ Milestone on ToastPopup stars observed event and opens pre-starred QuickCapture."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()

    ws_dir = tmp_path / "Workspace"
    proj_dir = ws_dir / "OKR"
    proj_dir.mkdir(parents=True)
    target_file = proj_dir / "01 - Copy.png"
    target_file.write_bytes(b"PNG")
    before_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()

    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(ws_dir)))
    proj = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="OKR", rel_path="OKR", abs_path=str(proj_dir))
    )
    ev = ObservedEventRepository(db).insert(
        ObservedEvent(ws.id, "OKR/01 - Copy.png", "created", "2026-11-25T05:00:00Z", project_id=proj.id)
    )

    bus = EventBus()
    hist = HistoryService(db, bus, app_paths=paths)
    cap = CaptureService(db, paths, bus)
    win = MainWindow(bus, paths, project_service=None, history_service=hist, capture_service=cap)
    win._projects_view._projects = [proj]

    payload = NotificationPayload(
        notif_id="n-ms",
        kind="new_file",
        title="New file in OKR",
        message="01 - Copy.png",
        project_id=proj.id,
        event_id=ev.id,
        rel_path="OKR/01 - Copy.png",
        duration_sec=0,
    )
    try:
        assert isinstance(win._toasts, ToastController)
        win._toasts.show_payload(payload)
        toast = win._active_toasts[-1]
        star_btn = toast.findChild(QPushButton, "toastMilestoneButton")
        assert star_btn is not None
        QTest.mouseClick(star_btn, Qt.MouseButton.LeftButton)
        _flush_qt()

        updated_ev = ObservedEventRepository(db).get(ev.id)
        assert updated_ev is not None and updated_ev.is_milestone is True
        # Idempotent: clicking again must NOT unstar.
        assert hist.set_milestone("observed", ev.id, True) is True
        assert ObservedEventRepository(db).get(ev.id).is_milestone is True  # type: ignore[union-attr]

        dlg = win._capture_dialog
        assert isinstance(dlg, QuickCaptureDialog)
        ms_btn = dlg.findChild(QPushButton, "captureMilestoneButton")
        assert ms_btn is not None and ms_btn.isChecked() is True
        assert dlg._file_input.text() == "OKR/01 - Copy.png"
        dlg.close()

        assert hashlib.sha256(target_file.read_bytes()).hexdigest() == before_hash
    finally:
        win.close()
        win.deleteLater()
        _flush_qt()


def test_branding_themes_soft_light_no_pure_white_and_calendar_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """App icon renders multi-DPI sizes; Soft Light avoids #ffffff; Calendar selection is distinct."""
    _ensure_qapp(monkeypatch)
    icon = app_icon.build_app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()
    assert not icon.pixmap(64, 64).isNull()

    for val in asdict(LIGHT_PALETTE).values():
        if isinstance(val, str):
            assert "#ffffff" not in val.lower()

    light_qss = build_stylesheet("light")
    assert LIGHT_PALETTE.bg in light_qss
    assert "#ffffff" not in light_qss.lower()

    # Selected calendar day paints distinct background from unselected day in both themes.
    for mode in ("dark", "light"):
        set_active_theme(mode)
        sel_btn = CalendarDayButton()
        sel_btn.resize(44, 40)
        sel_btn.set_cell(25, in_month=True, is_today=True, is_selected=True, markers=DayMarkers(True, True, False))
        unsel_btn = CalendarDayButton()
        unsel_btn.resize(44, 40)
        unsel_btn.set_cell(24, in_month=True, is_today=False, is_selected=False, markers=DayMarkers())

        pm_sel, pm_unsel = sel_btn.grab(), unsel_btn.grab()
        assert pm_sel.toImage().pixelColor(6, 6) != pm_unsel.toImage().pixelColor(6, 6)
        sel_btn.close()
        unsel_btn.close()

    set_active_theme("dark")
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    settings = AppSettings()
    player = sound_effects.SoundEffectsPlayer(paths.sounds_cache_dir, settings)
    view = SettingsView(paths, settings=settings, sound_player=player)
    try:
        combo = view.findChild(QComboBox, "themeModeCombo")
        slider = view.findChild(QSlider, "soundVolumeSlider")
        mute_btn = view.findChild(QPushButton, "soundMuteButton")
        val_lbl = view.findChild(QLabel, "soundVolumeValueLabel")
        assert all(w is not None for w in (combo, slider, mute_btn, val_lbl, view.findChild(QCheckBox, "enableSoundsCheckBox")))
        slider.setValue(35)  # type: ignore[union-attr]
        assert val_lbl.text() == "35%"  # type: ignore[union-attr]
        mute_btn.click()  # type: ignore[union-attr]
        combo.setCurrentIndex(combo.findData("light"))  # type: ignore[union-attr]
        reloaded = load_settings(paths)
        assert reloaded.sound_volume == 35
        assert reloaded.sound_muted is True
        assert reloaded.theme_mode == "light"
    finally:
        set_active_theme("dark")
        view.close()


def test_zip_limits_reject_oversized_archive_and_deferred_video_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """validate_zip_members rejects oversized archives and VideoPlayerPanel defers setSource."""
    _ensure_qapp(monkeypatch)

    zpath = tmp_path / "big.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("a.txt", b"hello world")
    with zipfile.ZipFile(zpath, "r") as zf:
        with pytest.raises(ValueError, match="exceeds"):
            archive_safety.validate_zip_members(zf, max_member_bytes=4)
        with pytest.raises(ValueError, match="exceeds"):
            archive_safety.validate_zip_members(zf, max_total_bytes=4)

    # Custom cover round-trips inside .wmem bundle.
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    ws_dir = tmp_path / "WS"
    p_dir = ws_dir / "Proj"
    p_dir.mkdir(parents=True)
    ws = WorkspaceRepository(db).create(Workspace(name="WS", root_path=str(ws_dir)))
    cover_name = "custom_cover.png"
    img = QImage(32, 32, QImage.Format.Format_ARGB32)
    img.fill(QColor("#335577"))
    img.save(str(paths.covers_dir / cover_name), "PNG")
    proj = ProjectRepository(db).create(
        Project(workspace_id=ws.id, name="Proj", rel_path="Proj", abs_path=str(p_dir), cover_image_path=cover_name)
    )
    bundle = tmp_path / "proj.wmem"
    ManifestService(db, paths).export_project_bundle(proj.id, bundle)
    with zipfile.ZipFile(bundle, "r") as zf:
        assert f"covers/{cover_name}" in zf.namelist()

    # VideoPlayerPanel leaves player.source() empty until Play is clicked.
    panel = VideoPlayerPanel()
    poster = QImage(64, 64, QImage.Format.Format_RGB32)
    poster.fill(QColor("#224466"))
    fake_vid = tmp_path / "clip.mp4"
    fake_vid.write_bytes(b"MP4")
    panel.load_video(fake_vid, fallback_image=poster)
    assert panel.player.source().isEmpty() is True
    panel.release_media()
    panel.close()
    panel.deleteLater()
    _flush_qt()
