"""SQLite CRUD repository for monitored workspace roots."""

from __future__ import annotations

import sqlite3
import sys

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import Workspace
from work_memory.storage.database import Database

_SELECT_COLUMNS = (
    "id, name, root_path, is_active, last_scan_utc, created_at_utc, updated_at_utc"
)


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    return Workspace(
        id=str(row["id"]),
        name=str(row["name"]),
        root_path=str(row["root_path"]),
        is_active=bool(row["is_active"]),
        last_scan_utc=str(row["last_scan_utc"]) if row["last_scan_utc"] is not None else None,
        created_at_utc=str(row["created_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
    )


class WorkspaceRepository:
    """Data-access layer for the ``workspaces`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, workspace: Workspace) -> Workspace:
        """Persist a new monitored workspace record."""
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (
                    id, name, root_path, is_active, last_scan_utc,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    workspace.id,
                    workspace.name,
                    workspace.root_path,
                    int(workspace.is_active),
                    workspace.last_scan_utc,
                    workspace.created_at_utc,
                    workspace.updated_at_utc,
                ),
            )
        return workspace

    def get_by_id(self, workspace_id: str) -> Workspace | None:
        """Return a workspace by UUIDv7 identifier, or ``None`` if missing."""
        with self._db.connection() as conn:
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM workspaces WHERE id = ?;",
                (workspace_id,),
            ).fetchone()
        return _row_to_workspace(row) if row is not None else None

    def get_by_root_path(self, root_path: str) -> Workspace | None:
        """Look up a workspace by root path (case-insensitive on Windows)."""
        if sys.platform == "win32":
            sql = f"SELECT {_SELECT_COLUMNS} FROM workspaces WHERE LOWER(root_path) = LOWER(?);"
        else:
            sql = f"SELECT {_SELECT_COLUMNS} FROM workspaces WHERE root_path = ?;"
        with self._db.connection() as conn:
            row = conn.execute(sql, (root_path,)).fetchone()
        return _row_to_workspace(row) if row is not None else None

    def list_all(self, *, active_only: bool = False) -> list[Workspace]:
        """Return all registered workspaces ordered by creation time."""
        where_clause = "WHERE is_active = 1 " if active_only else ""
        sql = f"SELECT {_SELECT_COLUMNS} FROM workspaces {where_clause}ORDER BY created_at_utc ASC, id ASC;"
        with self._db.connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [_row_to_workspace(row) for row in rows]

    def set_active(self, workspace_id: str, is_active: bool) -> Workspace | None:
        """Toggle whether a workspace is actively observed."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE workspaces
                SET is_active = ?, updated_at_utc = ?
                WHERE id = ?;
                """,
                (int(is_active), now, workspace_id),
            )
        return self.get_by_id(workspace_id)

    def set_all_active(self, is_active: bool) -> int:
        """Set ``is_active`` across all registered workspaces and return updated row count."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            cursor = conn.execute(
                "UPDATE workspaces SET is_active = ?, updated_at_utc = ?;",
                (int(is_active), now),
            )
            return cursor.rowcount

    def update_last_scan(
        self, workspace_id: str, last_scan_utc: str | None = None
    ) -> Workspace | None:
        """Record the completion timestamp of a baseline or reconciliation scan."""
        scan_ts = last_scan_utc or utc_now_iso()
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE workspaces
                SET last_scan_utc = ?, updated_at_utc = ?
                WHERE id = ?;
                """,
                (scan_ts, now, workspace_id),
            )
        return self.get_by_id(workspace_id)

    def update_root_path(self, workspace_id: str, new_root_path: str) -> Workspace | None:
        """Update ``root_path`` for ``workspace_id`` without touching disk files."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE workspaces SET root_path = ?, updated_at_utc = ? WHERE id = ?;",
                (new_root_path, now, workspace_id),
            )
        return self.get_by_id(workspace_id)

    def delete(self, workspace_id: str) -> bool:
        """Remove a workspace record and cascade-delete its baseline and observed events."""
        with self._db.connection() as conn:
            cursor = conn.execute("DELETE FROM workspaces WHERE id = ?;", (workspace_id,))
            return cursor.rowcount > 0
