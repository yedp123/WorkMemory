"""SQLite repository for calendar_events, due reminders, and FTS5 indexing."""

from __future__ import annotations

import sqlite3
from typing import cast

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import CalendarEvent, CalendarEventStatus
from work_memory.storage.database import Database

CALENDAR_COLS = (
    "id, project_id, title, description, starts_at_utc, event_at_utc, "
    "reminder_minutes, status, remind_at_utc, notified_at_utc, created_at_utc, updated_at_utc"
)


def row_to_calendar_event(row: sqlite3.Row) -> CalendarEvent:
    """Convert a SQLite row into a ``CalendarEvent`` domain model."""
    ev_at = str(row["event_at_utc"] or row["starts_at_utc"] or "")
    rem_min = row["reminder_minutes"]
    return CalendarEvent(
        id=str(row["id"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        title=str(row["title"]),
        description=str(row["description"] or ""),
        starts_at_utc=str(row["starts_at_utc"] or ev_at),
        event_at_utc=ev_at,
        reminder_minutes=int(rem_min) if rem_min is not None else None,
        status=cast(CalendarEventStatus, str(row["status"])),
        remind_at_utc=str(row["remind_at_utc"]) if row["remind_at_utc"] is not None else None,
        notified_at_utc=(
            str(row["notified_at_utc"]) if row["notified_at_utc"] is not None else None
        ),
        created_at_utc=str(row["created_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
    )


def _sync_calendar_fts(conn: sqlite3.Connection, event: CalendarEvent) -> None:
    conn.execute(
        "DELETE FROM fts_search WHERE entity_type = 'calendar' AND entity_id = ?;",
        (event.id,),
    )
    conn.execute(
        "INSERT INTO fts_search (entity_type, entity_id, project_id, title, body, rel_path) "
        "VALUES (?, ?, ?, ?, ?, ?);",
        ("calendar", event.id, event.project_id or "", event.title, event.description, ""),
    )


class CalendarRepo:
    """Data-access layer for ``calendar_events`` and due-reminder queries."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, event: CalendarEvent) -> CalendarEvent:
        """Persist a new calendar event and index it in FTS5."""
        with self._db.connection() as conn:
            conn.execute(
                f"INSERT INTO calendar_events ({CALENDAR_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    event.id,
                    event.project_id,
                    event.title,
                    event.description,
                    event.event_at_utc,
                    event.event_at_utc,
                    event.reminder_minutes,
                    event.status,
                    event.remind_at_utc,
                    event.notified_at_utc,
                    event.created_at_utc,
                    event.updated_at_utc,
                ),
            )
            _sync_calendar_fts(conn, event)
        return event

    def get_by_id(self, event_id: str) -> CalendarEvent | None:
        """Return a single calendar event by ID, or ``None`` if not found."""
        with self._db.connection() as conn:
            row = conn.execute(
                f"SELECT {CALENDAR_COLS} FROM calendar_events WHERE id = ?;",
                (event_id,),
            ).fetchone()
        return row_to_calendar_event(row) if row is not None else None

    def update(self, event: CalendarEvent) -> CalendarEvent:
        """Update an existing calendar event and re-index it in FTS5."""
        event.updated_at_utc = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE calendar_events SET project_id = ?, title = ?, description = ?, "
                "starts_at_utc = ?, event_at_utc = ?, reminder_minutes = ?, status = ?, "
                "remind_at_utc = ?, notified_at_utc = ?, updated_at_utc = ? WHERE id = ?;",
                (
                    event.project_id,
                    event.title,
                    event.description,
                    event.event_at_utc,
                    event.event_at_utc,
                    event.reminder_minutes,
                    event.status,
                    event.remind_at_utc,
                    event.notified_at_utc,
                    event.updated_at_utc,
                    event.id,
                ),
            )
            _sync_calendar_fts(conn, event)
        return event

    def update_status(self, event_id: str, status: str) -> CalendarEvent | None:
        """Explicitly update an event's status (``scheduled``, ``completed``, ``cancelled``)."""
        if status not in ("scheduled", "completed", "cancelled"):
            raise ValueError(f"Invalid calendar event status: {status!r}")
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE calendar_events SET status = ?, updated_at_utc = ? WHERE id = ?;",
                (status, now, event_id),
            )
        return self.get_by_id(event_id)

    def delete(self, event_id: str) -> bool:
        """Delete a calendar event and remove its FTS5 entry."""
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM fts_search WHERE entity_type = 'calendar' AND entity_id = ?;",
                (event_id,),
            )
            return conn.execute("DELETE FROM calendar_events WHERE id = ?;", (event_id,)).rowcount > 0

    def list_in_range(
        self, start_utc: str, end_utc: str, project_id: str | None = None
    ) -> list[CalendarEvent]:
        """Query calendar events inside ``[start_utc, end_utc)`` ordered by ``event_at_utc ASC``."""
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, start_utc, end_utc) if project_id is not None else (start_utc, end_utc)
        )
        sql = (
            f"SELECT {CALENDAR_COLS} FROM calendar_events "
            f"WHERE {prefix}COALESCE(event_at_utc, starts_at_utc) >= ? "
            "AND COALESCE(event_at_utc, starts_at_utc) < ? "
            "ORDER BY COALESCE(event_at_utc, starts_at_utc) ASC, id ASC;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row_to_calendar_event(row) for row in rows]

    def list_timestamps_in_range(
        self, start_utc: str, end_utc: str, project_id: str | None = None
    ) -> list[str]:
        """Return distinct UTC event timestamps inside ``[start_utc, end_utc)``."""
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, start_utc, end_utc) if project_id is not None else (start_utc, end_utc)
        )
        sql = (
            "SELECT DISTINCT COALESCE(event_at_utc, starts_at_utc) AS ts FROM calendar_events "
            f"WHERE {prefix}COALESCE(event_at_utc, starts_at_utc) >= ? "
            "AND COALESCE(event_at_utc, starts_at_utc) < ?;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [str(row["ts"]) for row in rows]

    def list_recent(self, *, project_id: str | None = None, limit: int = 50) -> list[CalendarEvent]:
        """Return recent or upcoming ``calendar_events`` ordered newest-first."""
        where = "WHERE project_id = ? " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit) if project_id is not None else (limit,)
        sql = (
            f"SELECT {CALENDAR_COLS} FROM calendar_events "
            f"{where}ORDER BY COALESCE(event_at_utc, starts_at_utc) DESC, id DESC LIMIT ?;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row_to_calendar_event(row) for row in rows]

    def list_due_reminders(self, now_utc: str) -> list[CalendarEvent]:
        """Return scheduled events whose reminder time has arrived and not yet notified."""
        sql = (
            f"SELECT {CALENDAR_COLS} FROM calendar_events "
            "WHERE status = 'scheduled' AND remind_at_utc IS NOT NULL "
            "AND remind_at_utc <= ? AND notified_at_utc IS NULL "
            "ORDER BY remind_at_utc ASC, id ASC;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, (now_utc,)).fetchall()
        return [row_to_calendar_event(row) for row in rows]

    def mark_notified(self, event_id: str, notified_at_utc: str) -> None:
        """Record that a reminder notification was emitted for ``event_id``."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE calendar_events SET notified_at_utc = ?, updated_at_utc = ? WHERE id = ?;",
                (notified_at_utc, now, event_id),
            )
