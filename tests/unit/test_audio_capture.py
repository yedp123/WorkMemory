"""Unit tests for Phase 6: Audio Recording, Offline Transcription, and Retention Modes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import types
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PySide6.QtWidgets import QApplication, QPushButton, QRadioButton

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import Project, Workspace
from work_memory.media.audio_recorder import AudioRecorder
from work_memory.media.transcribe_worker import (
    load_wav_as_float32,
    resolve_local_model_dir,
    transcribe_wav,
)
from work_memory.media.transcriber import run_transcription_subprocess
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.notification_service import NotificationPayload
from work_memory.storage.attachments import AttachmentStorage
from work_memory.storage.database import Database
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.ui.capture.quick_capture_dialog import QuickCaptureDialog
from work_memory.ui.capture.toast_popup import ToastPopup
from work_memory.ui.widgets.milestone_preview_dialog import MilestonePreviewDialog
from work_memory.ui.widgets.timeline_widget import TimelineWidget


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _make_wav(path: Path, frames: int = 1600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * frames)
    return path


def _setup_env(tmp_path: Path) -> tuple[Database, CaptureService, HistoryService, Project]:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Studio", root_path=str(tmp_path / "studio")))
    proj = ProjectRepository(db).create(Project(workspace_id=ws.id, name="Rig", rel_path="Rig"))
    bus = EventBus()
    cap_svc = CaptureService(db, paths, bus)
    hist_svc = HistoryService(db, bus, app_paths=paths)
    return db, cap_svc, hist_svc, proj


def test_audio_retention_modes_and_fts_search(tmp_path: Path) -> None:
    _db, cap_svc, hist_svc, proj = _setup_env(tmp_path)

    # 1. "both" retains WAV in attachments/ AND stores transcription in DB + FTS5
    wav_both = _make_wav(cap_svc.allocate_draft_audio_path())
    entry_both, atts_both = cap_svc.create_capture(
        project_id=proj.id,
        note_text="Rigging check",
        audio_wav_path=wav_both,
        transcription="Adjusted clavicle IK pole vector",
        audio_retention="both",
    )
    assert entry_both.audio_retention == "both"
    assert entry_both.transcription == "Adjusted clavicle IK pole vector"
    assert len(atts_both) == 1
    assert atts_both[0].kind == "audio"
    assert (cap_svc.attachments_dir / atts_both[0].stored_rel_path).is_file()

    # FTS5 search finds the capture by spoken transcription text
    res = hist_svc.search("clavicle")
    assert any(c.id == entry_both.id for c in res.captures)

    # 2. "text" stores transcription and cleans up draft WAV without keeping audio attachment
    wav_text = _make_wav(cap_svc.allocate_draft_audio_path())
    assert wav_text.is_file()
    entry_text, atts_text = cap_svc.create_capture(
        project_id=proj.id,
        audio_wav_path=wav_text,
        transcription="Baked normal map at 4k",
        audio_retention="text",
    )
    assert entry_text.audio_retention == "text"
    assert entry_text.transcription == "Baked normal map at 4k"
    assert atts_text == []
    assert not wav_text.is_file()
    assert any(c.id == entry_text.id for c in hist_svc.search("normal map").captures)

    # 3. "audio" retains WAV in attachments/ and stores transcription=None
    wav_audio = _make_wav(cap_svc.allocate_draft_audio_path())
    entry_audio, atts_audio = cap_svc.create_capture(
        project_id=proj.id,
        audio_wav_path=wav_audio,
        transcription="Should not be persisted",
        audio_retention="audio",
    )
    assert entry_audio.audio_retention == "audio"
    assert entry_audio.transcription is None
    assert entry_audio.transcript_text == ""
    assert len(atts_audio) == 1
    assert atts_audio[0].kind == "audio"
    assert (cap_svc.attachments_dir / atts_audio[0].stored_rel_path).is_file()


def test_save_audio_file_blocks_monitored_workspace(tmp_path: Path) -> None:
    ws_dir = tmp_path / "monitored"
    ws_dir.mkdir()
    wav = _make_wav(tmp_path / "temp.wav")
    storage = AttachmentStorage(ws_dir / "attachments", workspace_roots_provider=lambda: [ws_dir])
    try:
        storage.save_audio_file(wav)
        raise AssertionError("Expected PermissionError for write inside monitored workspace")
    except PermissionError:
        pass


def test_draft_recovery_preserves_audio_and_transcript(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, cap_svc, _hist_svc, proj = _setup_env(tmp_path)
    draft_wav = _make_wav(cap_svc.allocate_draft_audio_path())

    cap_svc.save_draft(
        project_id=proj.id,
        note_text="WIP note",
        draft_audio_path=draft_wav,
        draft_transcript="Pending voice transcript",
        audio_retention="text",
    )
    loaded = cap_svc.load_draft()
    assert loaded is not None
    assert loaded.draft_audio_path == str(draft_wav)
    assert loaded.draft_transcript == "Pending voice transcript"
    assert loaded.audio_retention == "text"

    dlg = QuickCaptureDialog(cap_svc, [proj])
    dlg.show()
    assert dlg._voice_drawer.isVisible()
    assert dlg._voice_drawer.audio_wav_path() == draft_wav.resolve()
    assert dlg._voice_drawer.transcription_text() == "Pending voice transcript"
    assert dlg._voice_drawer.audio_retention() == "text"
    dlg.close()


def test_audio_recorder_missing_mic_and_transcriber_subprocess_mocked(tmp_path: Path) -> None:
    recorder = AudioRecorder()
    wav_path = tmp_path / "drafts" / "mic_fail.wav"
    with patch("sounddevice.InputStream", side_effect=OSError("No default input device")):
        err = recorder.start(wav_path)
    assert err is not None
    assert "microphone" in err.lower()
    assert not recorder.is_recording

    ok_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"ok": True, "text": "Hello world"}), stderr=""
    )
    with patch("work_memory.media.transcriber.subprocess.run", return_value=ok_proc):
        ok, text = run_transcription_subprocess(wav_path, tmp_path / "models")
    assert ok is True
    assert text == "Hello world"

    fail_proc = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout=json.dumps({"ok": False, "error": "Offline connection error"}),
        stderr="",
    )
    with patch("work_memory.media.transcriber.subprocess.run", return_value=fail_proc):
        ok, err_msg = run_transcription_subprocess(wav_path, tmp_path / "models")
    assert ok is False
    assert "save your audio recording" in err_msg.lower()


def test_toast_voice_button_and_timeline_milestone_audio_ui(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, cap_svc, hist_svc, proj = _setup_env(tmp_path)

    payload = NotificationPayload(
        notif_id="n1",
        kind="new_file",
        title="New file",
        message="rig.blend",
        project_id=proj.id,
        rel_path="Rig/rig.blend",
        event_id=None,
        duration_sec=5,
    )
    toast = ToastPopup(payload)
    voice_clicks: list[NotificationPayload] = []
    toast.voice_requested.connect(voice_clicks.append)
    voice_btn = toast.findChild(QPushButton, "toastVoiceButton")
    assert voice_btn is not None
    voice_btn.click()
    assert len(voice_clicks) == 1

    wav = _make_wav(cap_svc.allocate_draft_audio_path())
    entry, _atts = cap_svc.create_capture(
        project_id=proj.id,
        note_text="Finalized face shapes",
        audio_wav_path=wav,
        transcription="Check brow blendshapes",
        audio_retention="both",
        is_milestone=True,
    )
    timeline = hist_svc.get_recent_timeline(proj.id)
    widget = TimelineWidget()
    widget.set_timeline(timeline)
    assert widget.findChild(QPushButton, "audioPlayButton") is not None

    detail = hist_svc.get_milestone_detail("capture", entry.id)
    assert detail is not None
    assert detail.transcription == "Check brow blendshapes"
    preview = MilestonePreviewDialog(detail)
    assert preview.findChild(QPushButton, "audioPlayButton") is not None
    preview.close()
    widget.close()
    toast.close()


def test_quick_capture_retention_radio_buttons(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, cap_svc, _hist_svc, proj = _setup_env(tmp_path)
    dlg = QuickCaptureDialog(cap_svc, [proj])
    dlg.show()
    assert not dlg._voice_drawer.isVisible()
    toggle_btn = dlg.findChild(QPushButton, "toggleVoiceButton")
    assert toggle_btn is not None
    toggle_btn.click()
    assert dlg._voice_drawer.isVisible()

    radios = dlg._voice_drawer.findChildren(QRadioButton)
    assert len(radios) == 3
    assert dlg._voice_drawer.audio_retention() == "both"
    radios[1].setChecked(True)
    assert dlg._voice_drawer.audio_retention() == "text"
    radios[2].setChecked(True)
    assert dlg._voice_drawer.audio_retention() == "audio"
    dlg.close()


def test_load_wav_as_float32_decodes_without_pyav(tmp_path: Path) -> None:
    wav = _make_wav(tmp_path / "sample.wav", frames=3200)
    samples = load_wav_as_float32(wav)
    assert samples.ndim == 1
    assert samples.size == 3200
    assert str(samples.dtype) == "float32"


def test_offline_snapshot_resolution_with_incomplete_blob_and_missing_model(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    blobs_dir = models_dir / "models--Systran--faster-whisper-base" / "blobs"
    snap_dir = models_dir / "models--Systran--faster-whisper-base" / "snapshots" / "rev123"
    blobs_dir.mkdir(parents=True)
    snap_dir.mkdir(parents=True)
    (blobs_dir / "deadbeef.incomplete").write_bytes(b"")
    for fname in ("model.bin", "config.json", "vocabulary.txt"):
        (snap_dir / fname).write_bytes(b"ok")

    assert resolve_local_model_dir(models_dir) == snap_dir

    wav = _make_wav(tmp_path / "speech.wav", frames=1600)
    fake_seg = MagicMock(text="  Offline test  ")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_seg], MagicMock())
    fake_cls = MagicMock(return_value=fake_model)
    fake_fw = types.SimpleNamespace(WhisperModel=fake_cls)

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        res = transcribe_wav(wav, models_dir)

    assert res == {"ok": True, "text": "Offline test"}
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("HF_HUB_DISABLE_TELEMETRY") == "1"
    fake_cls.assert_called_once_with(
        str(snap_dir), device="cpu", compute_type="int8", local_files_only=True
    )

    empty_models = tmp_path / "empty_models"
    empty_models.mkdir()
    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        missing_res = transcribe_wav(wav, empty_models)
    assert missing_res["ok"] is False
    assert "not found" in str(missing_res["error"]).lower()


def test_load_wav_removes_dc_offset_and_normalizes_quiet_speech(tmp_path: Path) -> None:
    wav = tmp_path / "quiet_dc.wav"
    t = np.linspace(0.0, 0.2, num=3200, endpoint=False)
    pcm = (250 + 1000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm.tobytes())

    samples = load_wav_as_float32(wav)
    assert abs(float(np.mean(samples))) < 1e-4
    peak = float(np.max(np.abs(samples)))
    assert 0.65 <= peak <= 0.86


def test_save_button_disabled_while_transcribing_and_reenabled_after(tmp_path: Path) -> None:
    _ensure_qapp()
    _db, cap_svc, _hist_svc, proj = _setup_env(tmp_path)
    dlg = QuickCaptureDialog(cap_svc, [proj])
    drawer = dlg._voice_drawer
    save_btn = dlg._save_btn
    assert save_btn.isEnabled()

    drawer._transcriber._active_signals.add(MagicMock())
    drawer.transcribing_changed.emit(True)
    assert not save_btn.isEnabled()
    assert save_btn.text() == "Transcribing..."

    drawer._transcriber._active_signals.clear()
    drawer.transcribing_changed.emit(False)
    assert save_btn.isEnabled()
    assert save_btn.text() == "Save entry"

    drawer._transcriber._active_signals.add(MagicMock())
    drawer.transcribing_changed.emit(True)
    assert not save_btn.isEnabled()

    drawer._transcriber._active_signals.clear()
    drawer._on_transcription_failed("Offline model missing")
    drawer.transcribing_changed.emit(False)
    assert save_btn.isEnabled()
    dlg.close()


def test_ui_stylesheets_have_no_fractional_px_values() -> None:
    pat = re.compile(r"\d+\.\d+px")
    ui_root = Path(__file__).resolve().parents[2] / "src" / "work_memory" / "ui"
    offenders: list[str] = []
    for py_file in sorted(ui_root.rglob("*.py")):
        for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), start=1):
            if pat.search(line):
                offenders.append(f"{py_file.name}:{lineno}: {line.strip()}")
    assert offenders == []
