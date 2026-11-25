# Work Memory — Architecture Introduction & Agent Contract

You are building **Work Memory**, a local-first Windows desktop application (Python 3.11+, PySide6, SQLite, Watchdog) that quietly preserves the history and context of creative work without changing the user's existing folders or workflow.

## Visual & Product References
- **Visual Guidance**: Follow `docs/ui_prototype.html` for layout, dark color palette, calm spacing, and progressive disclosure.
- **Product Requirements**: Follow `docs/PROJECT_BRIEF.md` for feature behavior across development phases.
- **Design Decisions**: Follow `docs/DESIGN_DECISIONS.md` to preserve long-term UX principles (project pinning, milestone starring including from notifications, 3-level summaries, calm vertical hierarchy, and development priorities).

## System Architecture (Segmented by Functional Category)
Code MUST be organized into decoupled layers. Each category has one clear responsibility:
1. `src/work_memory/config/` — App-owned paths (`%LOCALAPPDATA%\WorkMemory\`), workspace safety guards, and user settings.
2. `src/work_memory/core/` — Pure Python data models (`@dataclass`), time-ordered UUIDv7 generators, protocols, and the Qt `EventBus`. Zero database or widget imports.
3. `src/work_memory/storage/` — SQLite connection management (WAL + FTS5), numbered `.sql` migrations, domain-specific repositories (`repositories/`), and app-owned attachment storage (`attachments.py`).
4. `src/work_memory/watcher/` — Read-only filesystem observation (`observer.py`), noise/cache exclusions (`filters.py`), atomic-save and image-sequence grouping (`coalescer.py`), and `os.scandir` baseline/restart recovery (`reconciler.py`).
5. `src/work_memory/services/` — Application business logic (`workspace_service.py`, `history_service.py`, `capture_service.py`, `summary_service.py`, `notification_service.py`, `manifest_service.py`).
6. `src/work_memory/media/` — High-DPI screenshot capture, mic recording, and isolated offline transcription workers.
7. `src/work_memory/ui/` — Thin PySide6 views (`views/`), reusable cards/widgets (`widgets/`), system tray (`tray.py`), Win32 hotkeys (`hotkeys.py`), and capture/toast dialogs (`capture/`).

## Prime Directives
1. **Read-Only Observation**: Monitored user workspaces are strictly READ-ONLY. Never create, rename, move, delete, overwrite, or hold write-blocking handles on user files.
2. **Avoid Monolithic Files**: Strictly obey `.agents/rules/02-architecture-modularity.md`. Split code cleanly by functional category.
3. **Modify Only What Is Demanded**: Only edit files required for the active task. Never alter unrelated working modules.
4. **Verify Every Change**: Run `pytest` and `ruff check src tests` before completing any task.