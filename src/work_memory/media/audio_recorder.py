"""Safe streaming WAV audio recorder using sounddevice and stdlib wave."""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SAMPLE_RATE_HZ = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM


class AudioRecorder:
    """Streams microphone audio directly to a 16 kHz mono 16-bit PCM WAV file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stream: Any = None
        self._wave_file: wave.Wave_write | None = None
        self._output_path: Path | None = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        """Return ``True`` while the microphone stream is open and recording."""
        return self._recording

    @property
    def output_path(self) -> Path | None:
        """Return the active or most recently recorded WAV path."""
        return self._output_path

    def start(self, output_wav_path: Path) -> str | None:
        """Open the default microphone and stream frames to ``output_wav_path``.

        Returns ``None`` on success, or a user-friendly error message on failure.
        """
        if self._recording:
            return "Recording is already in progress."

        try:
            import sounddevice as sd
        except ImportError as exc:
            logger.exception("sounddevice is not installed.")
            return f"Audio recording library unavailable: {exc}"

        target = Path(output_wav_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        wf: wave.Wave_write | None = None
        stream: Any = None
        try:
            wf = wave.open(str(target), "wb")  # noqa: SIM115
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH_BYTES)
            wf.setframerate(SAMPLE_RATE_HZ)

            def _callback(indata: Any, _frames: int, _time_info: Any, status: Any) -> None:
                if status:
                    logger.warning("Audio input status: %s", status)
                with self._lock:
                    if self._wave_file is not None and self._recording:
                        self._wave_file.writeframes(indata.tobytes())

            stream = sd.InputStream(
                samplerate=SAMPLE_RATE_HZ,
                channels=CHANNELS,
                dtype="int16",
                callback=_callback,
            )
            with self._lock:
                self._wave_file = wf
                self._stream = stream
                self._output_path = target
                self._recording = True
            stream.start()
            return None
        except (sd.PortAudioError, OSError, wave.Error, RuntimeError) as exc:
            logger.warning("Failed to start microphone recording: %s", exc)
            with self._lock:
                self._recording = False
                self._stream = None
                self._wave_file = None
            if stream is not None:
                try:
                    stream.close()
                except (sd.PortAudioError, OSError):
                    logger.debug("Ignoring error closing failed audio stream.", exc_info=True)
            if wf is not None:
                try:
                    wf.close()
                except (OSError, wave.Error):
                    logger.debug("Ignoring error closing failed WAV file.", exc_info=True)
            return self._friendly_error(exc)

    def stop(self) -> Path | None:
        """Stop recording, close the microphone stream, and finalize the WAV file."""
        with self._lock:
            self._recording = False
            stream = self._stream
            wf = self._wave_file
            out_path = self._output_path
            self._stream = None
            self._wave_file = None

        try:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error closing audio input stream: %s", exc)
        finally:
            if wf is not None:
                try:
                    wf.close()
                except (OSError, wave.Error) as exc:
                    logger.warning("Error finalizing WAV file %s: %s", out_path, exc)
        return out_path

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        msg = str(exc).strip()
        lower = msg.lower()
        if "device" in lower or "portaudio" in lower or isinstance(exc, OSError):
            return (
                "No working microphone detected. Check that a microphone is plugged in "
                f"and permitted in Windows Privacy settings. ({msg})"
            )
        return f"Could not open microphone: {msg}"
