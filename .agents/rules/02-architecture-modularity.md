---
trigger: always_on
description: Prevents monolithic files and enforces functional segmentation and strict layered boundaries.
---
# Architecture & Anti-Monolith Rules

## File Size & Functional Segmentation Limits
- **Soft limit**: 250 lines per Python file.
- **Hard limit**: 350 lines per Python file. If a file approaches 300 lines, split it into smaller, functionally focused modules before adding more code.
- **Single responsibility per file**: Place one primary class or cohesive group of functions in each file. Never combine multiple views, repositories, or services into one script.
- `main.py` MUST remain a thin bootstrap script under 80 lines.

## Functional Grouping Rules
- Put each database table group in its own file under `src/work_memory/storage/repositories/` (e.g., `workspace_repo.py`, `project_repo.py`, `observed_event_repo.py`, `capture_repo.py`, `calendar_repo.py`).
- Put each screen in its own file under `src/work_memory/ui/views/` (`projects_view.py`, `project_detail_view.py`, `history_view.py`, `settings_view.py`).
- Put reusable UI components (project cards, calendar grid, collapsible timeline groups) in `src/work_memory/ui/widgets/`.

## Strict Downward Dependency Direction (No Circular Imports)
1. `ui/` -> may import `services/`, `core/`, `config/`
2. `services/` -> may import `storage/`, `watcher/`, `media/`, `core/`, `config/`
3. `watcher/` -> may import `core/`, `config/`
4. `storage/` -> may import `core/`, `config/`
5. `media/` -> may import `core/`, `config/`
6. `core/` -> standard library and typing ONLY (plus thin Qt Signal wrapper in `event_bus.py`).

## Banned Couplings
- `watcher/` MUST NEVER import `ui/` or `storage/`. It emits normalized events via callback or `core/event_bus.py`.
- `ui/` MUST NEVER import `sqlite3`, `storage/`, or `watchdog`. All data flows through `services/`.
- `storage/` MUST NEVER import `ui/` or `services/`.

## Code Quality
- Use full Python type hints on all functions and dataclasses.
- Use `pathlib.Path` consistently; store project-relative POSIX paths (`/`).
- Never silence errors (`except: pass` is banned). Log all caught exceptions via `logging`.