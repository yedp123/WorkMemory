"""SQLite repository for unified FTS5 + LIKE search and capture/calendar range queries."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import TypeVar

from work_memory.core.models import (
    CalendarEvent,
    CaptureEntry,
    SearchResults,
)
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CALENDAR_COLS, row_to_calendar_event
from work_memory.storage.repositories.capture_repo import CAPTURE_COLS, row_to_capture
from work_memory.storage.repositories.observed_event_repo import EVENT_SELECT_COLS, row_to_event
from work_memory.storage.repositories.project_repo import (
    PROJECT_SELECT_COLS,
    escape_like,
    row_to_project,
)

_T = TypeVar("_T")
_CAPTURE_COLS = CAPTURE_COLS
_row_to_capture = row_to_capture
_CALENDAR_COLS = CALENDAR_COLS
_row_to_calendar_event = row_to_calendar_event
_TOKEN_RE = re.compile(r"[^\W_]+")


def build_fts_query(raw_query: str) -> str:
    """Convert raw user text into a safe FTS5 MATCH expression without syntax errors."""
    tokens = _TOKEN_RE.findall(raw_query)
    return " ".join(f'"{token}"*' for token in tokens[:24]) if tokens else ""


class SearchRepository:
    """Data-access layer for FTS5 search and domain-separated capture/calendar queries."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_captures_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None, limit: int = 500
    ) -> list[CaptureEntry]:
        """Query ``capture_entries`` inside ``[start_utc, end_utc)`` newest-first."""
        return self._query_range(
            "capture_entries", _CAPTURE_COLS, "captured_at_utc", start_utc, end_utc,
            _row_to_capture, project_id=project_id, order_dir="DESC", limit=limit,
        )

    def list_capture_timestamps_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None
    ) -> list[str]:
        """Return distinct UTC capture timestamps inside ``[start_utc, end_utc)``."""
        return self._query_timestamps("capture_entries", "captured_at_utc", start_utc, end_utc, project_id)

    def list_recent_captures(self, *, project_id: str | None = None, limit: int = 50) -> list[CaptureEntry]:
        """Return recent ``capture_entries`` ordered newest-first."""
        return self._query_recent(
            "capture_entries", _CAPTURE_COLS, "captured_at_utc", _row_to_capture, project_id=project_id, limit=limit
        )

    def list_calendar_events_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None, limit: int = 500
    ) -> list[CalendarEvent]:
        """Query ``calendar_events`` inside ``[start_utc, end_utc)`` ordered by start time."""
        return self._query_range(
            "calendar_events", _CALENDAR_COLS, "starts_at_utc", start_utc, end_utc,
            _row_to_calendar_event, project_id=project_id, order_dir="ASC", limit=limit,
        )

    def list_calendar_timestamps_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None
    ) -> list[str]:
        """Return distinct UTC event start timestamps inside ``[start_utc, end_utc)``."""
        return self._query_timestamps("calendar_events", "starts_at_utc", start_utc, end_utc, project_id)

    def list_recent_calendar_events(self, *, project_id: str | None = None, limit: int = 50) -> list[CalendarEvent]:
        """Return recent or upcoming ``calendar_events`` ordered newest-first."""
        return self._query_recent(
            "calendar_events", _CALENDAR_COLS, "starts_at_utc", _row_to_calendar_event, project_id=project_id, limit=limit
        )

    def search_all(
        self, query: str, *, project_id: str | None = None, limit: int = 50
    ) -> SearchResults:
        """Search FTS5 plus parameterized LIKE on projects, files, captures, and events."""
        trimmed = query.strip()
        if not trimmed:
            return SearchResults(query="")
        raw_pat = f"%{escape_like(trimmed)}%"
        posix_pat = f"%{escape_like(trimmed.replace(chr(92), '/'))}%"
        fts_expr = build_fts_query(trimmed)

        with self._db.connection() as conn:
            fts_ids = self._query_fts(conn, fts_expr, project_id=project_id, limit=limit)
            projects = self._search_table(
                conn, "projects", PROJECT_SELECT_COLS,
                (("name", raw_pat), ("description", raw_pat), ("rel_path", posix_pat), ("abs_path", raw_pat), ("last_known_state", raw_pat), ("status", raw_pat)),
                fts_ids["project"], row_to_project, project_col="id", project_id=project_id,
                order_by="COALESCE(last_activity_utc, created_at_utc) DESC, id DESC", limit=limit,
            )
            observed = self._search_table(
                conn, "observed_events", EVENT_SELECT_COLS,
                (("rel_path", raw_pat), ("rel_path", posix_pat), ("COALESCE(old_rel_path, '')", posix_pat)),
                fts_ids["observed"], row_to_event, extra_filter="is_baseline = 0", project_id=project_id,
                order_by="occurred_at_utc DESC, id DESC", limit=limit,
            )
            captures = self._search_table(
                conn, "capture_entries", _CAPTURE_COLS,
                (("note_text", raw_pat), ("transcript_text", raw_pat), ("COALESCE(transcription, '')", raw_pat), ("COALESCE(rel_path, '')", posix_pat)),
                fts_ids["capture"], _row_to_capture, project_id=project_id,
                order_by="captured_at_utc DESC, id DESC", limit=limit,
            )
            events = self._search_table(
                conn, "calendar_events", _CALENDAR_COLS,
                (("title", raw_pat), ("description", raw_pat)),
                fts_ids["calendar"] + fts_ids["event"], _row_to_calendar_event, project_id=project_id,
                order_by="starts_at_utc DESC, id DESC", limit=limit,
            )

        return SearchResults(trimmed, tuple(projects), tuple(observed), tuple(captures), tuple(events))

    def _query_range(
        self, table: str, cols: str, time_col: str, start_utc: str, end_utc: str,
        mapper: Callable[[sqlite3.Row], _T], *, project_id: str | None, order_dir: str, limit: int,
    ) -> list[_T]:
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, start_utc, end_utc, limit) if project_id is not None else (start_utc, end_utc, limit)
        sql = f"SELECT {cols} FROM {table} WHERE {prefix}{time_col} >= ? AND {time_col} < ? ORDER BY {time_col} {order_dir}, id {order_dir} LIMIT ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [mapper(row) for row in rows]

    def _query_timestamps(
        self, table: str, time_col: str, start_utc: str, end_utc: str, project_id: str | None
    ) -> list[str]:
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, start_utc, end_utc) if project_id is not None else (start_utc, end_utc)
        sql = f"SELECT DISTINCT {time_col} AS ts FROM {table} WHERE {prefix}{time_col} >= ? AND {time_col} < ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [str(row["ts"]) for row in rows]

    def _query_recent(
        self, table: str, cols: str, time_col: str, mapper: Callable[[sqlite3.Row], _T],
        *, project_id: str | None, limit: int,
    ) -> list[_T]:
        where = "WHERE project_id = ? " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit) if project_id is not None else (limit,)
        sql = f"SELECT {cols} FROM {table} {where}ORDER BY {time_col} DESC, id DESC LIMIT ?;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [mapper(row) for row in rows]

    def _query_fts(
        self, conn: sqlite3.Connection, fts_expr: str, *, project_id: str | None, limit: int
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        if not fts_expr:
            return grouped
        if project_id is not None:
            sql = "SELECT entity_type, entity_id FROM fts_search WHERE fts_search MATCH ? AND project_id = ? ORDER BY bm25(fts_search) ASC LIMIT ?;"
            params: tuple[object, ...] = (fts_expr, project_id, limit)
        else:
            sql = "SELECT entity_type, entity_id FROM fts_search WHERE fts_search MATCH ? ORDER BY bm25(fts_search) ASC LIMIT ?;"
            params = (fts_expr, limit)
        for row in conn.execute(sql, params).fetchall():
            grouped[str(row["entity_type"])].append(str(row["entity_id"]))
        return grouped

    def _search_table(
        self, conn: sqlite3.Connection, table: str, select_cols: str, like_specs: Sequence[tuple[str, str]],
        fts_ids: Sequence[str], mapper: Callable[[sqlite3.Row], _T], *, project_id: str | None,
        order_by: str, limit: int, project_col: str = "project_id", extra_filter: str | None = None,
    ) -> list[_T]:
        clauses = [f"LOWER({expr}) LIKE LOWER(?) ESCAPE '\\'" for expr, _ in like_specs]
        params: list[object] = [pattern for _, pattern in like_specs]
        if fts_ids:
            clauses.append(f"id IN ({', '.join('?' for _ in fts_ids)})")
            params.extend(fts_ids)
        filters = [f"({' OR '.join(clauses)})"]
        if extra_filter:
            filters.insert(0, extra_filter)
        if project_id is not None:
            filters.insert(0, f"{project_col} = ?")
            params.insert(0, project_id)
        sql = f"SELECT {select_cols} FROM {table} WHERE {' AND '.join(filters)} ORDER BY {order_by} LIMIT ?;"
        return [mapper(row) for row in conn.execute(sql, (*params, limit)).fetchall()]
