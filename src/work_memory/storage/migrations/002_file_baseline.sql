-- Phase 1: Track workspace scan timestamps and read-only file baseline for restart reconciliation.

ALTER TABLE workspaces ADD COLUMN last_scan_utc TEXT;

CREATE TABLE IF NOT EXISTS file_baseline (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    file_id INTEGER NOT NULL DEFAULT 0,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (workspace_id, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_file_baseline_ws_file_id
    ON file_baseline (workspace_id, file_id);
