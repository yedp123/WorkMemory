"""Style and draft persistence helpers for QuickCaptureDialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QDialog, QFrame, QLineEdit, QTextEdit

from work_memory.services.capture_service import CaptureService
from work_memory.ui.capture.attachment_list import AttachmentStrip
from work_memory.ui.theme import get_palette


def apply_capture_dialog_style(dialog: QDialog) -> None:
    """Apply the active theme's Quick Capture stylesheet to ``dialog``."""
    pal = get_palette()
    dialog.setWindowTitle("Quick Capture")
    dialog.setMinimumWidth(620)
    dialog.resize(650, 390)
    dialog.setStyleSheet(
        f"QDialog {{ background-color: {pal.panel}; color: {pal.text}; }}"
        f"QComboBox, QTextEdit {{ background-color: {pal.input_bg}; color: {pal.text}; "
        f"border: 1px solid {pal.border}; border-radius: 8px; padding: 6px 10px; font-size: 12px; }}"
        f"QComboBox:focus, QTextEdit:focus {{ border-color: {pal.focus_border}; }}"
    )


def restore_draft_into_widgets(
    service: CaptureService,
    project_combo: QComboBox,
    file_input: QLineEdit,
    note_input: QTextEdit,
    attachments: AttachmentStrip,
    draft_bar: QFrame,
) -> None:
    """Restore any saved Quick Capture draft into the form widgets."""
    if (draft := service.load_draft()) is None:
        return
    if draft.project_id and (idx := project_combo.findData(draft.project_id)) >= 0:
        project_combo.setCurrentIndex(idx)
    file_input.setText(draft.linked_file)
    note_input.setPlainText(draft.note_text)
    if (
        draft.temp_image_path
        and (img_path := Path(draft.temp_image_path)).is_file()
        and not (pm := QPixmap(str(img_path))).isNull()
    ):
        attachments.add_screenshot(img_path.read_bytes(), preview_pixmap=pm)
    draft_bar.setVisible(True)


def persist_draft_from_widgets(
    service: CaptureService,
    project_combo: QComboBox,
    file_input: QLineEdit,
    note_input: QTextEdit,
    attachments: AttachmentStrip,
    *,
    is_milestone: bool = False,
    draft_audio_path: str | Path | None = None,
    draft_transcript: str = "",
    audio_retention: str = "both",
) -> None:
    """Persist non-empty Quick Capture content into app-owned ``drafts/``."""
    note, linked = note_input.toPlainText(), file_input.text()
    preview: bytes | None = None
    if queued := attachments.queued_screenshots():
        preview = queued[-1].annotated_bytes or queued[-1].original_bytes
    if note.strip() or linked.strip() or preview or draft_audio_path or draft_transcript.strip():
        service.save_draft(
            project_id=project_combo.currentData(),
            linked_file=linked,
            note_text=note,
            preview_image_bytes=preview,
            is_milestone=is_milestone,
            draft_audio_path=draft_audio_path,
            draft_transcript=draft_transcript,
            audio_retention=audio_retention,
        )
