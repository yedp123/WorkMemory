"""Unit tests for SQLite database pragmas, migrations, FTS5, and UUIDv7 models."""

from __future__ import annotations

import dataclasses
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from work_memory.core.ids import new_id, utc_now_iso
from work_memory.core.models import (
    Attachment,
    CalendarEvent,
    CaptureEntry,
    ObservedEvent,
    Project,
    Workspace,
)
from work_memory.storage.database import Database


def test_uuidv7_monotonic_ordering_and_utc_format() -> None:
    ids = [new_id() for _ in range(250)]

    assert len(set(ids)) == 250
    assert ids == sorted(ids)
    for item in ids:
        parsed = uuid.UUID(item)
        assert parsed.version == 7
        assert parsed.variant == uuid.RFC_4122

    timestamp = utc_now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp) is not None


def test_database_pragmas_and_wal_mode(tmp_path: Path) -> None:
    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()

    with db.connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1
    assert foreign_keys == 1
    assert busy_timeout == 5000


def test_idempotent_migrations_schema_and_fts5(tmp_path: Path) -> None:
    db = Database(tmp_path / "work_memory.db")

    first_applied = db.run_migrations()
    second_applied = db.run_migrations()

    assert first_applied == [
        "001_initial_schema",
        "002_file_baseline",
        "003_project_discovery",
        "004_pins_and_milestones",
        "005_audio_transcription",
        "006_calendar_events",
        "007_project_summaries",
        "008_project_cover_path",
    ]
    assert second_applied == []

    with db.connection() as conn:
        tables = {
            row["name"]: row["sql"]
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table';"
            ).fetchall()
        }
        migration_rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()

        expected_tables = {
            "schema_migrations",
            "workspaces",
            "projects",
            "dismissed_suggestions",
            "observed_events",
            "file_baseline",
            "capture_entries",
            "attachments",
            "calendar_events",
            "fts_search",
        }
        assert expected_tables.issubset(tables.keys())
        assert "AUTOINCREMENT" not in " ".join(
            sql or "" for sql in tables.values()
        ).upper()
        assert "fts5" in (tables["fts_search"] or "").lower()
        assert [row["version"] for row in migration_rows] == [
            "001_initial_schema",
            "002_file_baseline",
            "003_project_discovery",
            "004_pins_and_milestones",
            "005_audio_transcription",
            "006_calendar_events",
            "007_project_summaries",
            "008_project_cover_path",
        ]
        workspace_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(workspaces);").fetchall()
        }
        assert "last_scan_utc" in workspace_cols
        project_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(projects);").fetchall()
        }
        assert {"cover_style", "root_rel_path", "abs_path"}.issubset(project_cols)

        conn.execute(
            """
            INSERT INTO fts_search (entity_type, entity_id, project_id, title, body, rel_path)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            ("capture", new_id(), new_id(), "Rigging Note", "IK solver tuning", "rig/arm.blend"),
        )
        hits = conn.execute(
            "SELECT title, rel_path FROM fts_search WHERE fts_search MATCH ?;",
            ("solver",),
        ).fetchall()

    assert len(hits) == 1
    assert hits[0]["title"] == "Rigging Note"
    assert hits[0]["rel_path"] == "rig/arm.blend"


def _insert_record(conn: sqlite3.Connection, table: str, record: object) -> None:
    data = dataclasses.asdict(record)  # type: ignore[arg-type]
    for key, value in list(data.items()):
        if isinstance(value, bool):
            data[key] = int(value)
    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders});",
        tuple(data.values()),
    )


def test_separate_domain_tables_and_model_validation(tmp_path: Path) -> None:
    db = Database(tmp_path / "work_memory.db")
    db.run_migrations()

    ws = Workspace(name="Studio", root_path=str(tmp_path / "studio"))
    proj = Project(workspace_id=ws.id, name="Alpha", rel_path="Alpha")
    obs = ObservedEvent(
        workspace_id=ws.id,
        project_id=proj.id,
        rel_path="Alpha/scenes/main.blend",
        event_type="modified",
        occurred_at_utc=utc_now_iso(),
    )
    cap = CaptureEntry(
        project_id=proj.id,
        rel_path="Alpha/scenes/main.blend",
        note_text="Saved before lighting pass.",
    )
    att = Attachment(
        capture_entry_id=cap.id,
        kind="screenshot",
        stored_rel_path="2026/11/shot.png",
        mime_type="image/png",
        byte_size=128,
    )
    cal = CalendarEvent(
        project_id=proj.id,
        title="Client review",
        starts_at_utc="2026-11-24T15:00:00Z",
        remind_at_utc="2026-11-24T14:50:00Z",
        notified_at_utc=None,
    )

    with db.connection() as conn:
        for table, record in (
            ("workspaces", ws),
            ("projects", proj),
            ("observed_events", obs),
            ("capture_entries", cap),
            ("attachments", att),
            ("calendar_events", cal),
        ):
            _insert_record(conn, table, record)

        assert conn.execute("SELECT COUNT(*) FROM observed_events;").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM capture_entries;").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM calendar_events;").fetchone()[0] == 1
        cal_row = conn.execute(
            "SELECT remind_at_utc, notified_at_utc FROM calendar_events WHERE id = ?;",
            (cal.id,),
        ).fetchone()
        assert cal_row["remind_at_utc"] == "2026-11-24T14:50:00Z"
        assert cal_row["notified_at_utc"] is None

    with pytest.raises(ValueError):
        Project(workspace_id=ws.id, name="Bad", rel_path="Bad", status="archived")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        CalendarEvent(title="Bad", starts_at_utc=utc_now_iso(), status="done")  # type: ignore[arg-type]


def test_frozen_resource_resolution_for_migrations_and_bundled_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from work_memory.media.transcribe_worker import resolve_local_model_dir
    from work_memory.storage.database import resolve_migrations_dir

    # Dev mode resolves migrations inside the package directory
    dev_dir = resolve_migrations_dir()
    assert dev_dir.is_dir() and any(dev_dir.glob("*.sql"))

    # Frozen mode resolves migrations and bundled models inside sys._MEIPASS
    meipass = tmp_path / "_internal"
    frozen_mig = meipass / "work_memory" / "storage" / "migrations"
    frozen_mig.mkdir(parents=True)
    bundled_model = meipass / "models" / "base"
    bundled_model.mkdir(parents=True)
    for fname in ("model.bin", "config.json", "vocabulary.txt"):
        (bundled_model / fname).write_bytes(b"ok")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert resolve_migrations_dir() == frozen_mig
    assert resolve_local_model_dir(tmp_path / "empty_user_models") == bundled_model
