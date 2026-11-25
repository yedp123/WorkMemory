-- Phase 7: Calendar events & sleep-safe reminders

ALTER TABLE calendar_events ADD COLUMN event_at_utc TEXT;
ALTER TABLE calendar_events ADD COLUMN reminder_minutes INTEGER DEFAULT 10;

UPDATE calendar_events
SET event_at_utc = starts_at_utc
WHERE event_at_utc IS NULL;

CREATE INDEX IF NOT EXISTS idx_calendar_events_event_at
    ON calendar_events (event_at_utc);

CREATE INDEX IF NOT EXISTS idx_calendar_events_due
    ON calendar_events (status, remind_at_utc, notified_at_utc);
