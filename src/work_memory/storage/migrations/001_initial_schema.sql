-- Initial Work Memory SQLite schema (WAL + FTS5 + UUIDv7 keys)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ongoing' CHECK (status IN ('ongoing', 'completed')),
    last_known_state TEXT NOT NULL DEFAULT '',
    last_activity_utc TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE (workspace_id, rel_path)
);

-- Observed Material: strictly separate from user captures and planned events.
CREATE TABLE IF NOT EXISTS observed_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    rel_path TEXT NOT NULL,
    old_rel_path TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('created', 'modified', 'renamed', 'moved', 'deleted')),
    file_size INTEGER,
    is_baseline INTEGER NOT NULL DEFAULT 0 CHECK (is_baseline IN (0, 1)),
    group_key TEXT,
    occurred_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

-- Captured Material: user-authored notes, transcripts, and app-owned attachments.
CREATE TABLE IF NOT EXISTS capture_entries (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    rel_path TEXT,
    note_text TEXT NOT NULL DEFAULT '',
    transcript_text TEXT NOT NULL DEFAULT '',
    audio_retention TEXT CHECK (
        audio_retention IS NULL OR audio_retention IN ('both', 'text_only', 'audio_only')
    ),
    captured_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    capture_entry_id TEXT NOT NULL REFERENCES capture_entries(id) ON DELETE CASCADE,
    original_attachment_id TEXT REFERENCES attachments(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('screenshot', 'annotated_screenshot', 'audio', 'image')),
    stored_rel_path TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT '',
    byte_size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    created_at_utc TEXT NOT NULL
);

-- Planned Material: scheduled events and reminders (distinct from observed activity).
CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    starts_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    remind_at_utc TEXT,
    notified_at_utc TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_workspace
    ON projects (workspace_id);

CREATE INDEX IF NOT EXISTS idx_observed_events_ws_time
    ON observed_events (workspace_id, occurred_at_utc);

CREATE INDEX IF NOT EXISTS idx_observed_events_proj_time
    ON observed_events (project_id, occurred_at_utc);

CREATE INDEX IF NOT EXISTS idx_capture_entries_proj_time
    ON capture_entries (project_id, captured_at_utc);

CREATE INDEX IF NOT EXISTS idx_attachments_capture
    ON attachments (capture_entry_id);

CREATE INDEX IF NOT EXISTS idx_calendar_events_starts
    ON calendar_events (starts_at_utc);

CREATE INDEX IF NOT EXISTS idx_calendar_events_remind
    ON calendar_events (remind_at_utc, notified_at_utc);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_search USING fts5(
    entity_type UNINDEXED,
    entity_id UNINDEXED,
    project_id UNINDEXED,
    title,
    body,
    rel_path,
    tokenize = 'unicode61'
);
