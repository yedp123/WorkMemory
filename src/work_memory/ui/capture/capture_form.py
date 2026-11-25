"""Form layout builders for QuickCaptureDialog."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from work_memory.core.models import Project
from work_memory.ui.theme import get_palette


@dataclass(slots=True)
class CaptureFormWidgets:
    """Interactive form controls created for ``QuickCaptureDialog``."""

    draft_bar: QFrame
    discard_draft_btn: QPushButton
    project_combo: QComboBox
    file_input: QLineEdit
    note_input: QTextEdit
    attach_btn: QPushButton
    shot_btn: QPushButton
    voice_btn: QPushButton
    save_draft_btn: QPushButton
    save_btn: QPushButton


def resolve_default_project_id(
    projects: Sequence[Project], initial_project_id: str | None
) -> str | None:
    """Pick ``initial_project_id`` when valid, else the most recently active project."""
    if initial_project_id and any(p.id == initial_project_id for p in projects):
        return initial_project_id
    if not projects:
        return None
    recent = max(
        projects,
        key=lambda p: (p.last_activity_utc or p.created_at_utc, p.created_at_utc, p.id),
    )
    return recent.id


def build_capture_header() -> QVBoxLayout:
    """Build the dialog title and subtle subtitle."""
    pal = get_palette()
    box = QVBoxLayout()
    box.setSpacing(2)
    title = QLabel("Quick Capture")
    title.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {pal.text};")
    sub = QLabel("Save a note, image, or screenshot to your project memory.")
    sub.setStyleSheet(f"font-size: 12px; color: {pal.muted};")
    box.addWidget(title)
    box.addWidget(sub)
    return box


def build_capture_form(
    root: QVBoxLayout,
    projects: Sequence[Project],
    *,
    initial_project_id: str | None,
    initial_linked_file: str,
    on_discard_draft: Callable[[], None],
    on_attach_image: Callable[[], None],
    on_take_screenshot: Callable[[], None],
    on_toggle_voice: Callable[[], None] | None = None,
) -> CaptureFormWidgets:
    """Populate header, draft bar, project/file row, note box, and action buttons."""
    root.addLayout(build_capture_header())

    draft_bar = QFrame()
    draft_bar.setObjectName("draftRecoveryBar")
    draft_bar.setStyleSheet(
        "QFrame#draftRecoveryBar { background-color: #2a251d; border: 1px solid #4d402c; border-radius: 8px; }"
    )
    d_row = QHBoxLayout(draft_bar)
    d_row.setContentsMargins(12, 7, 12, 7)
    msg = QLabel("Unfinished draft recovered.")
    msg.setStyleSheet("color: #d8b57c; font-size: 12px;")
    discard_btn = QPushButton("Discard")
    discard_btn.setObjectName("discardDraftButton")
    discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    discard_btn.setStyleSheet(
        "background: transparent; border: none; color: #d8b57c; font-size: 12px; font-weight: 600;"
    )
    discard_btn.clicked.connect(on_discard_draft)
    d_row.addWidget(msg, 1)
    d_row.addWidget(discard_btn)
    draft_bar.setVisible(False)
    root.addWidget(draft_bar)

    meta_row = QHBoxLayout()
    meta_row.setSpacing(12)
    project_combo = QComboBox()
    project_combo.setObjectName("captureProjectCombo")
    project_combo.addItem("General (no specific project)", None)
    for proj in projects:
        project_combo.addItem(proj.name, proj.id)
    if (default_pid := resolve_default_project_id(projects, initial_project_id)) is not None and (
        idx := project_combo.findData(default_pid)
    ) >= 0:
        project_combo.setCurrentIndex(idx)

    file_input = QLineEdit(initial_linked_file)
    file_input.setObjectName("captureLinkedFileInput")
    file_input.setProperty("darkInput", True)
    file_input.setPlaceholderText("Linked file (optional), e.g. export/rig.py")
    meta_row.addWidget(project_combo, 1)
    meta_row.addWidget(file_input, 1)
    root.addLayout(meta_row)

    note_input = QTextEdit()
    note_input.setObjectName("captureNoteInput")
    note_input.setPlaceholderText("Why did you make this decision? Where did you leave off?")
    note_input.setMinimumHeight(92)
    note_input.setMaximumHeight(140)
    root.addWidget(note_input)

    action_row = QHBoxLayout()
    action_row.setSpacing(8)
    attach_btn = QPushButton("+ Attach image")
    attach_btn.setObjectName("attachImageButton")
    attach_btn.setProperty("secondary", True)
    attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    attach_btn.clicked.connect(on_attach_image)

    shot_btn = QPushButton("Screenshot")
    shot_btn.setObjectName("takeScreenshotButton")
    shot_btn.setProperty("secondary", True)
    shot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    shot_btn.clicked.connect(on_take_screenshot)

    voice_btn = QPushButton("Voice note")
    voice_btn.setObjectName("toggleVoiceButton")
    voice_btn.setCheckable(True)
    voice_btn.setProperty("secondary", True)
    voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_toggle_voice is not None:
        voice_btn.clicked.connect(on_toggle_voice)

    action_row.addWidget(attach_btn)
    action_row.addWidget(shot_btn)
    action_row.addWidget(voice_btn)
    action_row.addStretch(1)
    root.addLayout(action_row)

    save_draft_btn = QPushButton("Save draft")
    save_draft_btn.setProperty("secondary", True)
    save_draft_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    save_btn = QPushButton("Save entry")
    save_btn.setObjectName("saveCaptureButton")
    save_btn.setProperty("primary", True)
    save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    return CaptureFormWidgets(
        draft_bar=draft_bar,
        discard_draft_btn=discard_btn,
        project_combo=project_combo,
        file_input=file_input,
        note_input=note_input,
        attach_btn=attach_btn,
        shot_btn=shot_btn,
        voice_btn=voice_btn,
        save_draft_btn=save_draft_btn,
        save_btn=save_btn,
    )


def build_capture_footer(save_draft_btn: QPushButton, save_btn: QPushButton) -> QHBoxLayout:
    """Build the dialog footer row with draft hint and primary actions."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 4, 0, 0)
    hint = QLabel("Closing keeps unfinished text as a draft.")
    hint.setStyleSheet(f"font-size: 11px; color: {get_palette().muted};")
    row.addWidget(hint, 1)
    row.addWidget(save_draft_btn)
    row.addWidget(save_btn)
    return row
