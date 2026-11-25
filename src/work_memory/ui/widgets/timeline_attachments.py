"""Thumbnail and audio playback widgets shared by timeline rows and MilestonePreviewDialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from work_memory.core.models import Attachment
from work_memory.ui.theme import BORDER, PANEL_ALT, SOFT, TEXT


def build_audio_play_button(audio_path: Path, parent: QLabel | None = None) -> QPushButton:
    """Create a compact ``▶ Play audio`` / ``■ Stop`` button backed by QMediaPlayer."""
    btn = QPushButton("\u25b6 Play audio", parent)
    btn.setObjectName("audioPlayButton")
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background-color: {PANEL_ALT}; color: {SOFT}; border: 1px solid {BORDER}; "
        "border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: 600; }}"
        f"QPushButton:hover {{ border-color: #535d6e; color: {TEXT}; }}"
    )
    player = QMediaPlayer(btn)
    audio_out = QAudioOutput(btn)
    player.setAudioOutput(audio_out)

    def _toggle() -> None:
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.stop()
        else:
            player.setSource(QUrl.fromLocalFile(str(audio_path)))
            player.play()

    def _on_state(state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        btn.setText("\u25a0 Stop" if playing else "\u25b6 Play audio")
        if state == QMediaPlayer.PlaybackState.StoppedState:
            player.setSource(QUrl())

    def _on_media_status(status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            player.stop()
            player.setSource(QUrl())

    btn.clicked.connect(_toggle)
    player.playbackStateChanged.connect(_on_state)
    player.mediaStatusChanged.connect(_on_media_status)
    return btn


def append_thumbnails(
    col: QVBoxLayout, attachments: tuple[Attachment, ...], attachments_dir: str
) -> None:
    """Append aspect-preserved screenshot/image thumbnails for a capture row."""
    superseded_orig_ids = {
        a.original_attachment_id
        for a in attachments
        if a.kind == "annotated_screenshot" and a.original_attachment_id
    }
    has_unlinked_ann = any(
        a.kind == "annotated_screenshot" and not a.original_attachment_id for a in attachments
    )
    shown = [
        a
        for a in attachments
        if a.kind in ("annotated_screenshot", "image", "screenshot")
        and not (
            a.kind == "screenshot"
            and (a.id in superseded_orig_ids or (has_unlinked_ann and not superseded_orig_ids))
        )
    ]
    if not shown:
        return
    thumbs = QHBoxLayout()
    thumbs.setContentsMargins(0, 6, 0, 0)
    thumbs.setSpacing(8)
    base = Path(attachments_dir)
    for att in shown[:3]:
        img_path = base / att.stored_rel_path
        if not img_path.is_file():
            continue
        pm = QPixmap(str(img_path))
        if pm.isNull():
            continue
        thumb = QLabel()
        thumb.setPixmap(
            pm.scaled(
                220, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )
        thumb.setStyleSheet(f"border: 1px solid {BORDER}; border-radius: 6px; padding: 1px;")
        thumbs.addWidget(thumb)
    thumbs.addStretch(1)
    col.addLayout(thumbs)


def append_audio_buttons(
    col: QVBoxLayout, attachments: tuple[Attachment, ...], attachments_dir: str
) -> None:
    """Append ``▶ Play audio`` buttons for audio attachments present on disk."""
    base = Path(attachments_dir)
    audio_paths = [
        base / a.stored_rel_path
        for a in attachments
        if a.kind == "audio" and (base / a.stored_rel_path).is_file()
    ]
    if not audio_paths:
        return
    row = QHBoxLayout()
    row.setContentsMargins(0, 4, 0, 0)
    row.setSpacing(6)
    for path in audio_paths:
        row.addWidget(build_audio_play_button(path))
    row.addStretch(1)
    col.addLayout(row)
