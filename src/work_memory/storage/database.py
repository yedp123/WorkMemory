"""SQLite connection management and idempotent ordered SQL migrations."""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from work_memory.core.ids import utc_now_iso

logger = logging.getLogger(__name__)


def resolve_migrations_dir() -> Path:
    """Resolve the ``migrations`` directory in both dev and frozen PyInstaller builds."""
    if getattr(sys, "frozen", False) and (meipass := getattr(sys, "_MEIPASS", None)):
        bundled = Path(meipass) / "work_memory" / "storage" / "migrations"
        if bundled.is_dir():
            return bundled
    return Path(__file__).resolve().parent / "migrations"


_MIGRATIONS_DIR = resolve_migrations_dir()


class Database:
    """Manages SQLite connections (WAL, FK, busy timeout) and schema migrations."""

    def __init__(self, db_path: Path, migrations_dir: Path | None = None) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir or resolve_migrations_dir()

    @property
    def db_path(self) -> Path:
        """Return the path to the SQLite database file."""
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection configured with mandatory WAL and safety pragmas."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager yielding a configured connection that commits or rolls back."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            logger.exception("Database operation failed; rolling back transaction.")
            conn.rollback()
            raise
        finally:
            conn.close()

    def run_migrations(self) -> list[str]:
        """Apply unapplied *.sql migrations in sorted order and return applied versions."""
        applied_now: list[str] = []
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                );
                """
            )
            rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()
            already_applied = {str(row["version"]) for row in rows}

            migration_files = sorted(self._migrations_dir.glob("*.sql"))
            for migration_file in migration_files:
                version = migration_file.stem
                if version in already_applied:
                    continue

                sql = migration_file.read_text(encoding="utf-8")
                logger.info("Applying database migration: %s", version)
                # Ensure pending schema_migrations DDL is committed before executescript.
                conn.commit()
                conn.executescript(f"BEGIN;\n{sql}\nCOMMIT;")
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at_utc) VALUES (?, ?);",
                    (version, utc_now_iso()),
                )
                conn.commit()
                applied_now.append(version)

        return applied_now
