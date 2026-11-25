"""Calm dark MilestonePreviewDialog for inspecting full milestone notes, images, or file details."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from work_memory.core.models import Attachment, MilestoneDetail
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.timeline_rows import (
    build_audio_play_button,
    build_reveal_folder_button,
)


class MilestonePreviewDialog(QDialog):
    """Resizable dark dialog displaying full milestone content, attachments, and navigation actions."""

    jump_to_date_requested = Signal(QDate)
    unstar_requested = Signal(str, str)
    file_open_requested = Signal(str, str)
    file_reveal_requested = Signal(str, str)

    def __init__(self, detail: MilestoneDetail, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        pal = get_palette()
        self._pal = pal
        self._detail = detail
        kind_prefix = "Milestone" if detail.is_milestone else ("File" if detail.item_type == "observed" else "Note")
        self.setWindowTitle(f"{kind_prefix} \u00b7 {detail.title}")
        self.resize(660, 520)
        self.setMinimumSize(460, 360)
        self.setStyleSheet(
            f"QDialog {{ background-color: {pal.bg}; color: {pal.text}; }}"
            f"QScrollArea {{ background-color: {pal.bg}; border: 1px solid {pal.border}; border-radius: 10px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)
        root.addWidget(self._build_header(detail))
        root.addWidget(self._build_body(detail), 1)
        root.addLayout(self._build_footer(detail))

    def _build_header(self, detail: MilestoneDetail) -> QFrame:
        pal = self._pal
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {pal.panel}; border: 1px solid {pal.border}; border-radius: 10px; }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        tag = QLabel("File" if detail.item_type == "observed" else "Note")
        tag.setStyleSheet(
            f"background-color: {pal.panel_alt}; color: {pal.amber}; border: 1px solid {pal.border}; "
            "border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
        )
        when = QLabel(f"{detail.local_date.strftime('%Y-%m-%d')} at {detail.local_time_label} \u00b7 {detail.project_name}")
        when.setStyleSheet(f"color: {pal.muted}; font-size: 12px; border: none;")
        top.addWidget(tag, 0)
        top.addWidget(when, 1)
        col.addLayout(top)

        if detail.rel_path:
            path_btn = QPushButton(detail.rel_path)
            path_btn.setObjectName("milestoneFileLink")
            path_btn.setFlat(True)
            path_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            path_btn.setToolTip("Open file in default application")
            path_btn.setStyleSheet(
                "QPushButton#milestoneFileLink { font-family: 'Cascadia Code', Consolas, monospace; "
                f"font-size: 11px; color: {pal.accent}; background: transparent; border: none; "
                "padding: 0px; text-align: left; }"
                f"QPushButton#milestoneFileLink:hover {{ color: {pal.text}; text-decoration: underline; }}"
            )
            path_btn.clicked.connect(
                lambda _c=False, r=detail.rel_path, p=(detail.project_id or ""): (
                    self.file_open_requested.emit(r, p)
                )
            )
            path_row = QHBoxLayout()
            path_row.setContentsMargins(0, 0, 0, 0)
            path_row.setSpacing(6)
            path_row.addWidget(path_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            path_row.addWidget(
                build_reveal_folder_button(
                    lambda r=detail.rel_path, p=(detail.project_id or ""): (
                        self.file_reveal_requested.emit(r, p)
                    )
                ),
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
            path_row.addStretch(1)
            col.addLayout(path_row)
        return card

    def _build_body(self, detail: MilestoneDetail) -> QScrollArea:
        pal = self._pal
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setStyleSheet(f"background-color: {pal.panel};")
        col = QVBoxLayout(content)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(14)

        body_lbl = QLabel(detail.body_text)
        body_lbl.setWordWrap(True)
        body_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_lbl.setStyleSheet(f"color: {pal.text}; font-size: 13px; line-height: 1.45;")
        col.addWidget(body_lbl)

        if detail.transcription and detail.transcription.strip() != detail.body_text.strip():
            tr_lbl = QLabel(f"Transcript: {detail.transcription.strip()}")
            tr_lbl.setWordWrap(True)
            tr_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            tr_lbl.setStyleSheet(f"color: {pal.soft}; font-size: 12px; line-height: 1.4;")
            col.addWidget(tr_lbl)

        if detail.attachments and detail.attachments_dir:
            self._append_attachments(col, detail.attachments, detail.attachments_dir)

        col.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _append_attachments(
        self, col: QVBoxLayout, attachments: tuple[Attachment, ...], attachments_dir: str
    ) -> None:
        base = Path(attachments_dir)
        by_id = {a.id: a for a in attachments}
        paired_orig_ids: set[str] = set()
        groups: list[tuple[Attachment, Attachment | None]] = []

        for att in attachments:
            if att.kind == "annotated_screenshot":
                orig = by_id.get(att.original_attachment_id) if att.original_attachment_id else None
                if orig is not None:
                    paired_orig_ids.add(orig.id)
                groups.append((att, orig))

        for att in attachments:
            if att.kind in ("image", "screenshot") and att.id not in paired_orig_ids:
                groups.append((att, None))

        for primary, original in groups:
            if not (base / primary.stored_rel_path).is_file():
                continue
            col.addWidget(self._build_image_card(base, primary, original))

        for att in attachments:
            if att.kind == "audio" and (audio_file := base / att.stored_rel_path).is_file():
                row = QHBoxLayout()
                row.addWidget(build_audio_play_button(audio_file))
                row.addStretch(1)
                col.addLayout(row)

    def _build_image_card(
        self, base: Path, primary: Attachment, original: Attachment | None
    ) -> QFrame:
        pal = self._pal
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {pal.bg}; border: 1px solid {pal.border}; border-radius: 8px; }}")
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setStyleSheet("border: none;")
        state = {"show_original": False}

        def _render_img() -> None:
            target = original if (state["show_original"] and original is not None) else primary
            pm = QPixmap(str(base / target.stored_rel_path))
            if not pm.isNull():
                img_lbl.setPixmap(
                    pm.scaled(580, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )

        _render_img()
        vbox.addWidget(img_lbl)

        if original is not None and (base / original.stored_rel_path).is_file():
            toggle_btn = QPushButton("Show original")
            toggle_btn.setObjectName("milestoneImageToggleButton")
            toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle_btn.setProperty("secondary", True)

            def _toggle() -> None:
                state["show_original"] = not state["show_original"]
                toggle_btn.setText("Show annotated" if state["show_original"] else "Show original")
                _render_img()

            toggle_btn.clicked.connect(_toggle)
            vbox.addWidget(toggle_btn, 0, Qt.AlignmentFlag.AlignRight)
        return card

    def _build_footer(self, detail: MilestoneDetail) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        jump_btn = QPushButton("Jump to date")
        jump_btn.setObjectName("milestoneJumpDateButton")
        jump_btn.setProperty("secondary", True)
        jump_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        jump_btn.clicked.connect(self._on_jump_to_date)

        unstar_btn = QPushButton("\u2605 Unstar" if detail.is_milestone else "\u2606 Star milestone")
        unstar_btn.setObjectName("milestoneDialogUnstarButton")
        unstar_btn.setProperty("secondary", True)
        unstar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if detail.is_milestone:
            unstar_btn.setStyleSheet(f"color: {self._pal.amber}; border-color: {self._pal.amber};")
        unstar_btn.clicked.connect(self._on_unstar)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("milestoneCloseButton")
        close_btn.setProperty("primary", True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)

        row.addWidget(jump_btn)
        row.addWidget(unstar_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        return row

    def _on_jump_to_date(self) -> None:
        d = self._detail.local_date
        self.jump_to_date_requested.emit(QDate(d.year, d.month, d.day))
        self.accept()

    def _on_unstar(self) -> None:
        self.unstar_requested.emit(self._detail.item_type, self._detail.item_id)
        self.accept()
