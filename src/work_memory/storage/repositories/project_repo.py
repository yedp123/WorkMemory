"""SQLite CRUD repository for registered projects and dismissed discovery suggestions."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import PurePosixPath
from typing import cast

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import CoverStyle, DismissedSuggestion, Project, ProjectStatus
from work_memory.storage.database import Database

PROJECT_SELECT_COLS = (
    "id, workspace_id, name, rel_path, description, status, cover_style, cover_image_path, "
    "root_rel_path, abs_path, last_known_state, summary_custom, summary_generated, "
    "summary_updated_utc, last_activity_utc, is_pinned, created_at_utc, updated_at_utc"
)
_SELECT_COLS = PROJECT_SELECT_COLS
_ORDER_BY = "ORDER BY is_pinned DESC, COALESCE(last_activity_utc, created_at_utc) DESC, name ASC, id DESC;"
_VALID_STATUSES = frozenset({"ongoing", "completed"})
_VALID_COVERS = frozenset({"c1", "c2", "c3", "c4", "c5", "c6"})


def _normalize_rel(rel_path: str) -> str:
    posix = rel_path.replace("\\", "/").strip("/")
    while posix.startswith("./"):
        posix = posix[2:]
    return "" if posix in ("", ".") else PurePosixPath(posix).as_posix()


def escape_like(value: str) -> str:
    """Escape SQLite LIKE metacharacters for ``ESCAPE '\\'`` queries."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_escape_like = escape_like


def row_to_project(row: sqlite3.Row) -> Project:
    """Convert a SQLite row into a ``Project`` domain model."""
    cover_raw = str(row["cover_style"] or "c1")
    cover = cast(CoverStyle, cover_raw if cover_raw in _VALID_COVERS else "c1")
    rel_path = str(row["rel_path"])
    return Project(
        id=str(row["id"]),
        workspace_id=str(row["workspace_id"]),
        name=str(row["name"]),
        rel_path=rel_path,
        description=str(row["description"] or ""),
        status=cast(ProjectStatus, str(row["status"])),
        cover_style=cover,
        cover_image_path=str(row["cover_image_path"]) if row["cover_image_path"] is not None else None,
        root_rel_path=str(row["root_rel_path"] or "") or rel_path,
        abs_path=str(row["abs_path"] or ""),
        last_known_state=str(row["last_known_state"] or ""),
        summary_custom=str(row["summary_custom"]) if row["summary_custom"] is not None else None,
        summary_generated=str(row["summary_generated"]) if row["summary_generated"] is not None else None,
        summary_updated_utc=str(row["summary_updated_utc"]) if row["summary_updated_utc"] is not None else None,
        last_activity_utc=str(row["last_activity_utc"]) if row["last_activity_utc"] is not None else None,
        is_pinned=bool(row["is_pinned"]),
        created_at_utc=str(row["created_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
    )


_row_to_project = row_to_project


def _sync_fts(conn: sqlite3.Connection, project: Project) -> None:
    conn.execute("DELETE FROM fts_search WHERE entity_type = 'project' AND entity_id = ?;", (project.id,))
    conn.execute(
        "INSERT INTO fts_search (entity_type, entity_id, project_id, title, body, rel_path) "
        "VALUES (?, ?, ?, ?, ?, ?);",
        ("project", project.id, project.id, project.name, project.description, project.root_rel_path or project.rel_path),
    )


class ProjectRepository:
    """Data-access layer for ``projects`` and ``dismissed_suggestions``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project: Project) -> Project:
        """Persist a new registered project and index it in FTS5."""
        project.rel_path = _normalize_rel(project.rel_path)
        project.root_rel_path = _normalize_rel(project.root_rel_path or project.rel_path)
        params = (
            project.id, project.workspace_id, project.name, project.rel_path,
            project.description, project.status, project.cover_style, project.cover_image_path,
            project.root_rel_path, project.abs_path, project.last_known_state,
            project.summary_custom, project.summary_generated, project.summary_updated_utc,
            project.last_activity_utc, int(project.is_pinned), project.created_at_utc, project.updated_at_utc,
        )
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, rel_path, description, status, "
                "cover_style, cover_image_path, root_rel_path, abs_path, last_known_state, summary_custom, "
                "summary_generated, summary_updated_utc, last_activity_utc, is_pinned, "
                "created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                params,
            )
            _sync_fts(conn, project)
        return project

    def get(self, project_id: str) -> Project | None:
        """Return a project by UUIDv7 identifier, or ``None`` if not found."""
        with self._db.connection() as conn:
            row = conn.execute(f"SELECT {_SELECT_COLS} FROM projects WHERE id = ?;", (project_id,)).fetchone()
        return _row_to_project(row) if row is not None else None

    def get_by_abs_path(self, abs_path: str) -> Project | None:
        """Look up a project by normalized absolute path."""
        cmp = "LOWER(abs_path) = LOWER(?)" if sys.platform == "win32" else "abs_path = ?"
        with self._db.connection() as conn:
            row = conn.execute(f"SELECT {_SELECT_COLS} FROM projects WHERE {cmp};", (abs_path,)).fetchone()
        return _row_to_project(row) if row is not None else None

    def get_by_workspace_rel_path(self, workspace_id: str, rel_path: str) -> Project | None:
        """Look up a project inside a workspace by POSIX relative path."""
        norm = _normalize_rel(rel_path)
        cmp = "LOWER(rel_path) = LOWER(?)" if sys.platform == "win32" else "rel_path = ?"
        with self._db.connection() as conn:
            row = conn.execute(
                f"SELECT {_SELECT_COLS} FROM projects WHERE workspace_id = ? AND {cmp};",
                (workspace_id, norm),
            ).fetchone()
        return _row_to_project(row) if row is not None else None

    def list_all(self, *, workspace_id: str | None = None, status: ProjectStatus | None = None) -> list[Project]:
        """Return registered projects ordered by latest activity and creation time."""
        clauses, params = [], []
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status is not None:
            if status not in _VALID_STATUSES:
                raise ValueError(f"Invalid project status filter: {status!r}")
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        with self._db.connection() as conn:
            rows = conn.execute(f"SELECT {_SELECT_COLS} FROM projects {where}{_ORDER_BY}", tuple(params)).fetchall()
        return [_row_to_project(row) for row in rows]

    def search(self, query: str) -> list[Project]:
        """Search all registered projects (ongoing and completed) by text."""
        trimmed = query.strip()
        if not trimmed:
            return self.list_all()
        pattern = f"%{_escape_like(trimmed)}%"
        sql = (
            f"SELECT {_SELECT_COLS} FROM projects "
            "WHERE LOWER(name) LIKE LOWER(?) ESCAPE '\\' OR LOWER(description) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(rel_path) LIKE LOWER(?) ESCAPE '\\' OR LOWER(abs_path) LIKE LOWER(?) ESCAPE '\\' "
            f"OR LOWER(status) LIKE LOWER(?) ESCAPE '\\' {_ORDER_BY}"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, (pattern,) * 5).fetchall()
        return [_row_to_project(row) for row in rows]

    def update_status(self, project_id: str, status: ProjectStatus) -> Project | None:
        """Persist an explicit user status change (``ongoing`` or ``completed``)."""
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid project status: {status!r}")
        now = utc_now_iso()
        with self._db.connection() as conn:
            cur = conn.execute("UPDATE projects SET status = ?, updated_at_utc = ? WHERE id = ?;", (status, now, project_id))
            if cur.rowcount == 0:
                return None
        return self.get(project_id)

    def set_pinned(self, project_id: str, is_pinned: bool) -> None:
        """Persist the user pin state for ``project_id``."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE projects SET is_pinned = ?, updated_at_utc = ? WHERE id = ?;",
                (int(is_pinned), now, project_id),
            )

    def set_cover_image(self, project_id: str, cover_filename: str | None) -> Project | None:
        """Persist or clear ``cover_image_path`` for ``project_id`` and return updated project."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            cur = conn.execute(
                "UPDATE projects SET cover_image_path = ?, updated_at_utc = ? WHERE id = ?;",
                (cover_filename, now, project_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get(project_id)

    def update_details(
        self, project_id: str, *, name: str | None = None, description: str | None = None, cover_style: CoverStyle | None = None,
    ) -> Project | None:
        """Update editable project details and keep FTS5 search metadata in sync."""
        existing = self.get(project_id)
        if existing is None:
            return None
        next_name = name.strip() if name is not None else existing.name
        if not next_name:
            raise ValueError("Project name cannot be empty.")
        next_desc = description.strip() if description is not None else existing.description
        next_cover = cover_style if cover_style is not None else existing.cover_style
        if next_cover not in _VALID_COVERS:
            raise ValueError(f"Invalid cover style: {next_cover!r}")
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE projects SET name = ?, description = ?, cover_style = ?, updated_at_utc = ? WHERE id = ?;",
                (next_name, next_desc, next_cover, now, project_id),
            )
            updated = Project(
                id=existing.id, workspace_id=existing.workspace_id, name=next_name, rel_path=existing.rel_path,
                description=next_desc, status=existing.status, cover_style=next_cover,
                cover_image_path=existing.cover_image_path,
                root_rel_path=existing.root_rel_path, abs_path=existing.abs_path,
                last_known_state=existing.last_known_state,
                summary_custom=existing.summary_custom,
                summary_generated=existing.summary_generated,
                summary_updated_utc=existing.summary_updated_utc,
                last_activity_utc=existing.last_activity_utc,
                is_pinned=existing.is_pinned,
                created_at_utc=existing.created_at_utc, updated_at_utc=now,
            )
            _sync_fts(conn, updated)
        return updated

    def update_summary(
        self,
        project_id: str,
        custom_text: str | None,
        generated_text: str | None,
        updated_utc: str,
    ) -> None:
        """Persist custom and/or generated summary fields for ``project_id``."""
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE projects SET summary_custom = ?, summary_generated = ?, "
                "summary_updated_utc = ?, updated_at_utc = ? WHERE id = ?;",
                (custom_text, generated_text, updated_utc, updated_utc, project_id),
            )

    def update_last_activity(self, project_id: str, occurred_at_utc: str) -> Project | None:
        """Advance ``last_activity_utc`` if ``occurred_at_utc`` is newer than recorded."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE projects SET last_activity_utc = ?, updated_at_utc = ? "
                "WHERE id = ? AND (last_activity_utc IS NULL OR last_activity_utc < ?);",
                (occurred_at_utc, now, project_id, occurred_at_utc),
            )
        return self.get(project_id)

    def update_location(
        self,
        project_id: str,
        *,
        abs_path: str,
        rel_path: str | None = None,
        workspace_id: str | None = None,
    ) -> Project | None:
        """Update stored project folder location and keep FTS5 metadata in sync."""
        existing = self.get(project_id)
        if existing is None:
            return None
        next_rel = _normalize_rel(rel_path) if rel_path is not None else existing.rel_path
        next_root_rel = next_rel if rel_path is not None else existing.root_rel_path
        next_ws = workspace_id if workspace_id is not None else existing.workspace_id
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE projects SET workspace_id = ?, rel_path = ?, root_rel_path = ?, "
                "abs_path = ?, updated_at_utc = ? WHERE id = ?;",
                (next_ws, next_rel, next_root_rel, abs_path, now, project_id),
            )
            updated = Project(
                id=existing.id, workspace_id=next_ws, name=existing.name, rel_path=next_rel,
                description=existing.description, status=existing.status, cover_style=existing.cover_style,
                cover_image_path=existing.cover_image_path,
                root_rel_path=next_root_rel, abs_path=abs_path,
                last_known_state=existing.last_known_state,
                summary_custom=existing.summary_custom, summary_generated=existing.summary_generated,
                summary_updated_utc=existing.summary_updated_utc,
                last_activity_utc=existing.last_activity_utc, is_pinned=existing.is_pinned,
                created_at_utc=existing.created_at_utc, updated_at_utc=now,
            )
            _sync_fts(conn, updated)
        return updated

    def delete(self, project_id: str) -> bool:
        """Delete a registered project record without touching any disk files."""
        with self._db.connection() as conn:
            conn.execute("DELETE FROM fts_search WHERE entity_type = 'project' AND entity_id = ?;", (project_id,))
            return conn.execute("DELETE FROM projects WHERE id = ?;", (project_id,)).rowcount > 0

    def dismiss_suggestion(
        self, workspace_id: str, rel_path: str, dismissed_at_utc: str | None = None
    ) -> DismissedSuggestion:
        """Persist a dismissed project discovery suggestion so it stays hidden."""
        norm, ts = _normalize_rel(rel_path), dismissed_at_utc or utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO dismissed_suggestions (workspace_id, rel_path, dismissed_at_utc) VALUES (?, ?, ?) "
                "ON CONFLICT(workspace_id, rel_path) DO UPDATE SET dismissed_at_utc = excluded.dismissed_at_utc;",
                (workspace_id, norm, ts),
            )
        return DismissedSuggestion(workspace_id=workspace_id, rel_path=norm, dismissed_at_utc=ts)

    def list_dismissed(self, workspace_id: str | None = None) -> list[DismissedSuggestion]:
        """Return dismissed discovery suggestions, optionally scoped to one workspace."""
        if workspace_id is not None:
            sql = "SELECT workspace_id, rel_path, dismissed_at_utc FROM dismissed_suggestions WHERE workspace_id = ? ORDER BY dismissed_at_utc DESC, rel_path ASC;"
            params: tuple[object, ...] = (workspace_id,)
        else:
            sql = "SELECT workspace_id, rel_path, dismissed_at_utc FROM dismissed_suggestions ORDER BY dismissed_at_utc DESC, workspace_id ASC, rel_path ASC;"
            params = ()
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [DismissedSuggestion(str(r["workspace_id"]), str(r["rel_path"]), str(r["dismissed_at_utc"])) for r in rows]
