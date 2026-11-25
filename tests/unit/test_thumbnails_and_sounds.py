"""Unit and UI tests for Polish Pass B: media thumbnails, 3D/video preview, and UI sounds."""

from __future__ import annotations

import hashlib
import struct
import zipfile
from datetime import date
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QThreadPool
from PySide6.QtGui import QColor, QDesktopServices, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from work_memory.config.paths import resolve_app_paths
from work_memory.config.settings import AppSettings, load_settings
from work_memory.core.models import DayTimeline, ObservedEvent, ObservedGroup
from work_memory.media import sound_effects
from work_memory.media.thumbnail_service import ThumbnailService, get_media_kind
from work_memory.ui.views.settings_view import SettingsView
from work_memory.ui.widgets.media_preview_dialog import MediaPreviewDialog
from work_memory.ui.widgets.timeline_widget import TimelineWidget


def _ensure_qapp(monkeypatch: pytest.MonkeyPatch) -> QApplication:
    if QApplication.instance() is None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _png_bytes(width: int, height: int, color: str) -> bytes:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    buf = QByteArray()
    qbuf = QBuffer(buf)
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(qbuf, "PNG")
    qbuf.close()
    return bytes(buf.data())


def _write_binary_stl(path: Path) -> None:
    header = b"binary stl test".ljust(80, b"\x00")
    tri = struct.pack(
        "<12fH",
        0.0, 0.0, 1.0,
        0.0, 0.0, 0.0,
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.5,
        0,
    )
    path.write_bytes(header + struct.pack("<I", 1) + tri)


def _write_cube_obj(path: Path) -> None:
    path.write_text(
        "v -1 -1 -1\nv 1 -1 -1\nv 1 1 -1\nv -1 1 -1\n"
        "v -1 -1 1\nv 1 -1 1\nv 1 1 1\nv -1 1 1\n"
        "f 1 2 3 4\nf 5 6 7 8\nf 1 2 6 5\n"
        "f 2 3 7 6\nf 3 4 8 7\nf 4 1 5 8\n",
        encoding="utf-8",
    )


def _write_tiny_mp4(path: Path) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=2)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for val in (80, 160):
            arr = np.full((64, 64, 3), val, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for pkt in stream.encode(frame):
                container.mux(pkt)
        for pkt in stream.encode():
            container.mux(pkt)


def test_thumbnails_cache_readonly_and_video_handling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Image, 3MF, OBJ, STL, and MP4 thumbnails cache in app-data without mutating sources."""
    _ensure_qapp(monkeypatch)
    ws_dir = tmp_path / "Workspace"
    ws_dir.mkdir()
    png_file = ws_dir / "render.png"
    png_file.write_bytes(_png_bytes(160, 120, "#3377aa"))

    mf_file = ws_dir / "plate.3mf"
    with zipfile.ZipFile(mf_file, "w") as zf:
        zf.writestr("Metadata/plate_1.png", _png_bytes(120, 120, "#aa6633"))

    obj_file = ws_dir / "cube.obj"
    _write_cube_obj(obj_file)
    stl_file = ws_dir / "tri.stl"
    _write_binary_stl(stl_file)
    mp4_file = ws_dir / "turntable.mp4"
    _write_tiny_mp4(mp4_file)
    corrupt_mp4 = ws_dir / "corrupt.mp4"
    corrupt_mp4.write_bytes(b"not-a-real-video")

    sources = [png_file, mf_file, obj_file, stl_file, mp4_file, corrupt_mp4]
    before = {
        p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sources
    }

    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    svc = ThumbnailService(paths.thumbs_cache_dir, workspace_roots_provider=lambda: [ws_dir])

    assert get_media_kind("shots/a_0001.png .. a_0010.png (10 frames)") == "image"
    for f in (png_file, mf_file, obj_file, stl_file, mp4_file):
        img = svc.generate_thumbnail(f, size_px=76)
        assert img is not None and not img.isNull()

    assert svc.generate_thumbnail(corrupt_mp4, size_px=76) is None
    assert svc.generate_thumbnail(ws_dir / "missing.png", size_px=76) is None
    assert len(list(paths.thumbs_cache_dir.glob("*.png"))) == 5

    after = {
        p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sources
    }
    assert after == before


def test_media_preview_dialog_releases_video_handle_and_timeline_thumb_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MediaPreviewDialog clears QMediaPlayer source on close; timeline badge click stays isolated."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()
    svc = ThumbnailService(paths.thumbs_cache_dir)

    mp4_file = tmp_path / "clip.mp4"
    _write_tiny_mp4(mp4_file)
    obj_file = tmp_path / "mesh.obj"
    _write_cube_obj(obj_file)

    for target in (obj_file, mp4_file):
        dlg = MediaPreviewDialog(target, thumbnail_service=svc)
        dlg.show()
        QThreadPool.globalInstance().waitForDone(2000)
        QApplication.processEvents()
        dlg.close()
        assert dlg.video_panel.player.source().isEmpty()
        dlg.deleteLater()

    renamed_mp4 = tmp_path / "clip_renamed.mp4"
    mp4_file.replace(renamed_mp4)
    assert renamed_mp4.is_file()

    opened: list[object] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u) or True)
    tl = TimelineWidget(thumbnail_service=svc)
    ev = ObservedEvent("ws", "mesh.obj", "modified", "2026-11-25T10:00:00Z", project_id="p1")
    grp = ObservedGroup("p1", "Proj", "2026-11-25T10:00:00Z", "2026-11-25", "10:00", (ev,))
    tl.set_timeline(DayTimeline(local_date=date(2026, 11, 25), observed_groups=(grp,)))
    tl.show()
    try:
        previewed: list[tuple[str, str, str]] = []
        tl.file_preview_requested.connect(lambda r, p, w: previewed.append((r, p, w)))
        btn = tl.findChild(QPushButton, "timelineThumbnailBadge")
        assert btn is not None
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert previewed == [("mesh.obj", "p1", "ws")]
        assert opened == []
    finally:
        tl.close()


def test_sound_effects_wav_generation_toggle_and_error_resilience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Procedural WAV assets write cleanly, respect enable_sounds, and survive backend errors."""
    _ensure_qapp(monkeypatch)
    paths = resolve_app_paths(tmp_path / "app")
    paths.ensure_directories()

    click_wav, ding_wav = sound_effects.ensure_sound_assets(paths.sounds_cache_dir)
    assert click_wav.is_file() and click_wav.read_bytes().startswith(b"RIFF")
    assert ding_wav.is_file() and ding_wav.read_bytes().startswith(b"RIFF")

    settings = AppSettings(enable_sounds=False)
    player = sound_effects.SoundEffectsPlayer(paths.sounds_cache_dir, settings)
    assert player.play_screenshot_click() is False
    assert player.play_notification_ding() is False

    settings.enable_sounds = True
    monkeypatch.setattr(
        sound_effects.QSoundEffect,
        "play",
        lambda _self: (_ for _ in ()).throw(RuntimeError("No audio device")),
    )
    assert player.play_screenshot_click() is False

    view = SettingsView(paths, settings=settings)
    try:
        cb = view.findChild(QCheckBox, "enableSoundsCheckBox")
        assert cb is not None and cb.isChecked() is True
        cb.setChecked(False)
        assert load_settings(paths).enable_sounds is False
    finally:
        view.close()
