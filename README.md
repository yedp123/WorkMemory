# WorkMemory

[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6?style=flat-square)](https://github.com/yedp123/WorkMemory)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

**A quiet, local-first Windows desktop memory assistant for creative work.**

WorkMemory preserves the history and context of your projects in the background—without forcing you to reorganize your folders, change your tools, or upload files to the cloud.

> **Core principle:** *Don't make me organize my work. Help me remember it.*

---

## Why WorkMemory?

When working across creative apps (Blender, Maya, Photoshop, Premiere, Unity, code editors, etc.), it is easy to lose track of:
- *What was I working on last week?*
- *What changed between revisions?*
- *Why did I make that decision, or what did the client ask for?*
- *Where did I leave off before switching projects?*

WorkMemory acts as a **passive memory layer** alongside your existing folders. It observes meaningful file activity, lets you capture quick notes, annotated screenshots, and offline-transcribed voice memos, and brings everything together into a unified, searchable timeline.

---

## Safety First: Strictly Read-Only on Your Files

WorkMemory is designed to run safely alongside valuable production projects:

- **Never modifies original files** — It will never rename, move, delete, overwrite, reorganize, or hold write locks on files inside your monitored workspaces.
- **Zero sidecar clutter** — No `.json`, `.db`, thumbnail, or temp files are ever dropped inside your project folders.
- **Isolated app storage** — All WorkMemory data (`work_memory.db`, captured attachments, drafts, and logs) is stored strictly inside `%LOCALAPPDATA%\WorkMemory\` (or a custom location you configure).

---

## Features

- **Background Filesystem Observation**
  - Watches multiple workspace roots across drives using `watchdog`.
  - Filters temporary/cache noise, collapses atomic saves and image sequences, and reconciles missed changes on startup via `os.scandir`.
  - Pause/resume monitoring anytime from the app or system tray.

- **Project & Workspace Organization**
  - Register existing folders (including nested projects) without moving them.
  - Project discovery suggestions based on folder clues (never auto-registered without confirmation).
  - Pin important projects, track `Ongoing` / `Completed` status, customize project covers, and open original folders in Explorer.

- **Multimodal Quick Capture**
  - Trigger from the main window, system tray, contextual notifications, or a global Windows hotkey.
  - Combine **text notes**, **screen captures** (full screen, active window, or region) with built-in annotation tools (freehand pen, arrow, shapes, text, crop, undo), and **voice recordings** with offline speech-to-text transcription (`faster-whisper`).
  - Automatic draft recovery if the capture window is closed before saving.

- **Unified History, Calendar & Search**
  - Global and per-project calendars showing historical file activity, captures, and scheduled events.
  - Collapsible daily timeline groups, milestone starring (including directly from notifications), and instant full-text search via SQLite FTS5.

- **Unobtrusive Notifications & Reminders**
  - Focus-safe desktop toasts for meaningful new files, configurable repeated-save reminders, custom interval reminders, and upcoming calendar events.

- **Summaries, Portability & Backups**
  - Editable *"Last known state"* project summaries that prioritize your explicit notes.
  - Portable JSON manifest export/import with relative paths, missing-file relinking, local backup/restore, and dark/light themes.

---

## Getting Started

### Prerequisites

- **Windows** (designed for Windows desktop, system tray, and Win32 hotkeys)
- **Python 3.11+**

### Run from Source

1. **Clone the repository**
   ```powershell
   git clone https://github.com/yedp123/WorkMemory.git
   cd WorkMemory
   ```

2. **Create and activate a virtual environment**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**
   ```powershell
   pip install -e ".[dev]"
   ```

4. **Launch WorkMemory**
   ```powershell
   python -m work_memory.main
   ```
   To start minimized in the system tray:
   ```powershell
   python -m work_memory.main --minimized
   ```

> **Note on offline voice transcription:** Speech-to-text uses `faster-whisper` with a local Whisper `base` model (no cloud calls). See [`docs/BUILDING.md`](docs/BUILDING.md) for local model placement details.

---

## Building the Windows Installer

WorkMemory can be packaged as a standalone `--onedir` PyInstaller bundle and per-user Inno Setup 6 installer (no administrator privileges required).

See [`docs/BUILDING.md`](docs/BUILDING.md) for prerequisites and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
```

This produces `WorkMemorySetup-<version>.exe` in the repository root.

---

## Tech Stack & Architecture

- **UI:** PySide6 (Qt for Python), Windows system tray, Win32 global hotkeys
- **Storage:** SQLite (WAL mode + FTS5 full-text search) with numbered SQL migrations
- **Filesystem Watcher:** Watchdog + custom debouncing, coalescing, and restart reconciliation
- **Media:** High-DPI desktop capture, `sounddevice` audio capture, `faster-whisper` offline transcription

The codebase under `src/work_memory/` is organized into decoupled layers:

| Module | Responsibility |
| --- | --- |
| `config/` | App-owned paths (`%LOCALAPPDATA%\WorkMemory\`), workspace safety guards, and typed settings |
| `core/` | Pure Python dataclasses, UUIDv7 IDs, protocols, and the Qt `EventBus` |
| `storage/` | SQLite connection management, migrations, repositories, and attachment storage |
| `watcher/` | Read-only filesystem observer, filters, event coalescer, and restart reconciler |
| `services/` | Application business logic (workspaces, projects, history, captures, summaries, notifications, calendar, manifests, backups, relinking) |
| `media/` | Screenshot capture, audio recording, offline transcription worker, and thumbnail/mesh preview helpers |
| `ui/` | PySide6 views, widgets, system tray, global hotkeys, and Quick Capture / annotation tools |

---

## Development & Testing

Run the full test suite (including read-only workspace safety tests):
```powershell
pytest
```

Run the linter:
```powershell
ruff check src tests
```

---

## Documentation

- [`docs/BUILDING.md`](docs/BUILDING.md) — Packaging and building the Windows installer
- [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) — Product vision, architecture plan, and feature specifications
- [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md) — Long-term UX principles and design decisions
- [`AGENTS.md`](AGENTS.md) — Architecture contract and safety rules

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
