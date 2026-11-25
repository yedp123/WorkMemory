"""Reusable collapsible unified timeline widget matching docs/ui_prototype.html."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from work_memory.core.models import (
    CalendarEvent,
    CaptureEntry,
    DayTimeline,
    ObservedGroup,
)
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.timeline_format import (
    CollapsedFileItem,
    collapse_group_events,
)
from work_memory.ui.widgets.timeline_rows import (
    CollapsibleSection,
    build_event_action_button,
    build_file_row,
    build_reveal_folder_button,
    build_timed_row,
    clear_layout,
    format_hhmm,
    format_ymd,
)

_DEFAULT_EMPTY_TEXT = "No activity, notes, or scheduled events for this selection."


class TimelineWidget(QWidget):
    """Displays separated collapsible Files changed, Notes & captures, and Scheduled events."""

    milestone_toggled = Signal(str, str)
    event_edit_requested = Signal(object)
    event_status_requested = Signal(str, str)
    file_open_requested = Signal(str, str, str)
    file_reveal_requested = Signal(str, str, str)
    file_preview_requested = Signal(str, str, str)

    def __init__(
        self,
        *,
        show_project_names: bool = True,
        thumbnail_service: ThumbnailService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._show_project_names = show_project_names
        self._thumbnail_service = thumbnail_service
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self.set_timeline(DayTimeline(local_date=None))

    def set_show_project_names(self, show: bool) -> None:
        """Control whether project names are shown inside row subtitles."""
        self._show_project_names = show

    def set_timeline(self, timeline: DayTimeline, *, empty_text: str | None = None) -> None:
        """Render ``timeline`` into the 3 collapsible sections or calm empty state."""
        clear_layout(self._layout)
        if timeline.is_empty:
            pal = get_palette()
            lbl = QLabel(empty_text or _DEFAULT_EMPTY_TEXT)
            lbl.setObjectName("timelineEmptyLabel")
            lbl.setProperty("role", "mutedBody")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {pal.muted}; font-size: 12px; padding: 10px 0;")
            self._layout.addWidget(lbl)
            return

        total_files = sum(len(g.events) for g in timeline.observed_groups)
        files_sec = CollapsibleSection(
            "files", "\u25a8", f"Files changed \u00b7 {total_files}", is_first=True, expanded=total_files > 0
        )
        self._populate_files(files_sec.body_layout, timeline)
        self._layout.addWidget(files_sec)

        cap_sec = CollapsibleSection(
            "captures", "\u270e", f"Notes & captures \u00b7 {len(timeline.captures)}",
            is_first=False, expanded=bool(timeline.captures),
        )
        self._populate_captures(cap_sec.body_layout, timeline)
        self._layout.addWidget(cap_sec)

        ev_sec = CollapsibleSection(
            "events", "\u25c7", f"Scheduled events \u00b7 {len(timeline.scheduled_events)}",
            is_first=False, expanded=bool(timeline.scheduled_events),
        )
        self._populate_events(ev_sec.body_layout, timeline)
        self._layout.addWidget(ev_sec)
        self.updateGeometry()

    def _populate_files(self, layout: QVBoxLayout, timeline: DayTimeline) -> None:
        if not timeline.observed_groups:
            layout.addWidget(self._muted_line("No file changes recorded."))
            return
        multi = len(timeline.observed_groups) > 1 or timeline.local_date is None
        include_date = timeline.local_date is None
        pal = get_palette()
        for idx, group in enumerate(timeline.observed_groups):
            if idx > 0:
                layout.addSpacing(8)
            if multi:
                when = f"{group.local_date_label} {group.local_time_label}" if include_date else group.local_time_label
                hdr = QLabel(f"{group.project_name} \u00b7 {when}" if self._show_project_names else when)
                hdr.setStyleSheet(f"color: {pal.muted}; font-size: 11px; font-weight: 600; padding: 2px 0;")
                layout.addWidget(hdr)
            collapsed = collapse_group_events(group.events)
            for item in collapsed[:3]:
                layout.addWidget(self._make_file_item(item, group, include_date))
            if len(collapsed) > 3:
                extra_count = len(collapsed) - 3
                extra_box = QWidget()
                extra_box.setVisible(False)
                extra_lay = QVBoxLayout(extra_box)
                extra_lay.setContentsMargins(0, 0, 0, 0)
                extra_lay.setSpacing(2)
                for item in collapsed[3:]:
                    extra_lay.addWidget(self._make_file_item(item, group, include_date))
                layout.addWidget(extra_box)
                btn = QPushButton(f"+ Show {extra_count} more files")
                btn.setObjectName("moreFilesButton")
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; border: none; color: {pal.accent}; font-size: 11px; text-align: left; padding: 4px 0 2px 38px; }}"
                    "QPushButton:hover { text-decoration: underline; }"
                )
                btn.clicked.connect(lambda _c=False, b=extra_box, t=btn, n=extra_count: self._toggle_more(b, t, n))
                layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

    def _make_file_item(
        self, item: CollapsedFileItem, group: ObservedGroup, include_date: bool
    ) -> QWidget:
        ev = item.latest_event
        row = build_file_row(
            ev,
            group,
            show_project_names=self._show_project_names,
            include_date=include_date,
            change_count=item.count,
            first_occurred_at_utc=item.first_occurred_at_utc,
            on_open_file=lambda r=ev.rel_path, p=(ev.project_id or ""), w=ev.workspace_id: (
                self.file_open_requested.emit(r, p, w)
            ),
            on_preview_file=lambda r=ev.rel_path, p=(ev.project_id or ""), w=ev.workspace_id: (
                self.file_preview_requested.emit(r, p, w)
            ),
            thumbnail_service=self._thumbnail_service,
        )
        return self._wrap_with_star(
            row,
            "observed",
            ev.id,
            item.is_milestone,
            on_reveal=lambda r=ev.rel_path, p=(ev.project_id or ""), w=ev.workspace_id: (
                self.file_reveal_requested.emit(r, p, w)
            ),
        )

    @staticmethod
    def _toggle_more(box: QWidget, btn: QPushButton, count: int) -> None:
        show = not box.isVisible()
        box.setVisible(show)
        btn.setText("\u2212 Show fewer files" if show else f"+ Show {count} more files")

    def _populate_captures(self, layout: QVBoxLayout, timeline: DayTimeline) -> None:
        if not timeline.captures:
            layout.addWidget(self._muted_line("No notes or captures recorded."))
            return
        for idx, cap in enumerate(timeline.captures):
            layout.addWidget(self._build_capture_row(cap, timeline, idx == 0))

    def _build_capture_row(self, cap: CaptureEntry, timeline: DayTimeline, is_first: bool) -> QWidget:
        atts = timeline.capture_attachments.get(cap.id, ())
        note = cap.note_text.strip()
        spoken = (cap.transcription or cap.transcript_text or "").strip()
        if note:
            body, extra_transcript = note, spoken or None
        elif spoken:
            body, extra_transcript = spoken, None
        else:
            has_audio = any(a.kind == "audio" for a in atts)
            body = "(Audio voice note)" if has_audio else ("(Image / screenshot capture)" if atts else "(Capture)")
            extra_transcript = None

        proj_lbl = (
            timeline.project_names[cap.project_id]
            if self._show_project_names and cap.project_id and cap.project_id in timeline.project_names
            else None
        )
        date_lbl = format_ymd(cap.captured_at_utc)
        parts = [p for p in (proj_lbl, cap.rel_path, date_lbl) if p]
        row = build_timed_row(
            format_hhmm(cap.captured_at_utc),
            body,
            " \u00b7 ".join(parts),
            None,
            is_first=is_first,
            attachments=atts,
            attachments_dir=timeline.attachments_dir,
            transcription_txt=extra_transcript,
            linked_file=cap.rel_path,
            project_label=proj_lbl,
            date_label=date_lbl,
            on_open_linked_file=(
                (lambda _c=False, r=cap.rel_path, p=(cap.project_id or ""): self.file_open_requested.emit(r, p, ""))
                if cap.rel_path
                else None
            ),
            on_reveal_linked_file=(
                (lambda r=cap.rel_path, p=(cap.project_id or ""): self.file_reveal_requested.emit(r, p, ""))
                if cap.rel_path
                else None
            ),
        )
        return self._wrap_with_star(row, "capture", cap.id, cap.is_milestone)

    def _wrap_with_star(
        self,
        row_widget: QWidget,
        item_type: str,
        item_id: str,
        is_milestone: bool,
        *,
        on_reveal: Callable[[], None] | None = None,
    ) -> QWidget:
        wrap = QWidget()
        hbox = QHBoxLayout(wrap)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(6)
        star_btn = QPushButton("\u2605" if is_milestone else "\u2606")
        star_btn.setObjectName("timelineStarButton")
        star_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        star_btn.setFixedSize(24, 24)
        star_btn.setToolTip("Unstar milestone" if is_milestone else "Star as milestone")
        pal = get_palette()
        color = pal.amber if is_milestone else pal.muted
        hover = pal.text if is_milestone else pal.soft
        star_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {color}; font-size: 14px; padding: 0; }}"
            f"QPushButton:hover {{ color: {hover}; }}"
        )
        star_btn.clicked.connect(lambda _c=False, t=item_type, i=item_id: self.milestone_toggled.emit(t, i))
        hbox.addWidget(row_widget, 1)
        if on_reveal is not None:
            hbox.addWidget(build_reveal_folder_button(on_reveal), 0, Qt.AlignmentFlag.AlignTop)
        hbox.addWidget(star_btn, 0, Qt.AlignmentFlag.AlignTop)
        return wrap

    def _populate_events(self, layout: QVBoxLayout, timeline: DayTimeline) -> None:
        if not timeline.scheduled_events:
            layout.addWidget(self._muted_line("No scheduled events."))
            return
        for idx, ev in enumerate(timeline.scheduled_events):
            layout.addWidget(self._build_event_row(ev, timeline.project_names, idx == 0))

    def _build_event_row(self, ev: CalendarEvent, project_names: dict[str, str], is_first: bool) -> QWidget:
        parts = [project_names.get(ev.project_id or "", "General") if ev.project_id else "General"] if self._show_project_names else []
        ev_ts = ev.event_at_utc or ev.starts_at_utc
        parts.append(format_ymd(ev_ts))
        if ev.reminder_minutes is None:
            parts.append("No reminder")
        elif ev.reminder_minutes == 0:
            parts.append("Remind at event")
        else:
            parts.append(f"Remind {ev.reminder_minutes}m before")
        if ev.description.strip():
            parts.append(ev.description.strip())

        wrap = QWidget()
        vbox = QVBoxLayout(wrap)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)
        vbox.addWidget(build_timed_row(format_hhmm(ev_ts), ev.title, " \u00b7 ".join(parts), ev.status, is_first=is_first))

        actions = QHBoxLayout()
        actions.setContentsMargins(56, 0, 0, 4)
        actions.setSpacing(6)
        actions.addWidget(build_event_action_button("Edit", "eventEditButton", lambda _c=False, e=ev: self.event_edit_requested.emit(e)))
        if ev.status == "scheduled":
            actions.addWidget(
                build_event_action_button(
                    "Mark completed", "eventCompleteButton",
                    lambda _c=False, eid=ev.id: self.event_status_requested.emit(eid, "completed"),
                )
            )
            actions.addWidget(
                build_event_action_button(
                    "Cancel", "eventCancelButton",
                    lambda _c=False, eid=ev.id: self.event_status_requested.emit(eid, "cancelled"),
                )
            )
        actions.addStretch(1)
        vbox.addLayout(actions)
        return wrap

    @staticmethod
    def _muted_line(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {get_palette().muted}; font-size: 12px; padding: 6px 0;")
        return lbl
