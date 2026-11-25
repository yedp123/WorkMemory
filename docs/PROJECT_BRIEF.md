# Work Memory
## Product Definition & Implementation Plan

**Project type:** Local-first Windows desktop application
**Primary goal:** Automatically preserve the history and context of creative work without changing the user's existing workflow.

---

# 1. Product vision

Work Memory is a quiet, local-first memory assistant for people who work with files and creative projects.

It observes meaningful file activity, records project history, lets users capture important context, and reminds them about relevant events.

It should help users answer:

- What was I working on?
- What changed?
- When did I last work on this?
- Why did I make that decision?
- What did I send to the client?
- Was it approved?
- Where did I leave off?
- What happened on a particular day?

**Core principle:**

> Don't make me organize my work. Help me remember it.

Work Memory is not a project-management tool, file manager, task manager, or replacement for existing creative applications.

It is a memory layer that works alongside the user's existing folders, files, and applications.

## The most important design principle

**The user should not need to open Work Memory for Work Memory to be useful.**

It should work quietly in the background. Users should be able to interact with it when they want to capture something, when a relevant reminder appears, or when they need to retrieve past information.

The interface should remain simple, clean, approachable, and unobtrusive.

---

# 2. CRITICAL: Protect the user's original work

This is the most important technical and architectural requirement.

Work Memory must NEVER damage, reorganize, or modify the user's existing work.

### Absolute restrictions

Work Memory must never:

- Rename original files.
- Move original files or folders.
- Delete original files or folders.
- Overwrite original files.
- Modify file contents.
- Reorganize folder structures.
- Automatically create project folders inside existing workspaces.
- Change original file extensions.
- Open and save original files through Work Memory.
- Perform destructive cleanup operations on monitored folders.

The application must not require users to move their work into a special Work Memory directory.

It must adapt to existing folder structures.

### Read-only observation

The filesystem monitoring system should observe file activity and record relevant metadata.

It may read file metadata and, where appropriate, read file contents for supported previews or indexing. It must never write changes back to original files.

All captures and memories belong to Work Memory's own storage:

- Notes.
- Audio recordings.
- Transcriptions.
- Screenshots.
- Annotated screenshots.
- Calendar events.
- Activity records.
- Project summaries.
- Application metadata.

These must be stored separately from original project assets.

### Safety-first development

Implement a strict separation between:

1. Original user files.
2. Work Memory's internal database.
3. Work Memory's captured attachments.
4. Portable export/import files.

Do not implement filesystem write operations against monitored workspaces unless they are explicitly requested by the user and are part of a separately approved feature.

The default application must be safe to run against valuable professional projects.

Include tests proving that monitoring does not modify original files or directory structures.

---

# 3. Main application structure

The primary navigation should remain extremely simple.

- Projects
- History
- Settings

A global search bar should be available at the top.

Avoid duplicate search fields, excessive navigation, unnecessary dashboards, or complicated nested menus.

## Projects

Display registered projects in a clean visual grid.

Each project card should contain:

- Project thumbnail or cover.
- Project name.
- Short description.
- Last activity date.
- Small project status indicator.

Two project statuses:

- Ongoing.
- Completed.

Status should be manually controlled by the user. Do not infer completion from inactivity.

Completed projects remain accessible and searchable.

## Project detail

A project page should provide:

1. Project identity and basic information.
2. Last known state.
3. Recent activity.
4. Project calendar.
5. Notes.

The project should also provide an easy way to open its original folder.

### Last known state

Provide a short summary explaining where the project was last left.

Example:

"The latest client presentation was sent for review on November 20 and subsequently approved. Final assets were saved on November 21. The project appears to be awaiting source-file delivery."

Requirements:

- Keep it short, ideally two or three sentences.
- Use recorded activity and user notes.
- Explicit user notes should take priority over AI assumptions.
- Clearly distinguish confirmed information from inferred information.
- Never invent approvals, deliveries, or completed tasks.
- Allow the user to edit or replace the summary.
- Update it when meaningful new information appears.

This is a memory aid, not a project report.

## History

Provide a calendar-based history view.

Selecting a date displays a unified timeline containing:

- File activity.
- Notes and captures.
- Project events.
- Scheduled calendar events.

Categories should be visually distinguishable and collapsible.

Group related file changes to avoid overwhelming users with hundreds of low-level filesystem events.

Show the first few files and provide a Show More option.

Users should be able to navigate history globally or from within an individual project.

---

# 4. Workspace and project registration

A workspace is a monitored folder root.

A project is a folder or collection of folders that the user explicitly registers.

Support three entry paths:

1. Import an existing workspace.
2. Register an existing folder as a project.
3. Create a new project and optionally create its folder.

The third option is allowed because the user explicitly requested creation.

### Suggested project discovery

Work Memory may inspect folder structures and suggest possible projects.

Use clues such as:

- Recognisable project files.
- README or documentation files.
- Application-specific folder structures.
- Git repositories.
- Related asset collections.
- File activity patterns.

Suggestions must never automatically register projects.

The user confirms or dismisses suggestions.

Support nested projects and avoid assuming that the parent folder is always the meaningful project.

Do not treat every folder as a project.

### Multiple workspaces

Design the architecture to support multiple workspace roots, potentially across different drives.

The Projects and History interfaces should provide a unified experience.

---

# 5. Filesystem activity tracking

This is a foundational feature and should be implemented before advanced functionality.

Record meaningful events:

- File created.
- File modified.
- File renamed.
- File moved.
- File deleted.

Do not expose every raw filesystem event directly to the user.

Implement:

- Event debouncing.
- Duplicate detection.
- Temporary-file filtering.
- Backup-file filtering.
- Rename and move detection.
- Save As handling.
- Event grouping.
- Cooldowns.
- Configurable exclusions.
- Recovery and reconciliation after application restart.

The initial workspace scan establishes a baseline. Existing files must not be presented as newly created.

Filesystem modification timestamps must not be presented as proof of time spent working.

Work Memory should preserve enough underlying event information to reconstruct meaningful history.

---

# 6. Quick Capture

Quick Capture is a central feature.

It must be available:

- Through contextual notifications.
- Manually from the application.
- From the system tray.
- Optionally through a global keyboard shortcut.

It should work without requiring the user to navigate through several application screens.

One capture can contain multiple content types.

For example:

- Text note.
- Voice recording.
- Transcription.
- Screenshot.
- Image attachment.

These should form one combined memory entry rather than unrelated activity records.

## Text notes

Allow quick text entry and saving.

Associate the note with the relevant project and, where possible, a file.

## Voice recording

Workflow:

1. Start recording.
2. Speak naturally.
3. Stop recording.
4. Generate transcription.
5. Review and edit the transcription.
6. Save.

Allow the user to choose:

- Keep transcription only.
- Keep original audio and transcription.
- Keep audio only.

Do not silently discard audio when the user has selected audio retention.

Investigate practical transcription engines, including offline options.

## Screenshots

Capture modes:

- Full screen.
- Active application window.
- Selected region.

Always display a preview before saving.

Never capture screenshots automatically without explicit user action.

### Screenshot annotation

Initial tools:

- Freehand pen.
- Arrow.
- Circle and rectangle.
- Text label.
- Crop.
- Undo.

The annotated image is stored as a Work Memory attachment. Never overwrite the original screenshot or any existing project image.

## Draft recovery

If the capture panel is accidentally closed, preserve unfinished work temporarily so it can be recovered.

---

# 7. Notification system

Notifications should be non-modal, dismissible, unobtrusive, and never steal focus.

They must not interrupt the application the user is currently working in.

There are three distinct notification types.

## A. Contextual capture notifications

New-file notifications are enabled by default.

When meaningful new files are detected, offer the user an opportunity to record context.

Possible actions:

- Add note.
- Record voice.
- Capture screenshot.
- Dismiss.

Treat new files differently from subsequent saves.

Do not notify for every filesystem event.

## B. Repeated-save reminders

Allow users to configure reminders:

- Every save.
- Every 3 saves.
- Every 5 saves.
- Every 10 saves.
- Custom interval.
- Never.

Reset the counter after a reminder has been handled or dismissed.

Avoid repeatedly reminding users about the same group of saves.

## C. Scheduled reminders and custom rules

Allow users to create simple notification rules.

Examples:

- Remind me every 5 minutes to save my work.
- Remind me every 30 minutes to record progress.
- Remind me to take a screenshot when starting a project.
- Remind me to record a note after a period of work.

Keep rule creation simple: trigger, frequency or schedule, and message.

Important: Work Memory cannot generally know whether an arbitrary application's current work is unsaved. Generic reminders must say "Remember to save your work", not claim that unsaved changes were detected.

Keep time-based reminders separate internally from filesystem-event notifications.

### Notification duration

Configurable:

- 10 seconds.
- 30 seconds.
- 1 minute.
- 5 minutes.
- Until manually dismissed.

Suggested default: 1 minute.

Persistent notifications must remain unobtrusive.

---

# 8. Calendar and scheduled events

The calendar is a lightweight extension of History, not a replacement for a full calendar application.

It supports two kinds of information:

1. Historical activity.
2. Planned events.

These must remain distinct.

## Global calendar

The History calendar should display both activity markers and scheduled event markers.

Selecting a date shows:

- What actually happened.
- Which notes were recorded.
- Which files changed.
- Which events were scheduled.

Use distinct visual indicators for activity and planned events.

## Project calendar

Each project should have its own calendar view.

Selecting a date shows only activity and events associated with that project.

This should be another view of the same underlying records, not a separate duplicate history system.

## Creating events

A simple event should support:

- Title.
- Date.
- Time.
- Optional description.
- Optional project association.
- Reminder time.

Events can be global or associated with a project.

## Event notifications

Provide normal Windows desktop notifications before scheduled events.

Example:

"Client meeting starts in 10 minutes — Project Alpha."

Calendar notifications should have a subtle visual distinction from capture prompts.

They must never steal focus.

Events should distinguish between:

- Scheduled.
- Completed.
- Cancelled.

A scheduled meeting must not automatically be recorded as a meeting that actually happened.

Avoid complex recurring-event functionality in the initial version.

---

# 9. Portable project memory and JSON manifest

This is an important architectural consideration.

Users should be able to move their projects to another computer, restore a backup, or transfer project context without losing their Work Memory history.

The project memory must not depend exclusively on an absolute path on one computer.

## Recommended architecture

Use:

- SQLite as the primary local database.
- A separate application-managed attachment directory.
- A portable JSON manifest for project identity and history export/import.

The JSON manifest should contain information such as:

- Project identifier.
- Project name and description.
- Project status.
- Relative project folder references.
- File activity records.
- Notes.
- Calendar events.
- Last known state.
- Capture metadata.
- References to screenshots, recordings, and other attachments.
- Export schema version.

Prefer relative paths within a project wherever possible.

Avoid relying exclusively on absolute Windows paths.

## Important distinction

The JSON manifest is a portable representation of Work Memory's records. It is not a replacement for the user's original project files.

A portable export may contain:

- Manifest JSON.
- Work Memory notes and metadata.
- Selected captured attachments.
- Optional thumbnails.

It must not silently copy, move, modify, or reorganise original project assets.

## Optional project-sidecar JSON

A portable manifest could optionally be stored alongside a project for easier transfer.

However:

**Never automatically create or modify a JSON file inside a user's existing project folder.**

This must be an explicit opt-in action.

The default should be export/import through Work Memory's own storage or a user-selected external destination.

## Import and recovery

When importing a portable project manifest:

- Ask the user to locate the corresponding project folder if necessary.
- Resolve relative file references.
- Detect missing files.
- Preserve historical records even when original files are unavailable.
- Avoid overwriting existing records without an explicit conflict-resolution process.
- Validate the manifest schema and version.

The application must remain useful even if some original files have been moved, renamed, or deleted outside Work Memory.

---

# 10. Privacy, backup and user control

Include:

- Pause monitoring.
- Workspace and project exclusions.
- Configurable ignored file types and folders.
- Clear project removal controls.
- Clear history and capture deletion controls.
- Backup and restore.
- Export and import.
- Transparent monitoring status.

Local-first operation is the default.

Do not require cloud accounts or cloud storage for core functionality.

Any future cloud or AI service integration must be optional and clearly explained.

---

# 11. Recommended technical architecture

Suggested initial stack:

- Python.
- PySide6 for the Windows desktop interface.
- SQLite for structured local records.
- Watchdog for filesystem observation.
- Separate modules for screenshot capture, annotation, audio recording and transcription.

Keep the architecture modular.

Suggested conceptual modules:

1. Application shell and navigation.
2. Workspace manager.
3. Project registry.
4. Filesystem observer.
5. Event processor and history engine.
6. SQLite data layer.
7. Search and indexing.
8. Quick Capture.
9. Screenshot capture and annotation.
10. Audio recording and transcription.
11. Notification manager.
12. Calendar and event manager.
13. Project summary generator.
14. Portable manifest import/export.
15. Settings and privacy controls.

Do not build everything into one large Python file.

Define clear interfaces between modules.

The filesystem observer should not directly manipulate UI elements. It should produce events that are processed and stored by the appropriate services.

---

# 12. Development phases

Build incrementally. Each phase should result in a working, testable application.

## Phase 0 — Project foundation

- Inspect the development environment.
- Establish the application structure.
- Create the PySide6 application shell.
- Implement navigation.
- Establish SQLite database initialization and migrations.
- Define data models.
- Define strict storage boundaries.
- Establish automated tests.

Deliverable: A running desktop shell with persistent local storage.

## Phase 1 — Workspace observation

- Select workspace folders.
- Register and remove workspaces.
- Implement filesystem monitoring.
- Record meaningful file events.
- Debounce and group events.
- Filter temporary files.
- Establish initial baseline scans.
- Recover missed events after restart.
- Test that original files remain unchanged.

Deliverable: Reliable activity tracking.

## Phase 2 — Project management and discovery

- Register existing project folders.
- Support multiple workspaces.
- Support nested projects.
- Implement project discovery suggestions.
- Add project cards and descriptions.
- Add ongoing/completed status.
- Open original folders.

Deliverable: Functional Projects view.

## Phase 3 — History

- Implement global daily calendar.
- Implement daily activity timeline.
- Implement collapsible event categories.
- Implement project-specific history.
- Implement project calendar navigation.
- Implement basic search.

Deliverable: Users can reliably recall past activity.

## Phase 4 — Notes and Quick Capture

- Implement manual text capture.
- Associate captures with projects.
- Implement capture panel.
- Implement draft recovery.
- Implement image attachments.
- Implement screenshot capture.
- Implement basic annotation tools.

Deliverable: Users can intentionally preserve important context.

## Phase 5 — Notifications

- Implement new-file notifications.
- Implement repeated-save reminders.
- Implement notification duration settings.
- Implement notification dismissal and cooldown logic.
- Implement custom time-based reminders.

Deliverable: Useful background interaction without interruptions.

## Phase 6 — Audio and transcription

- Implement voice recording.
- Implement transcription.
- Allow transcription review and editing.
- Implement audio-retention preferences.
- Investigate offline transcription.

Deliverable: Complete multimodal Quick Capture.

## Phase 7 — Calendar events

- Implement event creation and editing.
- Support global and project-specific events.
- Display scheduled events in calendars.
- Implement event status.
- Implement Windows desktop reminders.

Deliverable: Lightweight event and meeting reminders.

## Phase 8 — Project memory and portability

- Implement Last known state summaries.
- Prioritise explicit notes over inferred information.
- Implement editable summaries.
- Implement portable JSON manifest.
- Implement export and import.
- Support relative paths.
- Support missing-file detection.
- Implement backup and restore.

Deliverable: Project context can survive computer changes and backups.

## Phase 9 — Reliability and refinement

- Test long-running filesystem monitoring.
- Test large workspaces.
- Test application restarts.
- Test interrupted captures.
- Test backup restoration.
- Test portability across different folder paths and drives.
- Test exclusions.
- Test privacy and file integrity.
- Refine performance and UI.

Deliverable: A stable first release.

---

# 13. What NOT to build

Do not expand the first version into:

- A task manager.
- A team collaboration platform.
- A time-tracking application.
- A productivity scoring system.
- A complicated project management suite.
- A full calendar replacement.
- A forced folder organisation system.
- A cloud-dependent service.

Keep the product focused on memory.