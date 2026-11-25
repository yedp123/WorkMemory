"""Short-window event coalescer for atomic saves, burst dedup, and image sequences."""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import ObservedEvent, ObservedEventType
from work_memory.watcher.filters import ExclusionFilter, normalize_rel_path

RawEventKind = Literal["created", "modified", "moved", "deleted"]
_FRAME_RE = re.compile(r"^(?P<prefix>.*?)(?P<frame>\d{2,})$")
SEQUENCE_EXTENSIONS: frozenset[str] = frozenset({
    ".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".dpx",
    ".bmp", ".hdr", ".webp", ".iff", ".cin", ".sxr", ".dds", ".vdb", ".bgeo",
})


@dataclass(frozen=True, slots=True)
class RawFsEvent:
    """Raw normalized-path filesystem notification queued for coalescing."""

    workspace_id: str
    kind: RawEventKind
    rel_path: str
    dest_rel_path: str | None = None
    file_size: int | None = None
    is_directory: bool = False
    occurred_at_utc: str = field(default_factory=utc_now_iso)
    monotonic_ts: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class _PathState:
    existed_before: bool
    origin_path: str | None
    file_size: int | None
    occurred_at_utc: str


def group_sequence_events(
    events: Sequence[ObservedEvent], *, min_sequence_length: int = 3
) -> list[ObservedEvent]:
    """Collapse numbered image/frame sequences into a single grouped ``ObservedEvent``."""
    buckets: dict[tuple[str, str, str, str, str], list[tuple[ObservedEvent, str, str, str]]] = defaultdict(list)
    keys: list[tuple[str, str, str, str, str] | None] = []
    for ev in events:
        posix = PurePosixPath(ev.rel_path)
        valid = ev.group_key is None and ev.event_type in ("created", "modified", "deleted")
        match = _FRAME_RE.match(posix.stem) if valid and posix.suffix.lower() in SEQUENCE_EXTENSIONS else None
        if match is None:
            keys.append(None)
            continue
        parent = "" if posix.parent == PurePosixPath(".") else posix.parent.as_posix()
        prefix, frame, ext = match.group("prefix"), match.group("frame"), posix.suffix
        key = (ev.workspace_id, ev.event_type, parent.lower(), prefix.lower(), ext.lower())
        buckets[key].append((ev, frame, posix.name, f"{parent}|{prefix}|{ext}"))
        keys.append(key)

    output: list[ObservedEvent] = []
    emitted: set[tuple[str, str, str, str, str]] = set()
    for ev, key in zip(events, keys, strict=True):
        if key is None or len(buckets[key]) < min_sequence_length:
            output.append(ev)
            continue
        if key in emitted:
            continue
        emitted.add(key)
        items = sorted(buckets[key], key=lambda item: (int(item[1]), item[1], item[2]))
        first_ev, first_frame, first_name, meta = items[0]
        _, last_frame, last_name, _ = items[-1]
        parent, prefix, ext = meta.split("|", 2)
        count = len(items)
        rel_path = f"{parent}/{first_name} .. {last_name} ({count} frames)" if parent else f"{first_name} .. {last_name} ({count} frames)"
        prefix_dir = f"{parent}/" if parent else ""
        sizes = [item[0].file_size for item in items if item[0].file_size is not None]
        output.append(ObservedEvent(
            first_ev.workspace_id, rel_path, first_ev.event_type,
            max(item[0].occurred_at_utc for item in items),
            file_size=sum(sizes) if sizes else None, is_baseline=first_ev.is_baseline,
            group_key=f"seq:{prefix_dir}{prefix}{'#' * len(first_frame)}{ext}:{first_frame}-{last_frame}:{count}",
        ))
    return output


class EventCoalescer:
    """Thread-safe short-window coalescer collapsing noise, bursts, and atomic saves."""

    def __init__(
        self, *, window_ms: int = 1000, max_window_ms: int = 3000, min_sequence_length: int = 3,
        exclusion_filter: ExclusionFilter | None = None,
        known_existing: Callable[[str, str], bool] | None = None,
        on_flush: Callable[[list[ObservedEvent]], None] | None = None,
    ) -> None:
        self._window_s = max(0.0, window_ms / 1000.0)
        self._max_window_s = max(self._window_s, max_window_ms / 1000.0)
        self._min_seq = max(2, min_sequence_length)
        self._filter = exclusion_filter or ExclusionFilter()
        self._known_existing, self._on_flush = known_existing, on_flush
        self._lock = threading.Lock()
        self._buffer: list[RawFsEvent] = []
        self._first_ts: float | None = None
        self._last_ts: float | None = None

    @property
    def window_ms(self) -> int:
        """Return configured coalescing debounce window in milliseconds."""
        return round(self._window_s * 1000)

    def has_pending(self) -> bool:
        """Return ``True`` if raw events are buffered awaiting flush."""
        with self._lock:
            return bool(self._buffer)

    def push(self, event: RawFsEvent) -> None:
        """Enqueue a raw filesystem event into the active coalescing window."""
        if event.is_directory:
            return
        rel = normalize_rel_path(event.rel_path)
        dest = normalize_rel_path(event.dest_rel_path) if event.dest_rel_path else None
        if not rel or (event.kind == "moved" and not dest):
            return
        norm = RawFsEvent(
            event.workspace_id, event.kind, rel, dest, event.file_size,
            False, event.occurred_at_utc, event.monotonic_ts,
        )
        with self._lock:
            self._buffer.append(norm)
            self._first_ts = norm.monotonic_ts if self._first_ts is None else self._first_ts
            self._last_ts = norm.monotonic_ts

    def flush_expired(self, now_monotonic: float | None = None) -> list[ObservedEvent]:
        """Flush buffered events if the coalescing window has elapsed."""
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            if not self._buffer or self._last_ts is None or self._first_ts is None:
                return []
            if (now - self._last_ts) < self._window_s and (now - self._first_ts) < self._max_window_s:
                return []
            batch = self._pop_locked()
        return self._emit_batch(batch)

    def flush(self) -> list[ObservedEvent]:
        """Immediately coalesce and emit all buffered events."""
        with self._lock:
            batch = self._pop_locked() if self._buffer else []
        return self._emit_batch(batch) if batch else []

    def clear(self) -> None:
        """Discard all currently buffered raw events without emitting."""
        with self._lock:
            self._pop_locked()

    def _pop_locked(self) -> list[RawFsEvent]:
        batch = list(self._buffer)
        self._buffer.clear()
        self._first_ts = self._last_ts = None
        return batch

    def _emit_batch(self, batch: list[RawFsEvent]) -> list[ObservedEvent]:
        by_ws: dict[str, list[RawFsEvent]] = defaultdict(list)
        for ev in batch:
            by_ws[ev.workspace_id].append(ev)
        out = [ev for ws_id, ws_batch in by_ws.items() for ev in group_sequence_events(self._coalesce_ws(ws_id, ws_batch), min_sequence_length=self._min_seq)]
        if out and self._on_flush is not None:
            self._on_flush(out)
        return out

    def _coalesce_ws(self, workspace_id: str, batch: list[RawFsEvent]) -> list[ObservedEvent]:
        existed: dict[str, tuple[str, int | None]] = {}
        live: dict[str, _PathState] = {}
        for ev in batch:
            p = ev.rel_path
            if ev.kind in ("created", "modified"):
                if p in live:
                    live[p].file_size = ev.file_size if ev.file_size is not None else live[p].file_size
                    live[p].occurred_at_utc = ev.occurred_at_utc
                elif ev.kind == "modified" or p in existed:
                    existed.setdefault(p, (ev.occurred_at_utc, ev.file_size))
                    live[p] = _PathState(True, p, ev.file_size, ev.occurred_at_utc)
                else:
                    live[p] = _PathState(False, None, ev.file_size, ev.occurred_at_utc)
            elif ev.kind == "deleted":
                removed = live.pop(p, None)
                if removed is None:
                    existed[p] = (ev.occurred_at_utc, ev.file_size)
                elif removed.existed_before and removed.origin_path:
                    existed[removed.origin_path] = (ev.occurred_at_utc, ev.file_size if ev.file_size is not None else removed.file_size)
            elif ev.kind == "moved" and ev.dest_rel_path and p != ev.dest_rel_path:
                self._apply_move(workspace_id, ev, live, existed)
        return self._finalize(workspace_id, live, existed)

    def _apply_move(
        self, workspace_id: str, ev: RawFsEvent,
        live: dict[str, _PathState], existed: dict[str, tuple[str, int | None]],
    ) -> None:
        src, dst = ev.rel_path, ev.dest_rel_path or ""
        if src in live:
            src_st = live.pop(src)
        elif self._filter.is_ignored(src):
            src_st = _PathState(False, None, ev.file_size, ev.occurred_at_utc)
        else:
            existed.setdefault(src, (ev.occurred_at_utc, ev.file_size))
            src_st = _PathState(True, src, ev.file_size, ev.occurred_at_utc)
        src_is_temp = self._filter.is_ignored(src) or not src_st.existed_before
        dst_known = bool(self._known_existing and not self._filter.is_ignored(dst) and self._known_existing(workspace_id, dst))
        dst_existed = dst in existed or (dst in live and live[dst].existed_before) or dst_known
        size = ev.file_size if ev.file_size is not None else src_st.file_size
        if src_is_temp and dst_existed:
            existed.setdefault(dst, (ev.occurred_at_utc, size))
            live[dst] = _PathState(True, dst, size, ev.occurred_at_utc)
        else:
            origin = None if src_is_temp else src_st.origin_path
            live[dst] = _PathState(not src_is_temp, origin, size, ev.occurred_at_utc)

    def _finalize(
        self, workspace_id: str, live: dict[str, _PathState],
        existed: dict[str, tuple[str, int | None]],
    ) -> list[ObservedEvent]:
        emitted: list[ObservedEvent] = []
        surviving: set[str] = set()
        for path, st in live.items():
            if self._filter.is_ignored(path):
                continue
            old_path: str | None = None
            if not st.existed_before:
                kind: ObservedEventType = "created"
            elif st.origin_path in (None, path):
                surviving.add(path)
                kind = "modified"
            else:
                assert st.origin_path is not None
                surviving.add(st.origin_path)
                same = PurePosixPath(st.origin_path).parent == PurePosixPath(path).parent
                kind, old_path = ("renamed" if same else "moved"), st.origin_path
            emitted.append(ObservedEvent(workspace_id, path, kind, st.occurred_at_utc, old_rel_path=old_path, file_size=st.file_size))
        emitted.extend(
            ObservedEvent(workspace_id, orig, "deleted", ts, file_size=size)
            for orig, (ts, size) in existed.items()
            if not self._filter.is_ignored(orig) and orig not in surviving
        )
        return emitted
