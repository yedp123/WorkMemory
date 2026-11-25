"""Read-only Watchdog filesystem observer with coalescing and overflow recovery."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import cast

from watchdog import events as wd_events
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch

from work_memory.core.event_bus import EventBus
from work_memory.core.models import ObservedEvent
from work_memory.watcher.coalescer import EventCoalescer, RawEventKind, RawFsEvent
from work_memory.watcher.filters import ExclusionFilter, to_rel_path

logger = logging.getLogger(__name__)
_HANDLED = {
    wd_events.EVENT_TYPE_CREATED: "created",
    wd_events.EVENT_TYPE_MODIFIED: "modified",
    wd_events.EVENT_TYPE_MOVED: "moved",
    wd_events.EVENT_TYPE_DELETED: "deleted",
}


def _safe_file_size(path: str | Path) -> int | None:
    try:
        return os.stat(path, follow_symlinks=False).st_size
    except OSError:
        return None


def _stop_watchdog(observer: BaseObserver | None) -> None:
    if observer is None:
        return
    try:
        observer.stop()
        observer.join(timeout=3.0)
    except (OSError, RuntimeError) as exc:
        logger.warning("Error stopping Watchdog observer: %s", exc)


class _WorkspaceEventHandler(wd_events.FileSystemEventHandler):
    """Translates Watchdog events into normalized ``RawFsEvent`` instances."""

    def __init__(
        self, workspace_id: str, root_path: Path, exclusion_filter: ExclusionFilter,
        push_fn: Callable[[RawFsEvent], None], overflow_fn: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._ws_id, self._root, self._filter = workspace_id, root_path, exclusion_filter
        self._push, self._overflow = push_fn, overflow_fn

    def on_any_event(self, event: wd_events.FileSystemEvent) -> None:
        try:
            if isinstance(event, wd_events.EventsLostEvent) or event.event_type == "events_lost":
                logger.warning("Watchdog buffer overflow for %s; reconciling.", self._ws_id)
                self._overflow(self._ws_id)
                return
            kind = None if event.is_directory else _HANDLED.get(event.event_type)
            if kind is None or not (rel_path := to_rel_path(src_str := os.fsdecode(event.src_path), self._root)):
                return
            dest_rel, stat_target = None, src_str
            if kind == "moved":
                if not (dest_raw := getattr(event, "dest_path", "")):
                    return
                stat_target = os.fsdecode(dest_raw)
                dest_rel = to_rel_path(stat_target, self._root)
            if self._in_ignored_dir(rel_path) and (dest_rel is None or self._in_ignored_dir(dest_rel)):
                return
            size = _safe_file_size(stat_target) if kind != "deleted" else None
            self._push(RawFsEvent(self._ws_id, cast(RawEventKind, kind), rel_path, dest_rel, size))
        except ValueError:
            logger.debug("Ignoring path outside workspace %s: %s", self._ws_id, event)
        except OSError as exc:
            logger.warning("Filesystem error observing %s (%s); reconciling.", self._ws_id, exc)
            self._overflow(self._ws_id)
        except Exception:
            logger.exception("Unexpected error in watchdog handler for %s", self._ws_id)

    def _in_ignored_dir(self, rel_path: str) -> bool:
        parent = PurePosixPath(rel_path).parent.as_posix()
        return parent != "." and self._filter.is_ignored_directory(parent)


class WorkspaceObserver:
    """Manages read-only Watchdog watches, coalescing, pause/resume, and overflow recovery."""

    def __init__(
        self, *, window_ms: int = 1000, exclusion_filter: ExclusionFilter | None = None,
        on_events: Callable[[list[ObservedEvent]], None] | None = None,
        on_overflow: Callable[[str], None] | None = None,
        event_bus: EventBus | None = None, known_existing: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._filter = exclusion_filter or ExclusionFilter()
        self._on_events, self._on_overflow, self._event_bus = on_events, on_overflow, event_bus
        self._lock = threading.RLock()
        self._workspaces: dict[str, Path] = {}
        self._wd_watches: dict[str, ObservedWatch] = {}
        self._observer: BaseObserver | None = None
        self._paused = self._running = False
        self._flush_stop = threading.Event()
        self._flush_thread: threading.Thread | None = None
        self._coalescer = EventCoalescer(
            window_ms=window_ms, exclusion_filter=self._filter,
            known_existing=known_existing, on_flush=self._dispatch_events,
        )

    @property
    def is_paused(self) -> bool:
        """Return ``True`` while observation is paused."""
        with self._lock:
            return self._paused

    @property
    def is_running(self) -> bool:
        """Return ``True`` if the observer lifecycle is started."""
        with self._lock:
            return self._running

    def start(self, *, paused: bool = False) -> None:
        """Start the background coalescer flush loop and Watchdog observer."""
        with self._lock:
            self._paused = paused
            if self._running:
                return
            self._running = True
            self._flush_stop.clear()
            self._flush_thread = threading.Thread(target=self._flush_loop, name="wm-coalescer-flush", daemon=True)
            self._flush_thread.start()
            if not self._paused:
                self._start_watchdog_locked()

    def watch_workspace(self, workspace_id: str, root_path: Path | str) -> None:
        """Register and watch a workspace root strictly read-only."""
        root = Path(root_path)
        with self._lock:
            self._workspaces[workspace_id] = root
            if self._running and not self._paused and self._observer is not None:
                self._schedule_one_locked(workspace_id, root)

    def unwatch_workspace(self, workspace_id: str) -> None:
        """Stop watching a workspace root without modifying any disk files."""
        with self._lock:
            self._workspaces.pop(workspace_id, None)
            watch = self._wd_watches.pop(workspace_id, None)
            if watch is not None and self._observer is not None:
                try:
                    self._observer.unschedule(watch)
                except OSError as exc:
                    logger.debug("Error unscheduling watch for %s: %s", workspace_id, exc)

    def pause(self) -> None:
        """Pause live observation and release Watchdog directory handles."""
        with self._lock:
            if self._paused:
                return
            self._paused = True
            observer, self._observer = self._observer, None
            self._wd_watches.clear()
        _stop_watchdog(observer)
        self._coalescer.flush()

    def resume(self) -> None:
        """Resume live observation for all registered workspaces."""
        with self._lock:
            if not self._paused:
                return
            self._paused = False
            if self._running:
                self._start_watchdog_locked()

    def flush(self) -> list[ObservedEvent]:
        """Synchronously flush any buffered coalesced events."""
        return self._coalescer.flush()

    def stop(self) -> None:
        """Flush buffered events and cleanly shut down Watchdog and timer threads."""
        with self._lock:
            if not self._running:
                return
            self._running, paused = False, self._paused
            self._flush_stop.set()
            flush_thread, self._flush_thread = self._flush_thread, None
            observer, self._observer = self._observer, None
            self._wd_watches.clear()
        _stop_watchdog(observer)
        self._coalescer.clear() if paused else self._coalescer.flush()
        if flush_thread is not None and flush_thread.is_alive():
            flush_thread.join(timeout=2.0)

    def _start_watchdog_locked(self) -> None:
        if self._observer is not None:
            return
        self._observer = Observer()
        for ws_id, root in list(self._workspaces.items()):
            self._schedule_one_locked(ws_id, root)
        try:
            self._observer.start()
        except OSError as exc:
            logger.warning("Failed to start Watchdog observer (%s); reconciling.", exc)
            self._observer = None
            self._wd_watches.clear()
            for ws_id in list(self._workspaces):
                self._notify_overflow(ws_id)

    def _schedule_one_locked(self, workspace_id: str, root: Path) -> None:
        if self._observer is None or workspace_id in self._wd_watches:
            return
        if not root.is_dir():
            logger.warning("Workspace folder missing during watch schedule: %s", root)
            return self._notify_overflow(workspace_id)
        handler = _WorkspaceEventHandler(workspace_id, root, self._filter, self._on_raw_event, self._notify_overflow)
        try:
            self._wd_watches[workspace_id] = self._observer.schedule(handler, str(root), recursive=True)
        except OSError as exc:
            logger.warning("OSError watching %s (%s); reconciling.", root, exc)
            self._notify_overflow(workspace_id)

    def _on_raw_event(self, event: RawFsEvent) -> None:
        if not self.is_paused and self.is_running:
            self._coalescer.push(event)

    def _notify_overflow(self, workspace_id: str) -> None:
        if self._on_overflow is not None:
            self._on_overflow(workspace_id)

    def _dispatch_events(self, events: list[ObservedEvent]) -> None:
        if self._on_events is not None:
            try:
                self._on_events(events)
            except Exception:
                logger.exception("ObservedEvent callback failed.")
        if self._event_bus is not None:
            for ev in events:
                self._event_bus.observed_event_recorded.emit(ev)

    def _flush_loop(self) -> None:
        while not self._flush_stop.wait(timeout=0.1):
            if not self.is_paused:
                try:
                    self._coalescer.flush_expired()
                except Exception:
                    logger.exception("Error flushing coalescer window.")
