"""Fast read-only os.scandir() baseline scanner and restart reconciler."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import BaselineEntry, ObservedEvent
from work_memory.watcher.coalescer import group_sequence_events
from work_memory.watcher.filters import ExclusionFilter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Output of a baseline or restart reconciliation scan."""

    baseline_entries: list[BaselineEntry]
    events: list[ObservedEvent]
    is_initial_scan: bool
    scanned_at_utc: str


def mtime_ns_to_utc(mtime_ns: int, fallback_utc: str) -> str:
    """Format a nanosecond epoch timestamp into UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    if mtime_ns <= 0:
        return fallback_utc
    try:
        return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return fallback_utc


def stat_file_baseline(
    workspace_id: str, file_path: Path, rel_path: str, updated_at_utc: str | None = None,
    *, dir_entry: os.DirEntry[str] | None = None,
) -> BaselineEntry | None:
    """Read metadata for a single file via ``os.stat`` without opening file contents."""
    ts = updated_at_utc or utc_now_iso()
    try:
        st = os.stat(file_path, follow_symlinks=False)
    except PermissionError:
        if dir_entry is None:
            return None
        try:
            st = dir_entry.stat(follow_symlinks=False)
        except OSError as exc:
            logger.debug("Skipping inaccessible file %s: %s", file_path, exc)
            return None
    except OSError as exc:
        logger.debug("Unable to stat %s: %s", file_path, exc)
        return None
    return BaselineEntry(workspace_id, rel_path, st.st_size, st.st_mtime_ns, st.st_ino, ts)


def scan_directory_entries(
    workspace_id: str, workspace_root: Path, rel_dir: str,
    exclusion_filter: ExclusionFilter | None = None,
) -> list[BaselineEntry]:
    """Scan a single directory non-recursively to refresh baseline metadata."""
    filt = exclusion_filter or ExclusionFilter()
    target_dir = workspace_root / rel_dir if rel_dir else workspace_root
    ts = utc_now_iso()
    entries: list[BaselineEntry] = []
    try:
        with os.scandir(target_dir) as it:
            for entry in it:
                rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if filt.is_ignored(rel_path, is_dir=False):
                    continue
                item = stat_file_baseline(workspace_id, Path(entry.path), rel_path, ts, dir_entry=entry)
                if item is not None:
                    entries.append(item)
    except OSError as exc:
        logger.debug("Unable to scan directory %s: %s", target_dir, exc)
    return entries


class WorkspaceReconciler:
    """Read-only recursive ``os.scandir()`` baseline builder and restart diff engine."""

    def __init__(self, exclusion_filter: ExclusionFilter | None = None) -> None:
        self._filter = exclusion_filter or ExclusionFilter()

    def scan_tree(
        self, workspace_id: str, workspace_root: Path, *, scanned_at_utc: str | None = None
    ) -> dict[str, BaselineEntry]:
        """Walk ``workspace_root`` read-only via ``os.scandir`` and snapshot non-ignored files."""
        ts = scanned_at_utc or utc_now_iso()
        root = Path(workspace_root)
        if not root.is_dir():
            logger.warning("Workspace root does not exist or is not a directory: %s", root)
            return {}
        snapshot: dict[str, BaselineEntry] = {}
        stack: list[tuple[Path, str]] = [(root, "")]
        while stack:
            current_dir, prefix = stack.pop()
            try:
                with os.scandir(current_dir) as it:
                    entries = list(it)
            except OSError as exc:
                logger.warning("Skipping unreadable directory %s: %s", current_dir, exc)
                continue
            for entry in entries:
                rel_path = f"{prefix}/{entry.name}" if prefix else entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not self._filter.is_ignored(rel_path, is_dir=True):
                            stack.append((Path(entry.path), rel_path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError as exc:
                    logger.debug("Skipping entry %s due to stat error: %s", entry.path, exc)
                    continue
                if self._filter.is_ignored(rel_path, is_dir=False):
                    continue
                item = stat_file_baseline(workspace_id, Path(entry.path), rel_path, ts, dir_entry=entry)
                if item is not None:
                    snapshot[rel_path] = item
        return dict(sorted(snapshot.items(), key=lambda pair: pair[0]))

    def reconcile(
        self, workspace_id: str, workspace_root: Path,
        previous_baseline: Sequence[BaselineEntry] | Mapping[str, BaselineEntry] | None = None,
        *, is_initial: bool | None = None,
    ) -> ReconcileResult:
        """Build current baseline and recover missed events if this is a restart scan."""
        scanned_at = utc_now_iso()
        initial = (previous_baseline is None) if is_initial is None else is_initial
        current_map = self.scan_tree(workspace_id, workspace_root, scanned_at_utc=scanned_at)
        entries = list(current_map.values())
        if initial:
            return ReconcileResult(entries, [], True, scanned_at)
        if previous_baseline is None:
            prev_map: dict[str, BaselineEntry] = {}
        elif isinstance(previous_baseline, Mapping):
            prev_map = dict(previous_baseline)
        else:
            prev_map = {entry.rel_path: entry for entry in previous_baseline}
        events = self._diff_baselines(workspace_id, prev_map, current_map, scanned_at)
        return ReconcileResult(entries, events, False, scanned_at)

    def _diff_baselines(
        self, workspace_id: str, prev_map: dict[str, BaselineEntry],
        current_map: dict[str, BaselineEntry], scanned_at: str,
    ) -> list[ObservedEvent]:
        events: list[ObservedEvent] = []
        for rel_path, curr in current_map.items():
            prev = prev_map.get(rel_path)
            if prev is None:
                continue
            inode_changed = prev.file_id != 0 and curr.file_id != 0 and prev.file_id != curr.file_id
            if curr.file_size != prev.file_size or curr.mtime_ns != prev.mtime_ns or inode_changed:
                events.append(
                    ObservedEvent(
                        workspace_id, rel_path, "modified", mtime_ns_to_utc(curr.mtime_ns, scanned_at),
                        file_size=curr.file_size,
                    )
                )
        missing = set(prev_map.keys()) - set(current_map.keys())
        added = sorted(set(current_map.keys()) - set(prev_map.keys()))
        missing_by_id: dict[int, list[BaselineEntry]] = defaultdict(list)
        for path in sorted(missing):
            if prev_map[path].file_id != 0:
                missing_by_id[prev_map[path].file_id].append(prev_map[path])

        created: list[ObservedEvent] = []
        for rel_path in added:
            curr = current_map[rel_path]
            candidates = missing_by_id.get(curr.file_id) if curr.file_id != 0 else None
            if candidates:
                prev = _pick_best_rename_match(candidates, rel_path)
                missing.discard(prev.rel_path)
                same_dir = PurePosixPath(prev.rel_path).parent == PurePosixPath(rel_path).parent
                events.append(
                    ObservedEvent(
                        workspace_id, rel_path, "renamed" if same_dir else "moved",
                        mtime_ns_to_utc(curr.mtime_ns, scanned_at),
                        old_rel_path=prev.rel_path, file_size=curr.file_size,
                    )
                )
            else:
                created.append(
                    ObservedEvent(
                        workspace_id, rel_path, "created", mtime_ns_to_utc(curr.mtime_ns, scanned_at),
                        file_size=curr.file_size,
                    )
                )
        events.extend(group_sequence_events(created))
        for rel_path in sorted(missing):
            prev = prev_map[rel_path]
            events.append(
                ObservedEvent(workspace_id, rel_path, "deleted", scanned_at, file_size=prev.file_size)
            )
        return events


def _pick_best_rename_match(candidates: list[BaselineEntry], dest_rel_path: str) -> BaselineEntry:
    dest_posix = PurePosixPath(dest_rel_path)
    for idx, cand in enumerate(candidates):
        cand_posix = PurePosixPath(cand.rel_path)
        if cand_posix.name == dest_posix.name or cand_posix.parent == dest_posix.parent:
            return candidates.pop(idx)
    return candidates.pop(0)


def collect_baseline_updates(
    events: Sequence[ObservedEvent], roots: Mapping[str, Path], exclusion_filter: ExclusionFilter,
) -> tuple[list[BaselineEntry], dict[str, list[str]], set[str]]:
    """Compute read-only baseline upserts, deletes, and rescan workspace IDs from live events."""
    to_upsert: list[BaselineEntry] = []
    to_delete: dict[str, list[str]] = {}
    rescan_ws: set[str] = set()
    for ev in events:
        root = roots.get(ev.workspace_id)
        if ev.old_rel_path:
            to_delete.setdefault(ev.workspace_id, []).append(ev.old_rel_path)
        if ev.event_type == "deleted":
            if ev.group_key and ev.group_key.startswith("seq:"):
                rescan_ws.add(ev.workspace_id)
            else:
                to_delete.setdefault(ev.workspace_id, []).append(ev.rel_path)
        elif root is not None:
            if ev.group_key and ev.group_key.startswith("seq:"):
                parent = PurePosixPath(ev.rel_path).parent
                rel_dir = "" if parent == PurePosixPath(".") else parent.as_posix()
                to_upsert.extend(scan_directory_entries(ev.workspace_id, root, rel_dir, exclusion_filter))
            elif (entry := stat_file_baseline(ev.workspace_id, root / ev.rel_path, ev.rel_path)) is not None:
                to_upsert.append(entry)
    return to_upsert, to_delete, rescan_ws
