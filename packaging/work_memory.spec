# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller --onedir build specification for Work Memory."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
SRC_DIR = ROOT / "src"
ICON_PATH = ROOT / "packaging" / "work_memory.ico"
MIGRATIONS_GLOB = ROOT / "src" / "work_memory" / "storage" / "migrations" / "*.sql"

_REQUIRED_WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


def _find_whisper_model_dir() -> Path | None:
    """Locate a complete local faster-whisper ``base`` snapshot for offline bundling."""
    candidates: list[Path] = []
    if env_dir := os.environ.get("WM_WHISPER_MODEL_DIR", "").strip():
        candidates.append(Path(env_dir))
    candidates.append(ROOT / "packaging" / "models" / "base")

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        default_models = Path(local_appdata) / "WorkMemory" / "models"
        candidates.append(default_models / "base")
        snaps = default_models / "models--Systran--faster-whisper-base" / "snapshots"
        if snaps.is_dir():
            candidates.extend(sorted(snaps.iterdir(), reverse=True))

    for candidate in candidates:
        if candidate.is_dir() and all((candidate / name).is_file() for name in _REQUIRED_WHISPER_FILES):
            return candidate
    return None


datas: list[tuple[str, str]] = [
    (str(MIGRATIONS_GLOB), "work_memory/storage/migrations"),
]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "sqlite3",
    "watchdog.observers.winapi",
    "watchdog.observers.polling",
    "watchdog.observers.read_directory_changes",
    "work_memory.media.transcribe_worker",
    "faster_whisper",
    "sounddevice",
    "_sounddevice_data",
    "numpy",
]

datas += collect_data_files("faster_whisper")
datas += collect_data_files("_sounddevice_data")

for pkg_name in ("ctranslate2", "onnxruntime"):
    pkg_datas, pkg_bins, pkg_hidden = collect_all(pkg_name)
    datas += pkg_datas
    binaries += pkg_bins
    hiddenimports += pkg_hidden

whisper_model_dir = _find_whisper_model_dir()
if whisper_model_dir is not None:
    for fname in _REQUIRED_WHISPER_FILES:
        datas.append((str(whisper_model_dir / fname), "models/base"))
elif os.environ.get("WM_REQUIRE_WHISPER_MODEL") == "1":
    raise FileNotFoundError(
        "Bundled faster-whisper 'base' model not found. Download it once or set WM_WHISPER_MODEL_DIR."
    )

excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtLocation",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQuick3D",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "tkinter",
]

a = Analysis(
    [str(SRC_DIR / "work_memory" / "main.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WorkMemory",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WorkMemory",
)
