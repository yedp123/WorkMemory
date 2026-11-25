---
trigger: always_on
description: Enforces strict read-only guarantees on monitored user workspaces and Windows file-locking safety.
---
# Safety Rule: Protect Original User Work

## Hard Prohibitions on Monitored Workspaces
NEVER write code that performs any of the following inside a monitored workspace or registered project folder:
- `open(..., "w" | "a" | "x" | "r+")`, `Path.write_text()`, `Path.write_bytes()`
- `os.remove`, `os.unlink`, `os.rename`, `os.replace`, `shutil.move`, `shutil.rmtree`
- Automatic creation of sidecar files (`.json`, `.db`, `.ini`, thumbnails, temp files) inside user folders.

## Allowed Exceptions (Explicit User Action Only)
1. **New Project Creation**: Creating an empty folder ONLY when the user explicitly selects "Create New Project Folder" and confirms the path.
2. **Explicit Portable Export**: Writing an export bundle ONLY to an external path explicitly chosen by the user via a Save dialog.

## Strict Storage Isolation
All Work Memory data MUST live exclusively under `%LOCALAPPDATA%\WorkMemory\` (or an isolated `tmp_path` during tests):
- `work_memory.db` (SQLite database)
- `attachments/` (screenshots, annotated copies, voice recordings)
- `drafts/` (Quick Capture draft recovery)
- `logs/` (rotating application logs)

## Windows File-Locking Discipline
- Never block a creative application (Maya, Blender, ZBrush, Photoshop, Unity, Premiere) from saving its own files.
- Prefer `os.stat()` and `os.scandir()` over opening files.
- If a read preview or partial fingerprint is needed, wait for write-quiescence first and immediately close the file handle in a `with` block. Catch `PermissionError` / `OSError` gracefully.