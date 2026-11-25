# Building the Work Memory Windows Installer

Work Memory ships as a fast-starting `--onedir` PyInstaller bundle wrapped in a per-user Inno Setup 6 installer (`PrivilegesRequired=lowest`, no administrator rights required).

## Prerequisites

1. **Python virtual environment (`.venv`)** with project dependencies plus PyInstaller:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]" pyinstaller
   ```
2. **Inno Setup 6** (`ISCC.exe`):
   ```powershell
   winget install --id JRSoftware.InnoSetup --source winget --scope user
   ```
3. **Offline Whisper `base` model** (included automatically in the installer):
   - Expected in `%LOCALAPPDATA%\WorkMemory\models\` (or `packaging\models\base\`, or pointed to via `WM_WHISPER_MODEL_DIR`).
   - Required files: `model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt`.

## One-Command Build

Run from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
```

This script:
1. Generates `packaging/work_memory.ico` directly from `work_memory.ui.app_icon.build_brand_pixmap()`.
2. Builds `dist/WorkMemory/WorkMemory.exe` (`--onedir`, windowed, bundled SQL migrations + `faster-whisper` `base` model + `silero_vad_v6.onnx` + PortAudio).
3. Compiles `packaging/work_memory.iss` and saves `WorkMemorySetup-<version>.exe` in the repository root folder.

Optional flags:
- `-SkipInstaller`: build only `dist/WorkMemory/` without running `ISCC.exe`.
- `-SkipModel`: build without requiring the local Whisper `base` model.

## Install & Uninstall Layout

- **Application binaries**: `%LOCALAPPDATA%\Programs\WorkMemory\`
- **User data (preserved on uninstall)**: `%LOCALAPPDATA%\WorkMemory\` (or the custom path configured in `bootstrap.json`)
- **Shortcuts & startup**: Start Menu shortcut, optional Desktop shortcut, and optional HKCU `Run` entry (`"...\WorkMemory.exe" --minimized`).
