---
trigger: glob
globs: "src/work_memory/ui/**"
description: PySide6 dark theme matching docs/ui_prototype.html, progressive disclosure, threading, and non-focus-stealing popups.
---
# PySide6 UI & UX Rules (Blueprint: docs/ui_prototype.html)

## Visual Style & Layout (Match docs/ui_prototype.html)
- Build a calm, quiet dark desktop interface matching `docs/ui_prototype.html`:
  - Main background: `#17191d` | Panels: `#1e2126` | Secondary surfaces: `#24282e`
  - Hairline borders: `#30353d` | Primary text: `#edf0f3` | Muted text: `#929aa5`
  - Soft accents: `#a9b8df` (active/files), `#8dbda4` (ongoing/confirmed), `#d8b57c` (notes/inferred), `#b7a6de` (scheduled events).
- **Navigation**: Keep **Projects** and **History** as the ONLY two primary navigation tabs. Place **Settings** behind a small gear icon (`⚙`) in the top-right header next to a discreet status dot. Keep `+ Capture` and the single global search bar in the top bar.
- **Progressive Disclosure**: Show controls only when relevant to the current task (e.g., voice/screenshot drawers open inside Quick Capture when clicked; event creation lives inside calendars; project status and export live inside Project Detail; monitoring/exclusions/backup live in Settings).
- Never include debug buttons, simulated alert triggers, or developer clutter in the user-facing UI.

## Thread Safety
- NEVER run filesystem scans, SQLite queries, or audio transcription on the Qt main GUI thread.
- Run background tasks via `QThreadPool` / `QRunnable` or dedicated workers, and update widgets exclusively via Qt `Signal` / `Slot`.

## Non-Focus-Stealing Notifications & Hotkeys
- Floating capture prompts MUST NEVER steal focus from the user's active creative software. Apply `Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus` and `Qt.WA_ShowWithoutActivating`.
- Implement global hotkeys (`Ctrl+Shift+M`) via Windows `user32.RegisterHotKey` using `ctypes` integrated with Qt's `nativeEvent` (never use keylogger-style hook packages like `keyboard` or `pynput`).