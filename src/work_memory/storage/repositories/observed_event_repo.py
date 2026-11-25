"""SQLite repository for observed filesystem events and baseline snapshots."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import cast

from work_memory.core.models import BaselineEntry, ObservedEvent, ObservedEventType
from work_memory.storage.database import Database

_I64_MAX = (1 << 63) - 1
_U64_MOD = 1 << 64

_EVENT_SELECT = (
    "id, workspace_id, project_id, rel_path, old_rel_path, event_type, "
    "file_size, is_baseline, is_milestone, group_key, occurred_at_utc, created_at_utc"
)
_BASELINE_SELECT = "workspace_id, rel_path, file_size, mtime_ns, file_id, updated_at_utc"
EVENT_SELECT_COLS = _EVENT_SELECT


def _to_sqlite_i64(file_id: int) -> int:
    """Convert an unsigned 64-bit NTFS file ID into SQLite signed 64-bit range."""
    if file_id <= _I64_MAX:
        return file_id
    masked = file_id & (_U64_MOD - 1)
    return masked - _U64_MOD if masked > _I64_MAX else masked


def _from_sqlite_u64(value: int) -> int:
    """Restore an unsigned 64-bit NTFS file ID from a SQLite signed 64-bit integer."""
    return value + _U64_MOD if value < 0 else value


def row_to_event(row: sqlite3.Row) -> ObservedEvent:
    """Convert a SQLite row into an ``ObservedEvent`` domain model."""
    return ObservedEvent(
        id=str(row["id"]),
        workspace_id=str(row["workspace_id"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        rel_path=str(row["rel_path"]),
        old_rel_path=str(row["old_rel_path"]) if row["old_rel_path"] is not None else None,
        event_type=cast(ObservedEventType, str(row["event_type"])),
        file_size=int(row["file_size"]) if row["file_size"] is not None else None,
        is_baseline=bool(row["is_baseline"]),
        is_milestone=bool(row["is_milestone"]),
        group_key=str(row["group_key"]) if row["group_key"] is not None else None,
        occurred_at_utc=str(row["occurred_at_utc"]),
        created_at_utc=str(row["created_at_utc"]),
    )


_row_to_event = row_to_event


def _row_to_baseline(row: sqlite3.Row) -> BaselineEntry:
    return BaselineEntry(
        workspace_id=str(row["workspace_id"]),
        rel_path=str(row["rel_path"]),
        file_size=int(row["file_size"]),
        mtime_ns=int(row["mtime_ns"]),
        file_id=_from_sqlite_u64(int(row["file_id"])),
        updated_at_utc=str(row["updated_at_utc"]),
    )


def _event_params(event: ObservedEvent) -> tuple[object, ...]:
    return (
        event.id,
        event.workspace_id,
        event.project_id,
        event.rel_path,
        event.old_rel_path,
        event.event_type,
        event.file_size,
        int(event.is_baseline),
        int(event.is_milestone),
        event.group_key,
        event.occurred_at_utc,
        event.created_at_utc,
    )


def _baseline_params(entry: BaselineEntry) -> tuple[object, ...]:
    return (
        entry.workspace_id,
        entry.rel_path,
        entry.file_size,
        entry.mtime_ns,
        _to_sqlite_i64(entry.file_id),
        entry.updated_at_utc,
    )


class ObservedEventRepository:
    """Data-access layer for ``observed_events`` and ``file_baseline``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(self, event: ObservedEvent) -> ObservedEvent:
        """Insert a single observed filesystem event."""
        self.insert_batch([event])
        return event

    def insert_batch(self, events: Sequence[ObservedEvent]) -> int:
        """Batch-insert observed events in a single transaction."""
        if not events:
            return 0
        sql = """
            INSERT INTO observed_events (
                id, workspace_id, project_id, rel_path, old_rel_path,
                event_type, file_size, is_baseline, is_milestone, group_key,
                occurred_at_utc, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = [_event_params(event) for event in events]
        with self._db.connection() as conn:
            conn.executemany(sql, params)
        return len(params)

    def _utc_select(self) -> str:
        return f"SELECT {_EVENT_SELECT} FROM observed_events"

    def get(self, event_id: str) -> ObservedEvent | None:
        """Return a single observed event by ID, or ``None`` if not found."""
        with self._db.connection() as conn:
            row = conn.execute(f"{self._utc_select()} WHERE id = ?;", (event_id,)).fetchone()
        return _row_to_event(row) if row is not None else None

    def set_milestone(self, event_id: str, is_milestone: bool) -> None:
        """Mark or unmark an observed event as a project milestone."""
        with self._db.connection() as conn:
            conn.execute("UPDATE observed_events SET is_milestone = ? WHERE id = ?;", (int(is_milestone), event_id))

    def list_milestones(self, project_id: str) -> list[ObservedEvent]:
        """Return all milestone-starred observed events for ``project_id`` newest-first."""
        sql = f"{self._utc_select()} WHERE project_id = ? AND is_milestone = 1 ORDER BY occurred_at_utc DESC, id DESC;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, (project_id,)).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_by_workspace(self, workspace_id: str, *, limit: int = 200, offset: int = 0) -> list[ObservedEvent]:
        """Query observed events for a workspace ordered newest-first."""
        sql = f"{self._utc_select()} WHERE workspace_id = ? ORDER BY occurred_at_utc DESC, id DESC LIMIT ? OFFSET ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, (workspace_id, limit, offset)).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_by_project(self, project_id: str, *, limit: int = 100, offset: int = 0) -> list[ObservedEvent]:
        """Query observed events linked to a project ordered newest-first."""
        sql = f"{self._utc_select()} WHERE project_id = ? ORDER BY occurred_at_utc DESC, id DESC LIMIT ? OFFSET ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, (project_id, limit, offset)).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None, limit: int = 2000
    ) -> list[ObservedEvent]:
        """Query non-baseline observed events in ``[start_utc, end_utc)`` newest-first."""
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, start_utc, end_utc, limit) if project_id is not None else (start_utc, end_utc, limit)
        sql = f"{self._utc_select()} WHERE {prefix}is_baseline = 0 AND occurred_at_utc >= ? AND occurred_at_utc < ? ORDER BY occurred_at_utc DESC, id DESC LIMIT ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_timestamps_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None
    ) -> list[str]:
        """Return distinct UTC timestamps for non-baseline observed events in ``[start_utc, end_utc)``."""
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, start_utc, end_utc) if project_id is not None else (start_utc, end_utc)
        sql = f"SELECT DISTINCT occurred_at_utc FROM observed_events WHERE {prefix}is_baseline = 0 AND occurred_at_utc >= ? AND occurred_at_utc < ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [str(row["occurred_at_utc"]) for row in rows]

    def assign_project_ids(self, updates: Sequence[tuple[str | None, str]]) -> int:
        """Update ``project_id`` for existing ``observed_events`` rows in batch."""
        if not updates:
            return 0
        sql = "UPDATE observed_events SET project_id = ? WHERE id = ?;"
        with self._db.connection() as conn:
            cursor = conn.executemany(sql, list(updates))
            return cursor.rowcount

    def count_by_workspace(self, workspace_id: str) -> int:
        """Return total observed event count for a workspace."""
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM observed_events WHERE workspace_id = ?;",
                (workspace_id,),
            ).fetchone()
        return int(row["cnt"]) if row is not None else 0

    def list_baseline(self, workspace_id: str) -> list[BaselineEntry]:
        """Load all baseline entries for a workspace ordered by ``rel_path``."""
        sql = (
            f"SELECT {_BASELINE_SELECT} FROM file_baseline "
            "WHERE workspace_id = ? ORDER BY rel_path ASC;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, (workspace_id,)).fetchall()
        return [_row_to_baseline(row) for row in rows]

    def get_baseline_map(self, workspace_id: str) -> dict[str, BaselineEntry]:
        """Return baseline entries indexed by POSIX ``rel_path``."""
        return {entry.rel_path: entry for entry in self.list_baseline(workspace_id)}

    def replace_baseline(self, workspace_id: str, entries: Sequence[BaselineEntry]) -> int:
        """Atomically replace the entire ``file_baseline`` snapshot for a workspace."""
        insert_sql = """
            INSERT INTO file_baseline (
                workspace_id, rel_path, file_size, mtime_ns, file_id, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?);
        """
        params = [_baseline_params(entry) for entry in entries]
        with self._db.connection() as conn:
            conn.execute("DELETE FROM file_baseline WHERE workspace_id = ?;", (workspace_id,))
            if params:
                conn.executemany(insert_sql, params)
        return len(params)

    def upsert_baseline_entries(self, entries: Sequence[BaselineEntry]) -> int:
        """Insert or update individual ``file_baseline`` records."""
        if not entries:
            return 0
        sql = """
            INSERT INTO file_baseline (
                workspace_id, rel_path, file_size, mtime_ns, file_id, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, rel_path) DO UPDATE SET
                file_size = excluded.file_size,
                mtime_ns = excluded.mtime_ns,
                file_id = excluded.file_id,
                updated_at_utc = excluded.updated_at_utc;
        """
        params = [_baseline_params(entry) for entry in entries]
        with self._db.connection() as conn:
            conn.executemany(sql, params)
        return len(params)

    def delete_baseline_paths(self, workspace_id: str, rel_paths: Sequence[str]) -> int:
        """Delete baseline entries for removed or renamed-away relative paths."""
        if not rel_paths:
            return 0
        sql = "DELETE FROM file_baseline WHERE workspace_id = ? AND rel_path = ?;"
        params = [(workspace_id, rel_path) for rel_path in rel_paths]
        with self._db.connection() as conn:
            cursor = conn.executemany(sql, params)
            return cursor.rowcount

    def count_baseline(self, workspace_id: str) -> int:
        """Return the number of baseline file records stored for a workspace."""
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM file_baseline WHERE workspace_id = ?;",
                (workspace_id,),
            ).fetchone()
        return int(row["cnt"]) if row is not None else 0
