"""Application service orchestrating read-only workspace monitoring and baseline state."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from work_memory.core.event_bus import EventBus
from work_memory.core.models import ObservedEvent, Workspace
from work_memory.storage.database import Database
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.watcher import reconciler
from work_memory.watcher.filters import ExclusionFilter
from work_memory.watcher.observer import WorkspaceObserver

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Coordinates workspace registration, background scans, and live Watchdog observation."""

    def __init__(
        self, database: Database, event_bus: EventBus | None = None,
        *, window_ms: int = 1000, exclusion_filter: ExclusionFilter | None = None,
        project_service: Any | None = None,
    ) -> None:
        self._bus, self._project_service = event_bus, project_service
        self._ws_repo, self._ev_repo = WorkspaceRepository(database), ObservedEventRepository(database)
        self._filter = exclusion_filter or ExclusionFilter()
        self._reconciler = reconciler.WorkspaceReconciler(self._filter)
        self._observer = WorkspaceObserver(
            window_ms=window_ms, exclusion_filter=self._filter,
            on_events=self._on_observed_events, on_overflow=self._on_observer_overflow,
            known_existing=lambda ws_id, rel: rel in self._known_paths.get(ws_id, ()),
        )
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wm-workspace")
        self._lock, self._db_lock = threading.RLock(), threading.Lock()
        self._cached_workspaces, self._known_paths = [], {}
        self._pending, self._reconciling, self._is_paused, self._is_shutdown = set(), set(), False, False
    def set_project_service(self, project_service: Any | None) -> None:
        """Attach a ``ProjectService`` to resolve ``project_id`` on observed events."""
        self._project_service = project_service
    def cached_workspaces(self) -> list[Workspace]:
        """Return the latest in-memory workspace snapshot without blocking on SQLite."""
        with self._lock:
            return list(self._cached_workspaces)
    def is_monitoring_paused(self) -> bool:
        """Return ``True`` when workspace monitoring is globally paused."""
        with self._lock:
            return self._is_paused
    def list_workspaces(self) -> list[Workspace]:
        """Query all registered workspaces from SQLite and refresh the local cache."""
        with self._db_lock:
            workspaces = self._ws_repo.list_all()
        with self._lock:
            self._cached_workspaces = list(workspaces)
        return workspaces
    def list_events(self, workspace_id: str, *, limit: int = 200) -> list[ObservedEvent]:
        """Query recent observed events persisted for a workspace."""
        with self._db_lock:
            return self._ev_repo.list_by_workspace(workspace_id, limit=limit)
    def count_baseline(self, workspace_id: str) -> int:
        """Return the number of baseline file entries stored for a workspace."""
        with self._db_lock:
            return self._ev_repo.count_baseline(workspace_id)
    def start_async(self) -> Future[Any]:
        """Initialize workspaces, restart recovery, and live observation in background."""
        return self._submit(self.start, background_scans=False)
    def start(self, *, background_scans: bool = True) -> None:
        """Initialize monitoring for persisted workspaces and recover offline changes."""
        workspaces = self.list_workspaces()
        paused = bool(workspaces) and all(not ws.is_active for ws in workspaces)
        with self._lock:
            self._is_paused = paused
        self._observer.start(paused=paused)
        self._notify_bus(workspaces=True, paused=paused)
        for ws in workspaces:
            if not ws.is_active or paused:
                self._observer.watch_workspace(ws.id, Path(ws.root_path))
            else:
                self._submit(self.reconcile_workspace, ws.id, watch=True) if background_scans else self.reconcile_workspace(ws.id, watch=True)
    def add_workspace_async(self, root_path: str | Path, name: str | None = None) -> Future[Any]:
        """Register a workspace folder and run its baseline scan off the UI thread."""
        return self._submit(self.add_workspace, root_path, name, background_scan=False)
    def add_workspace(
        self, root_path: str | Path, name: str | None = None, *, background_scan: bool = True
    ) -> Workspace:
        """Register a workspace folder, establish its initial baseline, and watch it."""
        resolved = Path(root_path).expanduser().resolve(strict=False)
        if not resolved.is_dir():
            raise FileNotFoundError(f"Workspace folder does not exist: {resolved}")
        root_str = str(resolved)
        with self._db_lock:
            if self._ws_repo.get_by_root_path(root_str) is not None:
                raise ValueError(f"Workspace is already registered: {root_str}")
            ws = Workspace(name or resolved.name or root_str, root_str, is_active=not self.is_monitoring_paused())
            self._ws_repo.create(ws)
        self.list_workspaces()
        self._notify_bus(workspaces=True, status=f"Scanning {ws.name} (read-only)...")
        if not self._observer.is_running:
            self._observer.start(paused=self.is_monitoring_paused())
        self._submit(self.reconcile_workspace, ws.id, watch=True) if background_scan else self.reconcile_workspace(ws.id, watch=True)
        return ws
    def remove_workspace_async(self, workspace_id: str) -> Future[Any]:
        """Stop watching and remove a workspace record off the UI thread."""
        return self._submit(self.remove_workspace, workspace_id)
    def remove_workspace(self, workspace_id: str) -> bool:
        """Stop observing a workspace and remove its Work Memory records (files untouched)."""
        self._observer.unwatch_workspace(workspace_id)
        with self._db_lock:
            deleted = self._ws_repo.delete(workspace_id)
        with self._lock:
            self._known_paths.pop(workspace_id, None)
        self.list_workspaces()
        self._notify_bus(workspaces=True, status="Workspace removed from monitoring (files untouched)" if deleted else None)
        return deleted

    def rebind_workspace_root(
        self, workspace_id: str, new_root: Path, *, background_scan: bool = False
    ) -> None:
        """Unwatch old root, clear cached paths, and reconcile/watch ``new_root``."""
        del new_root
        self._observer.unwatch_workspace(workspace_id)
        with self._lock:
            self._known_paths.pop(workspace_id, None)
        self.list_workspaces()
        if not self._observer.is_running:
            self._observer.start(paused=self.is_monitoring_paused())
        if background_scan:
            self._submit(self.reconcile_workspace, workspace_id, watch=True)
        else:
            self.reconcile_workspace(workspace_id, watch=True)
        self._notify_bus(workspaces=True, status="Workspace relinked (read-only)")

    def set_monitoring_paused_async(self, paused: bool) -> Future[Any]:
        """Pause or resume observation off the UI thread."""
        return self._submit(self.set_monitoring_paused, paused)
    def set_monitoring_paused(self, paused: bool) -> None:
        """Pause or resume live Watchdog observation and persist workspace state."""
        with self._lock:
            self._is_paused = paused
        if paused:
            self._observer.pause()
        with self._db_lock:
            self._ws_repo.set_all_active(not paused)
        workspaces = self.list_workspaces()
        if not paused:
            for ws in workspaces:
                self._observer.watch_workspace(ws.id, Path(ws.root_path))
                if ws.last_scan_utc is None:
                    self._submit(self.reconcile_workspace, ws.id, watch=True)
            self._observer.resume() if self._observer.is_running else self._observer.start(paused=False)
        self._notify_bus(workspaces=True, paused=paused, status="Monitoring paused" if paused else "Observing workspaces (read-only)")
    def pause_monitoring(self) -> None:
        """Pause live Watchdog observation."""
        self.set_monitoring_paused(True)
    def resume_monitoring(self) -> None:
        """Resume live Watchdog observation."""
        self.set_monitoring_paused(False)
    def reconcile_workspace(self, workspace_id: str, *, watch: bool = False) -> reconciler.ReconcileResult | None:
        """Run an initial baseline or restart reconciliation scan for one workspace."""
        with self._db_lock:
            if (ws := self._ws_repo.get_by_id(workspace_id)) is None:
                return None
            prev_map = self._ev_repo.get_baseline_map(ws.id)
        result = self._reconciler.reconcile(ws.id, Path(ws.root_path), prev_map, is_initial=(ws.last_scan_utc is None))
        if result.events and self._project_service is not None:
            self._project_service.attach_project_ids(result.events, {ws.id: Path(ws.root_path)})
        with self._db_lock:
            self._ev_repo.replace_baseline(ws.id, result.baseline_entries)
            if result.events:
                self._ev_repo.insert_batch(result.events)
            self._ws_repo.update_last_scan(ws.id, result.scanned_at_utc)
        if result.events and self._project_service is not None:
            self._project_service.record_activity_for_events(result.events)
        with self._lock:
            self._known_paths[ws.id] = {e.rel_path for e in result.baseline_entries}
        self.list_workspaces()
        if watch and ws.is_active and not self.is_monitoring_paused():
            self._observer.watch_workspace(ws.id, Path(ws.root_path))
        self._notify_bus(workspaces=True, events=result.events, status=None if self.is_monitoring_paused() else "Observing workspaces (read-only)")
        return result
    def flush_observer(self) -> list[ObservedEvent]:
        """Flush buffered live observer events immediately and persist them."""
        return self._observer.flush()
    def wait_for_scans(self, timeout: float = 10.0) -> None:
        """Wait for all currently queued background scan tasks to finish."""
        with self._lock:
            futures = list(self._pending)
        for fut in futures:
            fut.result(timeout=timeout)
    def shutdown(self) -> None:
        """Stop live observation, flush pending events, and shut down worker threads."""
        with self._lock:
            if self._is_shutdown:
                return
            self._is_shutdown = True
        self._observer.stop()
        self._executor.shutdown(wait=True)

    def _on_observer_overflow(self, workspace_id: str) -> None:
        with self._lock:
            if self._is_shutdown or workspace_id in self._reconciling:
                return
            self._reconciling.add(workspace_id)
        def _run() -> None:
            try:
                self.reconcile_workspace(workspace_id)
            finally:
                with self._lock:
                    self._reconciling.discard(workspace_id)
        self._submit(_run)

    def _on_observed_events(self, events: list[ObservedEvent]) -> None:
        if not events:
            return
        if self._project_service is not None:
            self._project_service.attach_project_ids(events, {ws.id: Path(ws.root_path) for ws in self.cached_workspaces()})
        with self._db_lock:
            self._ev_repo.insert_batch(events)
            roots = {ws.id: Path(ws.root_path) for ws in self._ws_repo.list_all()}
            to_upsert, to_delete, rescan_ws = reconciler.collect_baseline_updates(events, roots, self._filter)
            for ws_id, paths in to_delete.items():
                self._ev_repo.delete_baseline_paths(ws_id, paths)
                with self._lock:
                    self._known_paths.get(ws_id, set()).difference_update(paths)
            if to_upsert:
                self._ev_repo.upsert_baseline_entries(to_upsert)
                with self._lock:
                    for entry in to_upsert:
                        self._known_paths.setdefault(entry.workspace_id, set()).add(entry.rel_path)
        if self._project_service is not None:
            self._project_service.record_activity_for_events(events)
        for ws_id in rescan_ws:
            self._on_observer_overflow(ws_id)
        self._notify_bus(events=events)

    def _submit(self, fn: Any, *args: Any, **kwargs: Any) -> Future[Any]:
        def _done(fut: Future[Any]) -> None:
            with self._lock:
                self._pending.discard(fut)
            if (exc := fut.exception()) is not None:
                logger.exception("Background workspace task failed.", exc_info=exc)
        with self._lock:
            if self._is_shutdown:
                fut: Future[Any] = Future()
                fut.set_result(None)
                return fut
            future = self._executor.submit(fn, *args, **kwargs)
            self._pending.add(future)
        future.add_done_callback(_done)
        return future

    def _notify_bus(self, *, workspaces: bool = False, paused: bool | None = None, events: list[ObservedEvent] | None = None, status: str | None = None) -> None:
        if self._bus is not None:
            if workspaces:
                self._bus.workspaces_changed.emit()
            if paused is not None:
                self._bus.monitoring_paused_changed.emit(paused)
            for ev in events or ():
                self._bus.observed_event_recorded.emit(ev)
            if status:
                self._bus.status_message.emit(status)
