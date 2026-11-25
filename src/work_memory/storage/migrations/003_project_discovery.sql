-- Phase 2: Project discovery dismissals and project path/cover metadata.

ALTER TABLE projects ADD COLUMN cover_style TEXT NOT NULL DEFAULT 'c1';
ALTER TABLE projects ADD COLUMN root_rel_path TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN abs_path TEXT NOT NULL DEFAULT '';

UPDATE projects
SET root_rel_path = rel_path
WHERE root_rel_path = '' AND rel_path != '';

CREATE TABLE IF NOT EXISTS dismissed_suggestions (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    dismissed_at_utc TEXT NOT NULL,
    PRIMARY KEY (workspace_id, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_projects_abs_path
    ON projects (abs_path);
