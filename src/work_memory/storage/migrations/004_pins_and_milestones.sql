-- Phase 5A: Project pinning and milestone starring

ALTER TABLE projects ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE observed_events ADD COLUMN is_milestone INTEGER NOT NULL DEFAULT 0;
ALTER TABLE capture_entries ADD COLUMN is_milestone INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_observed_events_proj_milestone
    ON observed_events (project_id, is_milestone);

CREATE INDEX IF NOT EXISTS idx_capture_entries_proj_milestone
    ON capture_entries (project_id, is_milestone);
