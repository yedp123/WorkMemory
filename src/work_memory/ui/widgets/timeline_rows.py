"""Collapsible section and row builders shared by TimelineWidget."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QEnterEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from work_memory.core.models import Attachment, ObservedEvent, ObservedGroup
from work_memory.media.thumbnail_service import ThumbnailService, get_media_kind
from work_memory.ui.file_actions import build_folder_icon
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.thumbnail_badge import ThumbnailBadgeButton
from work_memory.ui.widgets.timeline_attachments import (
    append_audio_buttons,
    append_thumbnails,
    build_audio_play_button,
)
from work_memory.ui.widgets.timeline_format import (
    CollapsibleSection,
    clear_layout,
    extract_file_display,
    format_hhmm,
    format_ymd,
    parse_local_dt,
)

__all__ = [
    "CollapsibleSection",
    "build_audio_play_button",
    "build_event_action_button",
    "build_file_row",
    "build_reveal_folder_button",
    "build_timed_row",
    "clear_layout",
    "extract_file_display",
    "format_hhmm",
    "format_ymd",
    "parse_local_dt",
]


class _ClickableFileRow(QFrame):
    """Hoverable file-activity row that emits ``clicked`` to open the file read-only."""

    clicked = Signal()

    def __init__(
        self,
        title_label: QLabel,
        thumb_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title_lbl = title_label
        self._thumb_widget = thumb_widget
        pal = get_palette()
        self.setObjectName("timelineFileRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#timelineFileRow { background: transparent; border-radius: 7px; border: none; }"
            f"QFrame#timelineFileRow:hover {{ background-color: {pal.row_hover_rgba}; }}"
        )

    def enterEvent(self, event: QEnterEvent) -> None:
        pal = get_palette()
        font = self._title_lbl.font()
        font.setUnderline(True)
        self._title_lbl.setFont(font)
        self._title_lbl.setStyleSheet(f"color: {pal.text}; font-size: 12px; background: transparent;")
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        pal = get_palette()
        font = self._title_lbl.font()
        font.setUnderline(False)
        self._title_lbl.setFont(font)
        self._title_lbl.setStyleSheet(f"color: {pal.body_text}; font-size: 12px; background: transparent;")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
            and not (self._thumb_widget is not None and self._thumb_widget.underMouse())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def build_file_row(
    ev: ObservedEvent,
    group: ObservedGroup,
    *,
    show_project_names: bool,
    include_date: bool,
    change_count: int = 1,
    first_occurred_at_utc: str | None = None,
    on_open_file: Callable[[], None] | None = None,
    on_preview_file: Callable[[], None] | None = None,
    thumbnail_service: ThumbnailService | None = None,
) -> QWidget:
    """Build a clickable file-activity row with extension/thumbnail badge and path subtitle."""
    pal = get_palette()
    ext, name, rel_detail = extract_file_display(ev)
    title = QLabel(name)
    title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    title.setStyleSheet(f"color: {pal.body_text}; font-size: 12px; background: transparent;")

    use_thumb = (
        ev.event_type != "deleted"
        and get_media_kind(ev.rel_path) is not None
        and on_preview_file is not None
    )
    badge: QWidget
    if use_thumb and on_preview_file is not None:
        thumb_btn = ThumbnailBadgeButton(ext)
        thumb_btn.clicked.connect(lambda _c=False, fn=on_preview_file: fn())
        badge = thumb_btn
        if thumbnail_service is not None:
            thumbnail_service.request_thumbnail(
                ev.rel_path,
                project_id=ev.project_id,
                workspace_id=ev.workspace_id,
                size_px=76,
                callback=lambda img, b=thumb_btn: isValid(b) and b.set_thumbnail_image(img),
            )
    else:
        lbl_badge = QLabel(ext)
        lbl_badge.setProperty("role", "fileBadge")
        lbl_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_badge.setFixedSize(32, 26)
        badge = lbl_badge

    row_w: QWidget = (
        _ClickableFileRow(title, thumb_widget=badge if use_thumb else None)
        if on_open_file is not None
        else QWidget()
    )
    if isinstance(row_w, _ClickableFileRow) and on_open_file is not None:
        row_w.setToolTip(f"Open {name} in default app")
        row_w.clicked.connect(on_open_file)

    row = QHBoxLayout(row_w)
    row.setContentsMargins(4, 5, 4, 5)
    row.setSpacing(10)
    text_col = QVBoxLayout()
    text_col.setSpacing(1)

    prefix = f"{group.project_name} / " if show_project_names else ""
    end_hhmm = format_hhmm(ev.occurred_at_utc)
    end_ymd = format_ymd(ev.occurred_at_utc)
    if change_count > 1:
        start_iso = first_occurred_at_utc or ev.occurred_at_utc
        start_hhmm = format_hhmm(start_iso)
        start_ymd = format_ymd(start_iso)
        time_span = f"{start_hhmm}\u2013{end_hhmm}" if start_hhmm != end_hhmm else end_hhmm
        if include_date:
            when = (
                f"{end_ymd} {time_span}"
                if start_ymd == end_ymd
                else f"{start_ymd} {start_hhmm}\u2013{end_ymd} {end_hhmm}"
            )
        else:
            when = time_span
        sub_text = f"{prefix}{rel_detail} \u00b7 {change_count} changes \u00b7 {when}"
    else:
        when = f"{end_ymd} {end_hhmm}" if include_date else end_hhmm
        sub_text = f"{prefix}{rel_detail} \u00b7 {ev.event_type.capitalize()} \u00b7 {when}"
    sub = QLabel(sub_text)
    sub.setWordWrap(True)
    sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    sub.setStyleSheet(f"color: {pal.dim_text}; font-size: 11px; background: transparent;")
    text_col.addWidget(title)
    text_col.addWidget(sub)
    row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
    row.addLayout(text_col, 1)
    return row_w


def build_reveal_folder_button(on_reveal: Callable[[], None]) -> QPushButton:
    """Create a compact ``24x24`` folder icon button to reveal a file in Explorer."""
    pal = get_palette()
    btn = QPushButton()
    btn.setObjectName("revealInFolderButton")
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedSize(24, 24)
    btn.setIcon(build_folder_icon())
    btn.setIconSize(QSize(15, 15))
    btn.setToolTip("Open containing folder")
    btn.setStyleSheet(
        "QPushButton#revealInFolderButton { background: transparent; border: none; border-radius: 6px; padding: 0px; }"
        f"QPushButton#revealInFolderButton:hover {{ background-color: {pal.row_hover_rgba}; }}"
    )
    btn.clicked.connect(lambda _c=False, fn=on_reveal: fn())
    return btn


def _build_capture_meta_widget(
    meta_txt: str,
    linked_file: str | None,
    project_label: str | None,
    date_label: str | None,
    on_open_linked_file: Callable[[], None] | None,
    on_reveal_linked_file: Callable[[], None] | None = None,
) -> QWidget:
    pal = get_palette()
    if not linked_file or on_open_linked_file is None:
        lbl = QLabel(meta_txt)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {pal.dim_text}; font-size: 11px;")
        return lbl

    wrap = QWidget()
    hbox = QHBoxLayout(wrap)
    hbox.setContentsMargins(0, 0, 0, 0)
    hbox.setSpacing(5)
    muted_css = f"color: {pal.dim_text}; font-size: 11px;"
    if project_label:
        p_lbl = QLabel(f"{project_label} \u00b7")
        p_lbl.setStyleSheet(muted_css)
        hbox.addWidget(p_lbl)

    file_btn = QPushButton(linked_file)
    file_btn.setObjectName("captureLinkedFileLink")
    file_btn.setFlat(True)
    file_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    file_btn.setToolTip(f"Open {linked_file} in default app")
    file_btn.setStyleSheet(
        f"QPushButton#captureLinkedFileLink {{ background: transparent; border: none; "
        f"color: {pal.accent}; font-size: 11px; padding: 0px; text-align: left; }}"
        f"QPushButton#captureLinkedFileLink:hover {{ color: {pal.text}; text-decoration: underline; }}"
    )
    file_btn.clicked.connect(lambda _c=False, fn=on_open_linked_file: fn())
    hbox.addWidget(file_btn)
    if on_reveal_linked_file is not None:
        hbox.addWidget(build_reveal_folder_button(on_reveal_linked_file))

    if date_label:
        d_lbl = QLabel(f"\u00b7 {date_label}")
        d_lbl.setStyleSheet(muted_css)
        hbox.addWidget(d_lbl)
    hbox.addStretch(1)
    return wrap


def build_timed_row(
    time_txt: str, title_txt: str, meta_txt: str, status: str | None, *, is_first: bool,
    attachments: tuple[Attachment, ...] = (), attachments_dir: str = "",
    transcription_txt: str | None = None, linked_file: str | None = None,
    project_label: str | None = None, date_label: str | None = None,
    on_open_linked_file: Callable[[], None] | None = None,
    on_reveal_linked_file: Callable[[], None] | None = None,
) -> QWidget:
    """Build a capture or scheduled-event row with optional clickable linked-file path."""
    pal = get_palette()
    wrap = QWidget()
    outer = QVBoxLayout(wrap)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(6)
    if not is_first:
        sep = QFrame()
        sep.setStyleSheet(f"background-color: {pal.border_soft}; min-height: 1px; max-height: 1px;")
        outer.addWidget(sep)
    row = QHBoxLayout()
    row.setContentsMargins(0, 4, 0, 4)
    row.setSpacing(12)
    t_lbl = QLabel(time_txt)
    t_lbl.setFixedWidth(44)
    t_lbl.setStyleSheet(f"color: {pal.dim_text}; font-size: 12px;")
    col = QVBoxLayout()
    col.setSpacing(2)
    top_line = QHBoxLayout()
    top_line.setSpacing(6)
    main_lbl = QLabel(title_txt)
    main_lbl.setWordWrap(True)
    main_lbl.setStyleSheet(
        f"color: {pal.dim_text}; font-size: 12px; text-decoration: line-through;"
        if status == "cancelled" else f"color: {pal.body_text}; font-size: 12px;"
    )
    top_line.addWidget(main_lbl, 1)
    if status is not None:
        pill = QLabel(status)
        col_hex = pal.green if status == "completed" else (pal.muted if status == "cancelled" else pal.purple)
        bdr_hex = pal.pill_active_border if status == "completed" else (pal.border if status == "cancelled" else pal.purple)
        pill.setStyleSheet(f"color: {col_hex}; border: 1px solid {bdr_hex}; border-radius: 10px; padding: 1px 7px; font-size: 11px;")
        top_line.addWidget(pill)
    col.addLayout(top_line)
    col.addWidget(
        _build_capture_meta_widget(
            meta_txt, linked_file, project_label, date_label,
            on_open_linked_file, on_reveal_linked_file,
        )
    )
    if transcription_txt and transcription_txt.strip():
        tr_lbl = QLabel(f"Transcript: {transcription_txt.strip()}")
        tr_lbl.setWordWrap(True)
        tr_lbl.setStyleSheet(f"color: {pal.soft}; font-size: 11px; padding-top: 2px;")
        col.addWidget(tr_lbl)
    if attachments and attachments_dir:
        append_thumbnails(col, attachments, attachments_dir)
        append_audio_buttons(col, attachments, attachments_dir)
    row.addWidget(t_lbl, 0, Qt.AlignmentFlag.AlignTop)
    row.addLayout(col, 1)
    outer.addLayout(row)
    return wrap


def build_event_action_button(text: str, obj_name: str, slot: object) -> QPushButton:
    """Create a secondary timeline action pill button."""
    pal = get_palette()
    btn = QPushButton(text)
    btn.setObjectName(obj_name)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background-color: {pal.panel_alt}; color: {pal.soft}; border: 1px solid {pal.border}; "
        "border-radius: 6px; padding: 2px 8px; font-size: 11px; }}"
        f"QPushButton:hover {{ border-color: {pal.hover_border}; color: {pal.text}; }}"
    )
    btn.clicked.connect(slot)  # type: ignore[arg-type]
    return btn
