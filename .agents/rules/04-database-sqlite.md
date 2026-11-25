---
trigger: glob
globs: "src/work_memory/storage/**, src/work_memory/core/models.py"
description: SQLite WAL mode, FTS5 search, UUIDv7 keys, strict domain separation, and migrations.
---
# SQLite Storage & Data Model Rules

## Connection Pragmas (Mandatory on Every Connection)
- `PRAGMA journal_mode = WAL;`
- `PRAGMA synchronous = NORMAL;`
- `PRAGMA foreign_keys = ON;`
- `PRAGMA busy_timeout = 5000;`

## Primary Keys & Cross-Machine Portability
- NEVER use `INTEGER PRIMARY KEY AUTOINCREMENT` for domain records (`workspaces`, `projects`, `observed_events`, `capture_entries`, `attachments`, `calendar_events`).
- Generate time-ordered unique text IDs (`UUIDv7` via `core/ids.py`) so records merge without ID collisions during portable manifest import.
- Store all timestamps in ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ`).
- Store file paths inside project records as POSIX relative paths (`rel_path`, using `/`) alongside `workspace_id` / `project_id`.

## Strict Domain Separation
- Keep **Observed Material** (`observed_events`), **Captured Material** (`capture_entries` + `attachments`), and **Planned Material** (`calendar_events`) in separate tables.
- Unify them ONLY at query/presentation time inside `services/history_service.py`.
- Calendar reminders MUST store `remind_at_utc` and `notified_at_utc` so sleep/hibernate wake-up recovery never misses or duplicates alerts.

## Schema & Migrations
- Maintain ordered SQL migration files in `src/work_memory/storage/migrations/` tracked via `schema_migrations`.
- Include an SQLite **FTS5** virtual table (`fts_search`) from migration `001`.
- Always use parameterized SQL queries (`?`).