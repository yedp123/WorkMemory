"""Timestamp, file-name display, and layout clearing helpers for timeline widgets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from work_memory.core.models import ObservedEvent
from work_memory.ui.theme import get_palette


class CollapsibleSection(QWidget):
    """Hairline-separated collapsible category block for the timeline."""

    def __init__(
        self,
        key: str,
        icon: str,
        title: str,
        *,
        is_first: bool,
        expanded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = expanded
        pal = get_palette()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0 if is_first else 12, 0, 8)
        root.setSpacing(0)
        if not is_first:
            div = QFrame()
            div.setStyleSheet(f"background-color: {pal.border}; min-height: 1px; max-height: 1px;")
            root.addWidget(div)
            root.addSpacing(12)

        self._header_btn = QPushButton()
        self._header_btn.setObjectName(f"timelineSection_{key}")
        self._header_btn.setFlat(True)
        self._header_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header_btn.setFixedHeight(28)
        self._header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        h_row = QHBoxLayout(self._header_btn)
        h_row.setContentsMargins(0, 0, 0, 0)
        left = QLabel(f"{icon}  {title}")
        left.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        left.setStyleSheet(f"color: {pal.section_title}; font-size: 13px; font-weight: 600;")
        self._chevron = QLabel("\u2304" if expanded else "\u203a")
        self._chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._chevron.setStyleSheet(f"color: {pal.dim_text}; font-size: 14px;")
        h_row.addWidget(left, 1)
        h_row.addWidget(self._chevron)
        self._header_btn.clicked.connect(self.toggle)
        root.addWidget(self._header_btn)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(22, 8, 0, 0)
        self._body_layout.setSpacing(4)
        self._body.setVisible(expanded)
        root.addWidget(self._body)

    @property
    def is_expanded(self) -> bool:
        """Return ``True`` if this section's body is currently visible."""
        return self._expanded

    @property
    def body_layout(self) -> QVBoxLayout:
        """Return the vertical layout inside the collapsible body."""
        return self._body_layout

    def toggle(self) -> None:
        """Collapse or expand this timeline category."""
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._chevron.setText("\u2304" if self._expanded else "\u203a")
        self.updateGeometry()
        if (parent := self.parentWidget()) is not None:
            parent.updateGeometry()


def parse_local_dt(iso_utc: str) -> datetime | None:
    """Parse an ISO-8601 UTC string into a local-timezone ``datetime``."""
    try:
        normalized = f"{iso_utc[:-1]}+00:00" if iso_utc.endswith("Z") else iso_utc
        dt = datetime.fromisoformat(normalized)
        return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).astimezone()
    except ValueError:
        return None


def format_hhmm(iso_utc: str) -> str:
    """Format an ISO-8601 UTC timestamp as local ``HH:MM``."""
    dt = parse_local_dt(iso_utc)
    return dt.strftime("%H:%M") if dt is not None else iso_utc[11:16]


def format_ymd(iso_utc: str) -> str:
    """Format an ISO-8601 UTC timestamp as local ``YYYY-MM-DD``."""
    dt = parse_local_dt(iso_utc)
    return dt.strftime("%Y-%m-%d") if dt is not None else iso_utc[:10]


def clear_layout(layout: QVBoxLayout) -> None:
    """Detach and schedule deletion for all widgets in ``layout``."""
    while layout.count():
        if (item := layout.takeAt(0)) is not None and (w := item.widget()) is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


def extract_file_display(ev: ObservedEvent) -> tuple[str, str, str]:
    """Return ``(ext_badge, display_name, rel_detail)`` for normal and sequence events."""
    rel = ev.rel_path
    if " .. " in rel:
        ext = PurePosixPath(rel.split(" .. ", 1)[0]).suffix.lstrip(".").upper()[:4] or "SEQ"
        return ext, rel.rsplit("/", 1)[-1], rel
    posix = PurePosixPath(rel)
    ext = posix.suffix.lstrip(".").upper()[:4] or "FILE"
    detail = f"{rel} (from {ev.old_rel_path})" if ev.old_rel_path else rel
    return ext, posix.name or rel, detail


@dataclass(frozen=True, slots=True)
class CollapsedFileItem:
    """Multiple same-file events in one group collapsed into a single display row."""

    latest_event: ObservedEvent
    count: int
    first_occurred_at_utc: str
    is_milestone: bool


def collapse_group_events(events: Sequence[ObservedEvent]) -> list[CollapsedFileItem]:
    """Collapse repeated events for the same ``rel_path`` within a group, preserving newest-first order."""
    buckets: dict[str, list[ObservedEvent]] = {}
    for ev in events:
        buckets.setdefault(ev.rel_path, []).append(ev)

    collapsed: list[CollapsedFileItem] = []
    for group_evs in buckets.values():
        latest = max(group_evs, key=lambda e: (e.occurred_at_utc, e.id))
        earliest = min(group_evs, key=lambda e: (e.occurred_at_utc, e.id))
        collapsed.append(
            CollapsedFileItem(
                latest_event=latest,
                count=len(group_evs),
                first_occurred_at_utc=earliest.occurred_at_utc,
                is_milestone=any(e.is_milestone for e in group_evs),
            )
        )
    return collapsed
