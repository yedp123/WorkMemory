"""Calm dark progressive-disclosure VoiceDrawer for recording, preview, and transcription."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.media.audio_recorder import AudioRecorder
from work_memory.media.transcriber import AudioTranscriber
from work_memory.services.capture_service import CaptureService
from work_memory.ui.theme import ACCENT, BG, BORDER, MUTED, PANEL_ALT, SOFT, TEXT

logger = logging.getLogger(__name__)

_READY_STATUS = "Ready \u2014 mic opens only while recording"


class VoiceDrawer(QFrame):
    """Expandable voice note sub-drawer with streaming WAV capture and offline Whisper."""

    changed = Signal()
    transcribing_changed = Signal(bool)
    recording_changed = Signal(bool)

    def __init__(self, capture_service: CaptureService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = capture_service
        self._recorder = AudioRecorder()
        self._transcriber = AudioTranscriber(self)
        self._wav_path: Path | None = None
        self._elapsed_sec = 0

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

        self._transcriber.transcription_finished.connect(self._on_transcription_finished)
        self._transcriber.transcription_failed.connect(self._on_transcription_failed)
        self._transcriber.transcribing_changed.connect(self.transcribing_changed)

        self.setObjectName("voiceDrawer")
        self.setStyleSheet(
            "QFrame#voiceDrawer { background-color: #17191d; border: 1px solid #30353d; "
            "border-radius: 10px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._record_btn = QPushButton("Start recording")
        self._record_btn.setObjectName("voiceRecordButton")
        self._record_btn.setProperty("secondary", True)
        self._record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._record_btn.clicked.connect(self._toggle_recording)

        self._play_btn = QPushButton("\u25b6 Play")
        self._play_btn.setObjectName("voicePlayButton")
        self._play_btn.setProperty("secondary", True)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._toggle_playback)

        self._discard_btn = QPushButton("Discard audio")
        self._discard_btn.setObjectName("voiceDiscardButton")
        self._discard_btn.setProperty("secondary", True)
        self._discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._discard_btn.setEnabled(False)
        self._discard_btn.clicked.connect(self._on_discard_audio)

        self._elapsed_lbl = QLabel("0:00")
        self._elapsed_lbl.setStyleSheet(f"color: {SOFT}; font-size: 12px; border: none;")

        top.addWidget(self._record_btn)
        top.addWidget(self._elapsed_lbl)
        top.addStretch(1)
        top.addWidget(self._play_btn)
        top.addWidget(self._discard_btn)
        root.addLayout(top)

        self._status_lbl = QLabel(_READY_STATUS)
        self._status_lbl.setObjectName("voiceStatusLabel")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; border: none;")
        root.addWidget(self._status_lbl)

        self._transcript_edit = QPlainTextEdit()
        self._transcript_edit.setObjectName("voiceTranscriptEdit")
        self._transcript_edit.setPlaceholderText("Offline transcription appears here for review and editing...")
        self._transcript_edit.setMinimumHeight(68)
        self._transcript_edit.setMaximumHeight(110)
        self._transcript_edit.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {BG}; color: {TEXT}; border: 1px solid {BORDER}; "
            "border-radius: 8px; padding: 6px 10px; font-size: 12px; }}"
        )
        root.addWidget(self._transcript_edit)

        ret_row = QHBoxLayout()
        ret_row.setSpacing(12)
        self._ret_group = QButtonGroup(self)
        self._rb_both = QRadioButton("Keep audio && text")
        self._rb_text = QRadioButton("Transcription only")
        self._rb_audio = QRadioButton("Audio only")
        self._rb_both.setChecked(True)
        for rb, mode in ((self._rb_both, "both"), (self._rb_text, "text"), (self._rb_audio, "audio")):
            rb.setProperty("retentionMode", mode)
            rb.setStyleSheet(f"color: {SOFT}; font-size: 11px;")
            self._ret_group.addButton(rb)
            ret_row.addWidget(rb)
        ret_row.addStretch(1)
        root.addLayout(ret_row)

    @property
    def is_transcribing(self) -> bool:
        """Return ``True`` while offline transcription is running."""
        return self._transcriber.is_transcribing

    @property
    def is_recording(self) -> bool:
        """Return ``True`` while microphone recording is active."""
        return self._recorder.is_recording

    def audio_wav_path(self) -> Path | None:
        """Return the active recorded WAV path if it exists on disk."""
        return self._wav_path if self._wav_path is not None and self._wav_path.is_file() else None

    def transcription_text(self) -> str:
        """Return the current edited transcription text."""
        return self._transcript_edit.toPlainText().strip()

    def audio_retention(self) -> str:
        """Return the selected retention mode: ``both``, ``text``, or ``audio``."""
        if self._rb_text.isChecked():
            return "text"
        if self._rb_audio.isChecked():
            return "audio"
        return "both"

    def restore_state(self, audio_path: str | None, transcript: str, retention: str) -> None:
        """Restore draft audio path, edited transcript, and retention mode."""
        self._transcript_edit.setPlainText(transcript or "")
        if retention == "text":
            self._rb_text.setChecked(True)
        elif retention == "audio":
            self._rb_audio.setChecked(True)
        else:
            self._rb_both.setChecked(True)

        p = Path(audio_path) if audio_path else None
        if p is not None and p.is_file():
            self._wav_path = p
            self._play_btn.setEnabled(True)
            self._discard_btn.setEnabled(True)
            self._status_lbl.setText("Recovered draft voice recording.")
        else:
            self._wav_path = None
            self._play_btn.setEnabled(False)
            self._discard_btn.setEnabled(False)

    def clear(self) -> None:
        """Stop any active recording/playback and reset all voice controls."""
        self.shutdown()
        self._wav_path = None
        self._transcript_edit.clear()
        self._rb_both.setChecked(True)
        self._elapsed_sec = 0
        self._elapsed_lbl.setText("0:00")
        self._play_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status_lbl.setText(_READY_STATUS)

    def shutdown(self) -> None:
        """Ensure microphone stream and media player are stopped cleanly."""
        self._tick_timer.stop()
        if self._recorder.is_recording:
            self._recorder.stop()
            self._record_btn.setText("Start recording")
            self.recording_changed.emit(False)
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
        self._player.setSource(QUrl())

    def _toggle_recording(self) -> None:
        if self._recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
        self._player.setSource(QUrl())
        target = self._service.allocate_draft_audio_path()
        err = self._recorder.start(target)
        if err is not None:
            self._status_lbl.setText(err)
            self._status_lbl.setStyleSheet("color: #e58f8f; font-size: 11px; border: none;")
            return
        self._wav_path = target
        self._elapsed_sec = 0
        self._elapsed_lbl.setText("0:00")
        self._tick_timer.start()
        self._record_btn.setText("Stop (0s)")
        self._record_btn.setStyleSheet(
            f"background-color: {PANEL_ALT}; color: #e58f8f; border: 1px solid #a15252; "
            "border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600;"
        )
        self._play_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 11px; border: none;")
        self._status_lbl.setText("Recording...")
        self.recording_changed.emit(True)

    def _stop_recording(self) -> None:
        self._tick_timer.stop()
        wav_path = self._recorder.stop()
        self.recording_changed.emit(False)
        self._record_btn.setText("Start recording")
        self._record_btn.setStyleSheet("")
        self._record_btn.setProperty("secondary", True)
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)

        if wav_path is None or not wav_path.is_file():
            self._status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; border: none;")
            self._status_lbl.setText(_READY_STATUS)
            return

        self._wav_path = wav_path
        self._play_btn.setEnabled(True)
        self._discard_btn.setEnabled(True)
        self._status_lbl.setStyleSheet(f"color: {SOFT}; font-size: 11px; border: none;")
        self._status_lbl.setText("Transcribing offline...")
        self._transcriber.transcribe(wav_path, self._service.models_dir)

    def _on_tick(self) -> None:
        self._elapsed_sec += 1
        mins, secs = divmod(self._elapsed_sec, 60)
        self._elapsed_lbl.setText(f"{mins}:{secs:02d}")
        self._record_btn.setText(f"Stop ({self._elapsed_sec}s)")

    def _on_transcription_finished(self, text: str) -> None:
        if text:
            existing = self._transcript_edit.toPlainText().strip()
            self._transcript_edit.setPlainText(f"{existing}\n{text}".strip() if existing else text)
            self._status_lbl.setStyleSheet(f"color: {SOFT}; font-size: 11px; border: none;")
            self._status_lbl.setText("Transcription ready for review")
        else:
            self._status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; border: none;")
            self._status_lbl.setText("No speech detected. You can still save the audio or type a note.")

    def _on_transcription_failed(self, err: str) -> None:
        self._status_lbl.setStyleSheet("color: #d8b57c; font-size: 11px; border: none;")
        self._status_lbl.setText(err)

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
            return
        if (wav := self.audio_wav_path()) is None:
            return
        self._player.setSource(QUrl.fromLocalFile(str(wav)))
        self._player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setText("\u25a0 Stop" if playing else "\u25b6 Play")
        if state == QMediaPlayer.PlaybackState.StoppedState and not self._player.source().isEmpty():
            # Release Windows OS read handle immediately after preview playback stops.
            self._player.setSource(QUrl())

    def _on_discard_audio(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
        self._player.setSource(QUrl())
        if self._wav_path is not None and self._wav_path.is_file():
            try:
                self._wav_path.unlink()
            except OSError as exc:
                logger.warning("Failed to delete discarded draft audio %s: %s", self._wav_path, exc)
        self._wav_path = None
        self._play_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._elapsed_sec = 0
        self._elapsed_lbl.setText("0:00")
        self._status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; border: none;")
        self._status_lbl.setText(_READY_STATUS)
