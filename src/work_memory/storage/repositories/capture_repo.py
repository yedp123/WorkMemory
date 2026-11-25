"""SQLite repository for capture entries, attachments, and FTS5 note indexing."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import cast

from work_memory.core.ids import utc_now_iso
from work_memory.core.models import Attachment, AttachmentKind, AudioRetention, CaptureEntry
from work_memory.storage.database import Database

CAPTURE_COLS = (
    "id, project_id, rel_path, note_text, transcript_text, transcription, "
    "audio_retention, is_milestone, captured_at_utc, created_at_utc, updated_at_utc"
)
_ATTACHMENT_COLS = (
    "id, capture_entry_id, original_attachment_id, kind, stored_rel_path, "
    "mime_type, byte_size, sha256, created_at_utc"
)


def row_to_capture(row: sqlite3.Row) -> CaptureEntry:
    """Convert a SQLite row into a ``CaptureEntry`` domain model."""
    ret_raw = row["audio_retention"]
    ret_str = str(ret_raw) if ret_raw is not None else "both"
    if ret_str == "text_only":
        ret_str = "text"
    elif ret_str == "audio_only":
        ret_str = "audio"
    transcript_raw = str(row["transcript_text"] or "")
    transcription_col = row["transcription"]
    transcription = (
        str(transcription_col)
        if transcription_col is not None
        else (transcript_raw or None)
    )
    return CaptureEntry(
        id=str(row["id"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        rel_path=str(row["rel_path"]) if row["rel_path"] is not None else None,
        note_text=str(row["note_text"] or ""),
        transcript_text=transcript_raw or (transcription or ""),
        transcription=transcription,
        audio_retention=cast(AudioRetention, ret_str),
        is_milestone=bool(row["is_milestone"]),
        captured_at_utc=str(row["captured_at_utc"]),
        created_at_utc=str(row["created_at_utc"]),
        updated_at_utc=str(row["updated_at_utc"]),
    )


def row_to_attachment(row: sqlite3.Row) -> Attachment:
    """Convert a SQLite row into an ``Attachment`` domain model."""
    return Attachment(
        id=str(row["id"]),
        capture_entry_id=str(row["capture_entry_id"]),
        original_attachment_id=(
            str(row["original_attachment_id"])
            if row["original_attachment_id"] is not None
            else None
        ),
        kind=cast(AttachmentKind, str(row["kind"])),
        stored_rel_path=str(row["stored_rel_path"]),
        mime_type=str(row["mime_type"] or ""),
        byte_size=int(row["byte_size"] or 0),
        sha256=str(row["sha256"] or ""),
        created_at_utc=str(row["created_at_utc"]),
    )


def _sync_capture_fts(conn: sqlite3.Connection, entry: CaptureEntry) -> None:
    conn.execute(
        "DELETE FROM fts_search WHERE entity_type = 'capture' AND entity_id = ?;",
        (entry.id,),
    )
    title = PurePosixPath(entry.rel_path).name if entry.rel_path else "Note"
    spoken = entry.transcription or entry.transcript_text or ""
    body = f"{entry.note_text} {spoken}".strip()
    conn.execute(
        "INSERT INTO fts_search (entity_type, entity_id, project_id, title, body, rel_path) "
        "VALUES (?, ?, ?, ?, ?, ?);",
        ("capture", entry.id, entry.project_id or "", title, body, entry.rel_path or ""),
    )


class CaptureRepository:
    """Data-access layer for ``capture_entries``, ``attachments``, and FTS5 sync."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, entry: CaptureEntry, attachments: Sequence[Attachment] = (), *, is_milestone: bool | None = None
    ) -> CaptureEntry:
        """Persist a capture entry, its attachments, and FTS5 search entry atomically."""
        if is_milestone is not None:
            entry.is_milestone = is_milestone
        with self._db.connection() as conn:
            conn.execute(
                f"INSERT INTO capture_entries ({CAPTURE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    entry.id,
                    entry.project_id,
                    entry.rel_path,
                    entry.note_text,
                    entry.transcript_text,
                    entry.transcription,
                    entry.audio_retention,
                    int(entry.is_milestone),
                    entry.captured_at_utc,
                    entry.created_at_utc,
                    entry.updated_at_utc,
                ),
            )
            if attachments:
                conn.executemany(
                    f"INSERT INTO attachments ({_ATTACHMENT_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    [
                        (
                            att.id,
                            entry.id,
                            att.original_attachment_id,
                            att.kind,
                            att.stored_rel_path,
                            att.mime_type,
                            att.byte_size,
                            att.sha256,
                            att.created_at_utc,
                        )
                        for att in attachments
                    ],
                )
            _sync_capture_fts(conn, entry)
        return entry

    def get(self, capture_id: str) -> CaptureEntry | None:
        """Return a single capture entry by ID, or ``None`` if not found."""
        with self._db.connection() as conn:
            row = conn.execute(
                f"SELECT {CAPTURE_COLS} FROM capture_entries WHERE id = ?;",
                (capture_id,),
            ).fetchone()
        return row_to_capture(row) if row is not None else None

    def list_attachments(self, capture_id: str) -> list[Attachment]:
        """Return all attachments associated with ``capture_id``."""
        with self._db.connection() as conn:
            rows = conn.execute(
                f"SELECT {_ATTACHMENT_COLS} FROM attachments "
                "WHERE capture_entry_id = ? ORDER BY created_at_utc ASC, id ASC;",
                (capture_id,),
            ).fetchall()
        return [row_to_attachment(row) for row in rows]

    def list_attachments_for_entries(
        self, capture_ids: Sequence[str]
    ) -> dict[str, tuple[Attachment, ...]]:
        """Batch-load attachments for multiple capture entries in one query."""
        if not capture_ids:
            return {}
        placeholders = ", ".join("?" for _ in capture_ids)
        sql = (
            f"SELECT {_ATTACHMENT_COLS} FROM attachments "
            f"WHERE capture_entry_id IN ({placeholders}) ORDER BY created_at_utc ASC, id ASC;"
        )
        grouped: dict[str, list[Attachment]] = defaultdict(list)
        with self._db.connection() as conn:
            rows = conn.execute(sql, tuple(capture_ids)).fetchall()
        for row in rows:
            att = row_to_attachment(row)
            grouped[att.capture_entry_id].append(att)
        return {cid: tuple(items) for cid, items in grouped.items()}

    def update_note(
        self, capture_id: str, note_text: str, rel_path: str | None = None
    ) -> CaptureEntry | None:
        """Update a capture entry's note text and optional linked file, syncing FTS5."""
        existing = self.get(capture_id)
        if existing is None:
            return None
        now = utc_now_iso()
        next_rel = rel_path if rel_path is not None else existing.rel_path
        updated = CaptureEntry(
            id=existing.id,
            project_id=existing.project_id,
            rel_path=next_rel,
            note_text=note_text.strip(),
            transcript_text=existing.transcript_text,
            audio_retention=existing.audio_retention,
            is_milestone=existing.is_milestone,
            captured_at_utc=existing.captured_at_utc,
            created_at_utc=existing.created_at_utc,
            updated_at_utc=now,
        )
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE capture_entries SET note_text = ?, rel_path = ?, updated_at_utc = ? WHERE id = ?;",
                (updated.note_text, updated.rel_path, now, capture_id),
            )
            _sync_capture_fts(conn, updated)
        return updated

    def delete(self, capture_id: str) -> bool:
        """Delete a capture entry (and cascaded attachment rows) plus FTS5 index."""
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM fts_search WHERE entity_type = 'capture' AND entity_id = ?;",
                (capture_id,),
            )
            return conn.execute("DELETE FROM capture_entries WHERE id = ?;", (capture_id,)).rowcount > 0

    def list_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None, limit: int = 500
    ) -> list[CaptureEntry]:
        """Query ``capture_entries`` inside ``[start_utc, end_utc)`` newest-first."""
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, start_utc, end_utc, limit)
            if project_id is not None
            else (start_utc, end_utc, limit)
        )
        sql = (
            f"SELECT {CAPTURE_COLS} FROM capture_entries "
            f"WHERE {prefix}captured_at_utc >= ? AND captured_at_utc < ? "
            "ORDER BY captured_at_utc DESC, id DESC LIMIT ?;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row_to_capture(row) for row in rows]

    def list_timestamps_in_utc_range(
        self, start_utc: str, end_utc: str, *, project_id: str | None = None
    ) -> list[str]:
        """Return distinct UTC capture timestamps inside ``[start_utc, end_utc)``."""
        prefix = "project_id = ? AND " if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, start_utc, end_utc) if project_id is not None else (start_utc, end_utc)
        )
        sql = (
            f"SELECT DISTINCT captured_at_utc AS ts FROM capture_entries "
            f"WHERE {prefix}captured_at_utc >= ? AND captured_at_utc < ?;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [str(row["ts"]) for row in rows]

    def list_recent(
        self, *, project_id: str | None = None, limit: int = 50
    ) -> list[CaptureEntry]:
        """Return recent ``capture_entries`` ordered newest-first."""
        where = "WHERE project_id = ? " if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit) if project_id is not None else (limit,)
        sql = (
            f"SELECT {CAPTURE_COLS} FROM capture_entries "
            f"{where}ORDER BY captured_at_utc DESC, id DESC LIMIT ?;"
        )
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row_to_capture(row) for row in rows]

    def set_milestone(self, capture_id: str, is_milestone: bool) -> None:
        """Mark or unmark a capture entry as a project milestone."""
        now = utc_now_iso()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE capture_entries SET is_milestone = ?, updated_at_utc = ? WHERE id = ?;",
                (int(is_milestone), now, capture_id),
            )

    def list_milestones(self, project_id: str) -> list[CaptureEntry]:
        """Return all milestone-starred capture entries for ``project_id`` newest-first."""
        sql = f"SELECT {CAPTURE_COLS} FROM capture_entries WHERE project_id = ? AND is_milestone = 1 ORDER BY captured_at_utc DESC, id DESC;"
        with self._db.connection() as conn:
            rows = conn.execute(sql, (project_id,)).fetchall()
        return [row_to_capture(row) for row in rows]
