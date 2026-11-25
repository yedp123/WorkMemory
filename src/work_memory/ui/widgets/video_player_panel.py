"""Embedded dark video player panel with guaranteed Windows file-handle release."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from work_memory.ui.theme import ACCENT, BG, BORDER, MUTED, PANEL, PANEL_ALT, SOFT, TEXT


def _fmt_ms(ms: int) -> str:
    sec = max(0, ms // 1000)
    return f"{sec // 60:02d}:{sec % 60:02d}"


class VideoPlayerPanel(QWidget):
    """Compact dark video playback widget with codec-error still-frame fallback."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_path: Path | None = None
        self._fallback_image: QImage | None = None
        self._duration_ms = 0
        self._seeking = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._stack = QStackedWidget()
        self._video_widget = QVideoWidget()
        self._video_widget.setStyleSheet(f"background-color: {BG};")
        self._stack.addWidget(self._video_widget)

        fallback_box = QWidget()
        fb_lay = QVBoxLayout(fallback_box)
        fb_lay.setContentsMargins(12, 12, 12, 12)
        fb_lay.setSpacing(8)
        self._fallback_img_lbl = QLabel()
        self._fallback_img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback_note = QLabel(
            "Playback unavailable for this codec \u2014 use 'Open in default app'."
        )
        self._fallback_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback_note.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        fb_lay.addWidget(self._fallback_img_lbl, 1)
        fb_lay.addWidget(self._fallback_note, 0)
        self._stack.addWidget(fallback_box)
        layout.addWidget(self._stack, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)

        self._play_btn = QPushButton("Play")
        self._play_btn.setObjectName("videoPlayButton")
        self._play_btn.setProperty("secondary", True)
        self._play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.clicked.connect(self._toggle_play)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("videoSeekSlider")
        self._slider.setRange(0, 0)
        self._slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0; "
            f"background: {TEXT}; border-radius: 6px; }}"
        )
        self._slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self._slider.sliderReleased.connect(self._on_seek_released)

        self._time_lbl = QLabel("00:00 / 00:00")
        self._time_lbl.setObjectName("videoTimeLabel")
        self._time_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")

        self._mute_btn = QPushButton("Mute")
        self._mute_btn.setObjectName("videoMuteButton")
        self._mute_btn.setProperty("secondary", True)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.toggled.connect(self._on_mute_toggled)

        controls.addWidget(self._play_btn)
        controls.addWidget(self._slider, 1)
        controls.addWidget(self._time_lbl)
        controls.addWidget(self._mute_btn)
        layout.addLayout(controls)

        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video_widget)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.errorOccurred.connect(self._on_error)

    @property
    def player(self) -> QMediaPlayer:
        """Expose underlying ``QMediaPlayer`` for handle-release verification."""
        return self._player

    def load_video(self, abs_path: Path, fallback_image: QImage | None = None) -> None:
        """Store ``abs_path`` and show poster preview without locking the file until Play."""
        self.release_media()
        self._current_path = abs_path
        self._fallback_image = fallback_image
        self._duration_ms = 0
        self._slider.setRange(0, 0)
        self._time_lbl.setText("00:00 / 00:00")
        if fallback_image is not None and not fallback_image.isNull():
            pm = QPixmap.fromImage(fallback_image).scaled(
                680, 380, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._fallback_img_lbl.setPixmap(pm)
            self._fallback_note.setText("Click Play to start video playback")
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)

    def release_media(self) -> None:
        """Stop playback and clear source so Windows releases the file lock immediately."""
        self._player.stop()
        self._player.setSource(QUrl())
        self._play_btn.setText("Play")

    def _toggle_play(self) -> None:
        if self._current_path is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            return
        if self._player.source().isEmpty():
            self._player.setSource(QUrl.fromLocalFile(str(self._current_path)))
        self._stack.setCurrentIndex(0)
        self._player.play()

    def _on_seek_released(self) -> None:
        self._seeking = False
        self._player.setPosition(self._slider.value())

    def _on_mute_toggled(self, muted: bool) -> None:
        self._audio.setMuted(muted)
        self._mute_btn.setText("Unmute" if muted else "Mute")

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self._play_btn.setText(
            "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play"
        )

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.release_media()

    def _on_duration_changed(self, duration: int) -> None:
        self._duration_ms = max(0, duration)
        self._slider.setRange(0, self._duration_ms)
        self._time_lbl.setText(f"00:00 / {_fmt_ms(self._duration_ms)}")

    def _on_position_changed(self, pos: int) -> None:
        if not self._seeking:
            self._slider.setValue(pos)
        self._time_lbl.setText(f"{_fmt_ms(pos)} / {_fmt_ms(self._duration_ms)}")

    def _on_error(self, _error: object, _msg: str = "") -> None:
        self.release_media()
        self._fallback_note.setText(
            "Playback unavailable for this codec \u2014 use 'Open in default app'."
        )
        if self._fallback_image is not None and not self._fallback_image.isNull():
            pm = QPixmap.fromImage(self._fallback_image).scaled(
                680, 380, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._fallback_img_lbl.setPixmap(pm)
        else:
            self._fallback_img_lbl.setText("Preview unavailable")
            self._fallback_img_lbl.setStyleSheet(f"color: {SOFT}; font-size: 13px;")
        self._stack.setCurrentIndex(1)
        _ = PANEL, PANEL_ALT
