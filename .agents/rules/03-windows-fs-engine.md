---
trigger: glob
globs: "src/work_memory/watcher/**, src/work_memory/services/workspace_service.py"
description: Windows filesystem watching, creative-app atomic save coalescing, and image sequence rules.
---
# Windows Filesystem Engine Rules

## Creative App Atomic-Save Handling
Creative software saves via temporary files + delete + rename.
- Buffer raw `watchdog` events in a short-window coalescer (default 1000ms) before emitting a normalized `ObservedEvent`.
- Collapse `temp create -> original delete -> temp rename to original` into a single `MODIFIED` event on the original path.
- Never fire a "New File" alert for atomic-save replacements.

## Performance & Noise Control
- **NEVER compute full-file hashes** (SHA-256/MD5 over full file). Creative assets can exceed 10 GB. If fingerprinting is needed, hash only `(file_size, first_64kb, last_64kb)`.
- Default ignore patterns MUST exclude temp/cache noise: `*.tmp`, `*.bak`, `~$*`, `*.swp`, `.DS_Store`, `Thumbs.db`, `.git/objects/`, `node_modules/`, `Library/`, `Temp/`, `Cache/`, `Auto-Save/`.
- Collapse numbered image sequences (e.g., `shot04_0001.exr` .. `shot04_0120.exr`) into a single grouped sequence event.
- Baseline scans and restart reconciliation MUST use `os.scandir()` recursively and mark pre-existing files as baseline — never as "newly created".
- Catch Windows `ReadDirectoryChangesW` buffer overflow errors cleanly and schedule a targeted reconciliation scan instead of crashing the observer thread.