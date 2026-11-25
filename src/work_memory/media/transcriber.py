"""Non-blocking Qt controller for isolated offline Whisper transcription."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from work_memory.config.paths import _default_app_root
from work_memory.media.transcribe_worker import resolve_local_model_dir

logger = logging.getLogger(__name__)
_TRANSCRIBE_TIMEOUT_SEC = 180


def run_transcription_subprocess(wav_path: Path, models_dir: Path) -> tuple[bool, str]:
    """Invoke ``transcribe_worker`` in a child process so RAM is reclaimed on exit."""
    effective_models_dir = models_dir
    if resolve_local_model_dir(models_dir) is None:
        default_models = _default_app_root() / "models"
        if default_models != models_dir and resolve_local_model_dir(default_models) is not None:
            effective_models_dir = default_models

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--transcribe-worker", str(wav_path), str(effective_models_dir)]
    else:
        cmd = [
            sys.executable,
            "-m",
            "work_memory.media.transcribe_worker",
            str(wav_path),
            str(effective_models_dir),
        ]
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, check=False, timeout=_TRANSCRIBE_TIMEOUT_SEC, **kwargs)  # type: ignore[call-overload]
    except subprocess.TimeoutExpired:
        logger.warning("Offline transcription worker timed out after %ds.", _TRANSCRIBE_TIMEOUT_SEC)
        return False, (
            "Offline transcription timed out. You can still save your audio recording and add a note."
        )
    except OSError as exc:
        logger.warning("Failed to launch transcription worker: %s", exc)
        return False, (
            f"Could not start offline transcription ({exc}). "
            "You can still save your audio recording."
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    stdout = (proc.stdout or "").strip()
    if stdout:
        last_line = stdout.splitlines()[-1]
        try:
            data = json.loads(last_line)
            if isinstance(data, dict):
                if data.get("ok"):
                    text = str(data.get("text") or "").strip()
                    logger.info(
                        "Offline transcription succeeded in %d ms (%d chars).",
                        elapsed_ms,
                        len(text),
                    )
                    return True, text
                err = str(data.get("error") or "Unknown transcription error.")
                logger.warning("Offline transcription failed in %d ms: %s", elapsed_ms, err)
                return False, _format_user_error(err)
        except json.JSONDecodeError:
            logger.warning("Non-JSON output from transcription worker: %s", last_line)

    stderr = (proc.stderr or "").strip()
    detail = stderr.splitlines()[-1] if stderr else f"exit code {proc.returncode}"
    logger.warning("Offline transcription exited abnormally in %d ms: %s", elapsed_ms, detail)
    return False, _format_user_error(detail)


def _format_user_error(raw_error: str) -> str:
    lower = raw_error.lower()
    if any(tok in lower for tok in ("offline", "connection", "huggingface", "download", "network")):
        return (
            "Offline transcription model is not downloaded yet and could not be reached. "
            "You can still save your audio recording and add a note."
        )
    return f"Transcription unavailable ({raw_error}). You can still save your audio recording."


class _TranscribeSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class _TranscribeTask(QRunnable):
    def __init__(self, wav_path: Path, models_dir: Path, signals: _TranscribeSignals) -> None:
        super().__init__()
        self._wav_path = wav_path
        self._models_dir = models_dir
        self._signals = signals

    def run(self) -> None:
        ok, payload = run_transcription_subprocess(self._wav_path, self._models_dir)
        if ok:
            self._signals.finished.emit(payload)
        else:
            self._signals.failed.emit(payload)


class AudioTranscriber(QObject):
    """Runs offline Whisper transcription in a background thread pool."""

    transcription_finished = Signal(str)
    transcription_failed = Signal(str)
    transcribing_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active_signals: set[_TranscribeSignals] = set()

    @property
    def is_transcribing(self) -> bool:
        """Return ``True`` while at least one background transcription is running."""
        return bool(self._active_signals)

    def transcribe(self, wav_path: Path, models_dir: Path) -> None:
        """Start transcribing ``wav_path`` asynchronously without blocking the UI."""
        was_idle = not self._active_signals
        sig = _TranscribeSignals()
        self._active_signals.add(sig)
        if was_idle:
            self.transcribing_changed.emit(True)

        def _on_done(text: str) -> None:
            self._active_signals.discard(sig)
            self.transcription_finished.emit(text)
            if not self._active_signals:
                self.transcribing_changed.emit(False)

        def _on_fail(err: str) -> None:
            self._active_signals.discard(sig)
            self.transcription_failed.emit(err)
            if not self._active_signals:
                self.transcribing_changed.emit(False)

        sig.finished.connect(_on_done)
        sig.failed.connect(_on_fail)
        QThreadPool.globalInstance().start(_TranscribeTask(wav_path, models_dir, sig))
