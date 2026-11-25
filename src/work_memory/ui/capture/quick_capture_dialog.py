"""Calm dark Quick Capture dialog with 1:1 on-screen capture and draft recovery."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QHideEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import Project
from work_memory.media.screenshot import grab_virtual_desktop, pixmap_to_png_bytes
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.services.capture_service import CaptureService, ScreenshotData
from work_memory.ui.capture.attachment_list import AttachmentStrip
from work_memory.ui.capture.capture_draft_helpers import (
    apply_capture_dialog_style,
    persist_draft_from_widgets,
    restore_draft_into_widgets,
)
from work_memory.ui.capture.capture_form import build_capture_footer, build_capture_form
from work_memory.ui.capture.capture_overlay import CaptureOverlay
from work_memory.ui.capture.voice_drawer import VoiceDrawer
from work_memory.ui.theme import get_palette

logger = logging.getLogger(__name__)


class QuickCaptureDialog(QDialog):
    """Non-modal Quick Capture dialog supporting notes, images, and 1:1 desktop capture."""

    def __init__(
        self,
        capture_service: CaptureService,
        projects: Sequence[Project],
        *,
        initial_project_id: str | None = None,
        initial_linked_file: str = "",
        initial_milestone: bool = False,
        sound_player: SoundEffectsPlayer | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service, self._projects = capture_service, list(projects)
        self._sound_player = sound_player
        self._saved = self._capturing_screen = self._in_close_event = False
        self._overlay: CaptureOverlay | None = None

        apply_capture_dialog_style(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        w = build_capture_form(
            root,
            self._projects,
            initial_project_id=initial_project_id,
            initial_linked_file=initial_linked_file,
            on_discard_draft=self._on_discard_draft,
            on_attach_image=self._on_attach_image,
            on_take_screenshot=self._on_take_screenshot,
            on_toggle_voice=self._on_toggle_voice,
        )
        self._draft_bar, self._discard_draft_btn = w.draft_bar, w.discard_draft_btn
        self._project_combo, self._file_input, self._note_input = (
            w.project_combo,
            w.file_input,
            w.note_input,
        )
        self._attach_btn, self._shot_btn, self._voice_btn = w.attach_btn, w.shot_btn, w.voice_btn
        self._save_draft_btn, self._save_btn = w.save_draft_btn, w.save_btn
        self._save_draft_btn.clicked.connect(self._on_save_draft_and_close)
        self._save_btn.clicked.connect(self._on_save_entry)

        self._voice_drawer = VoiceDrawer(self._service)
        self._voice_drawer.setVisible(False)
        self._voice_drawer.changed.connect(self.adjustSize)
        self._voice_drawer.transcribing_changed.connect(self._sync_save_button_state)
        self._voice_drawer.recording_changed.connect(self._sync_save_button_state)
        root.addWidget(self._voice_drawer)

        self._attachments = AttachmentStrip()
        self._attachments.changed.connect(self.adjustSize)
        root.addWidget(self._attachments)
        self._milestone_btn = QPushButton("\u2606 Milestone")
        self._milestone_btn.setObjectName("captureMilestoneButton")
        self._milestone_btn.setCheckable(True)
        self._milestone_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._milestone_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._milestone_btn.setToolTip("Star this capture as a project milestone")
        self._milestone_btn.toggled.connect(self._update_milestone_style)
        self._update_milestone_style(False)
        footer = build_capture_footer(self._save_draft_btn, self._save_btn)
        footer.insertWidget(1, self._milestone_btn)
        root.addLayout(footer)

        restore_draft_into_widgets(
            self._service,
            self._project_combo,
            self._file_input,
            self._note_input,
            self._attachments,
            self._draft_bar,
        )
        if (draft := self._service.load_draft()) is not None:
            if draft.is_milestone:
                self._milestone_btn.setChecked(True)
            if draft.draft_audio_path or draft.draft_transcript.strip():
                self._voice_drawer.restore_state(
                    draft.draft_audio_path, draft.draft_transcript, draft.audio_retention
                )
                self.open_voice_drawer()
        if initial_milestone:
            self._milestone_btn.setChecked(True)

    @property
    def is_capturing_screen(self) -> bool:
        """Return ``True`` while hidden for an active screenshot capture."""
        return self._capturing_screen

    def set_project_id(self, project_id: str | None) -> None:
        """Select ``project_id`` in the project dropdown when present."""
        if project_id and (idx := self._project_combo.findData(project_id)) >= 0:
            self._project_combo.setCurrentIndex(idx)

    def set_milestone_checked(self, checked: bool) -> None:
        """Programmatically set the milestone star button state."""
        self._milestone_btn.setChecked(checked)

    def force_close_on_shutdown(self) -> None:
        """Close cleanly during application shutdown even if a screen capture was pending."""
        self._capturing_screen = False
        self._voice_drawer.shutdown()
        if self._overlay is not None:
            self._overlay.reject()
            self._overlay.deleteLater()
            self._overlay = None
        self.close()

    def open_voice_drawer(self) -> None:
        """Expand the progressive-disclosure VoiceDrawer sub-panel."""
        self._voice_btn.setChecked(True)
        self._voice_drawer.setVisible(True)
        self.adjustSize()

    def _on_toggle_voice(self) -> None:
        self._voice_drawer.setVisible(self._voice_btn.isChecked())
        self.adjustSize()

    def _sync_save_button_state(self, _active: bool = False) -> None:
        if self._voice_drawer.is_recording:
            self._save_btn.setEnabled(False)
            self._save_btn.setText("Recording...")
            self._save_btn.setToolTip("Finish recording first")
        elif self._voice_drawer.is_transcribing:
            self._save_btn.setEnabled(False)
            self._save_btn.setText("Transcribing...")
            self._save_btn.setToolTip("Wait for offline transcription to finish")
        else:
            self._save_btn.setEnabled(True)
            self._save_btn.setText("Save entry")
            self._save_btn.setToolTip("")

    def _on_take_screenshot(self) -> None:
        if self._capturing_screen:
            return
        logger.info("Starting WeChat-style screenshot capture.")
        self._capturing_screen = True
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(250, self, self._run_screen_capture)

    def _run_screen_capture(self) -> None:
        try:
            frozen, virtual_rect = grab_virtual_desktop()
            if frozen.isNull():
                logger.info("Screenshot capture aborted: frozen virtual desktop is empty.")
                return
            self._overlay = CaptureOverlay(frozen, virtual_rect)
            if self._overlay.exec() == QDialog.DialogCode.Accepted and (
                res := self._overlay.capture_result
            ) is not None:
                if self._sound_player is not None:
                    self._sound_player.play_screenshot_click()
                orig_bytes = pixmap_to_png_bytes(res.original)
                ann_bytes = pixmap_to_png_bytes(res.annotated) if res.annotated is not None else None
                self._attachments.add_screenshot(
                    orig_bytes,
                    ann_bytes,
                    preview_pixmap=(res.annotated if res.annotated is not None else res.original),
                )
                logger.info(
                    "Confirmed screenshot added to entry (%dx%d px, annotated=%s).",
                    res.original.width(),
                    res.original.height(),
                    res.annotated is not None,
                )
            else:
                logger.info("Screenshot capture cancelled by user.")
        except Exception:
            logger.exception("Screenshot capture failed unexpectedly.")
        finally:
            if self._overlay is not None:
                self._overlay.deleteLater()
                self._overlay = None
            self._capturing_screen = False
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self.adjustSize()
            logger.info("QuickCaptureDialog restored (visible=%s).", self.isVisible())

    def _on_attach_image(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
        )
        for path in paths:
            self._attachments.add_external_image(Path(path))

    def _on_discard_draft(self) -> None:
        self._service.clear_draft()
        self._note_input.clear()
        self._file_input.clear()
        self._attachments.clear()
        self._voice_drawer.clear()
        self._voice_drawer.setVisible(False)
        self._voice_btn.setChecked(False)
        self._milestone_btn.setChecked(False)
        self._draft_bar.setVisible(False)
        self.adjustSize()

    def _on_save_entry(self) -> None:
        self._voice_drawer.shutdown()
        shots = [
            ScreenshotData(original_bytes=s.original_bytes, annotated_bytes=s.annotated_bytes)
            for s in self._attachments.queued_screenshots()
        ]
        try:
            self._service.save_capture(
                project_id=self._project_combo.currentData(),
                note_text=self._note_input.toPlainText(),
                linked_file=self._file_input.text(),
                screenshots=shots,
                external_image_paths=self._attachments.external_images(),
                is_milestone=self._milestone_btn.isChecked(),
                audio_wav_path=self._voice_drawer.audio_wav_path(),
                transcription=self._voice_drawer.transcription_text(),
                audio_retention=self._voice_drawer.audio_retention(),
            )
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Quick Capture", str(exc))
            return
        self._milestone_btn.setChecked(False)
        self._saved = True
        self.accept()

    def _persist_draft_if_needed(self) -> None:
        if self._saved:
            return
        self._voice_drawer.shutdown()
        persist_draft_from_widgets(
            self._service,
            self._project_combo,
            self._file_input,
            self._note_input,
            self._attachments,
            is_milestone=self._milestone_btn.isChecked(),
            draft_audio_path=self._voice_drawer.audio_wav_path(),
            draft_transcript=self._voice_drawer.transcription_text(),
            audio_retention=self._voice_drawer.audio_retention(),
        )

    def _update_milestone_style(self, checked: bool) -> None:
        pal = get_palette()
        self._milestone_btn.setText("\u2605 Milestone" if checked else "\u2606 Milestone")
        if checked:
            self._milestone_btn.setStyleSheet(
                f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.amber}; border: 1px solid {pal.amber}; "
                "border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; }}"
            )
        else:
            self._milestone_btn.setStyleSheet(
                f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.muted}; border: 1px solid {pal.border}; "
                "border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {pal.hover_border}; color: {pal.text}; }}"
            )

    def _on_save_draft_and_close(self) -> None:
        self.close()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)

    def reject(self) -> None:
        if self._capturing_screen:
            logger.info("Ignoring reject while screenshot capture is active.")
            return
        if not self._in_close_event:
            self.close()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._capturing_screen:
            logger.info("Ignoring closeEvent while screenshot capture is active.")
            event.ignore()
            return
        self._persist_draft_if_needed()
        self._in_close_event = True
        try:
            super().closeEvent(event)
        finally:
            self._in_close_event = False
