-- Phase 6: Audio recording & offline speech-to-text transcription

ALTER TABLE attachments RENAME TO _attachments_old;
ALTER TABLE capture_entries RENAME TO _capture_entries_old;

CREATE TABLE capture_entries (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    rel_path TEXT,
    note_text TEXT NOT NULL DEFAULT '',
    transcript_text TEXT NOT NULL DEFAULT '',
    transcription TEXT,
    audio_retention TEXT NOT NULL DEFAULT 'both' CHECK (
        audio_retention IN ('both', 'text', 'audio')
    ),
    is_milestone INTEGER NOT NULL DEFAULT 0,
    captured_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

INSERT INTO capture_entries (
    id, project_id, rel_path, note_text, transcript_text, transcription,
    audio_retention, is_milestone, captured_at_utc, created_at_utc, updated_at_utc
)
SELECT
    id,
    project_id,
    rel_path,
    note_text,
    transcript_text,
    NULLIF(transcript_text, ''),
    CASE audio_retention
        WHEN 'text_only' THEN 'text'
        WHEN 'audio_only' THEN 'audio'
        WHEN 'text' THEN 'text'
        WHEN 'audio' THEN 'audio'
        ELSE 'both'
    END,
    is_milestone,
    captured_at_utc,
    created_at_utc,
    updated_at_utc
FROM _capture_entries_old;

CREATE TABLE attachments (
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

INSERT INTO attachments (
    id, capture_entry_id, original_attachment_id, kind, stored_rel_path,
    mime_type, byte_size, sha256, created_at_utc
)
SELECT
    id, capture_entry_id, original_attachment_id, kind, stored_rel_path,
    mime_type, byte_size, sha256, created_at_utc
FROM _attachments_old;

DROP TABLE _attachments_old;
DROP TABLE _capture_entries_old;

CREATE INDEX IF NOT EXISTS idx_capture_entries_proj_time
    ON capture_entries (project_id, captured_at_utc);

CREATE INDEX IF NOT EXISTS idx_capture_entries_proj_milestone
    ON capture_entries (project_id, is_milestone);

CREATE INDEX IF NOT EXISTS idx_attachments_capture
    ON attachments (capture_entry_id);
