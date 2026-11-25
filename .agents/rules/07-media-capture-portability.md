---
trigger: glob
globs: "src/work_memory/media/**, src/work_memory/ui/capture/**, src/work_memory/services/notification_service.py, src/work_memory/services/manifest_service.py"
description: HiDPI screenshots, isolated audio/Whisper workers, idle/fullscreen alert pausing, and portable .wmem manifests.
---
# Media, Notifications & Portability Rules

## High-DPI Multi-Monitor Screenshots
- Query per-screen geometry and `devicePixelRatio()` via `QGuiApplication.screens()` and freeze the screen bitmap BEFORE showing any region-selection overlay.
- Save original and annotated screenshots strictly inside app-owned `attachments/`. Never overwrite original captures or user project files.

## Audio Recording & Offline Transcription
- Open the default audio input device ONLY while recording; close the stream immediately on stop to prevent hot-plug crashes.
- Stream audio directly to a temp WAV file inside `drafts/` so accidental closure never loses a recording.
- Run offline transcription (`faster-whisper`) inside an isolated subprocess that exits when idle so RAM/VRAM is freed.
- Strictly honor the user's audio-retention choice (audio + text, transcription only, or audio only).

## Idle & Fullscreen-Aware Notifications
- Before showing scheduled or repeated-save notifications, check Windows `GetLastInputInfo` (pause if idle > 120s) and `SHQueryUserNotificationState` (suppress during fullscreen or screen sharing).
- Keep time-based reminders separate internally from filesystem-event notifications.
- Generic save reminders MUST say "Remember to save your work" — never claim unsaved changes were detected.

## Portable Manifest (.wmem)
- Export portable bundles as a standard ZIP (`.wmem`) containing `manifest.json` (with `schema_version`), selected app-owned attachments, and SHA-256 checksums.
- Validate ZIP member paths on import to prevent path traversal.
- NEVER create a sidecar JSON inside a user's project folder unless triggered by an explicit opt-in user action.