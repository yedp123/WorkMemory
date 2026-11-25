-- Phase 8A: Project summaries (Last Known State & custom user override)

ALTER TABLE projects ADD COLUMN summary_custom TEXT;
ALTER TABLE projects ADD COLUMN summary_generated TEXT;
ALTER TABLE projects ADD COLUMN summary_updated_utc TEXT;
