"""Isolated subprocess worker for strictly offline speech-to-text via faster-whisper."""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

_TARGET_SAMPLE_RATE = 16_000
_REQUIRED_MODEL_FILES = ("model.bin", "config.json", "vocabulary.txt")


def _has_required_model_files(directory: Path) -> bool:
    return directory.is_dir() and all((directory / name).is_file() for name in _REQUIRED_MODEL_FILES)


def resolve_local_model_dir(models_dir: Path) -> Path | None:
    """Find a complete local CTranslate2 Whisper ``base`` directory without network access."""
    search_roots = [models_dir]
    if getattr(sys, "frozen", False) and (meipass := getattr(sys, "_MEIPASS", None)):
        bundled_models = Path(meipass) / "models"
        if bundled_models != models_dir:
            search_roots.append(bundled_models)

    for root in search_roots:
        direct_base = root / "base"
        if _has_required_model_files(direct_base):
            return direct_base

        hf_snapshots = root / "models--Systran--faster-whisper-base" / "snapshots"
        if hf_snapshots.is_dir():
            for candidate in sorted(hf_snapshots.iterdir(), reverse=True):
                if _has_required_model_files(candidate):
                    return candidate

    return None


def load_wav_as_float32(wav_path: Path) -> np.ndarray:
    """Decode a 16-bit PCM WAV file into a DC-removed, gain-normalized 16 kHz mono float32 array."""
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth * 8}-bit (expected 16-bit PCM).")
    if not raw:
        return np.zeros(0, dtype=np.float32)

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if framerate != _TARGET_SAMPLE_RATE and samples.size > 0:
        target_len = max(1, round(samples.size * _TARGET_SAMPLE_RATE / framerate))
        x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        samples = np.interp(x_new, x_old, samples).astype(np.float32)

    if samples.size > 0:
        samples = (samples - float(np.mean(samples))).astype(np.float32)
        peak = float(np.max(np.abs(samples)))
        if 1e-4 < peak < 0.85:
            gain = min(0.85 / peak, 25.0)
            samples = np.clip(samples * gain, -1.0, 1.0).astype(np.float32)
    return samples


def transcribe_wav(wav_path: Path, models_dir: Path) -> dict[str, object]:
    """Transcribe ``wav_path`` strictly offline using a local faster-whisper ``base`` model."""
    if not wav_path.is_file():
        return {"ok": False, "error": f"Audio file not found: {wav_path}"}

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    local_model_dir = resolve_local_model_dir(models_dir)
    if local_model_dir is None:
        return {
            "ok": False,
            "error": "Local offline Whisper model not found in models directory.",
        }

    try:
        from faster_whisper import WhisperModel

        audio = load_wav_as_float32(wav_path)
        if audio.size == 0:
            return {"ok": True, "text": ""}

        model = WhisperModel(
            str(local_model_dir),
            device="cpu",
            compute_type="int8",
            local_files_only=True,
        )
        segments, _info = model.transcribe(
            audio,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        parts = [seg.text.strip() for seg in segments if getattr(seg, "text", "").strip()]
        return {"ok": True, "text": " ".join(parts).strip()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).strip() or exc.__class__.__name__}


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint printing a single JSON result to stdout and exiting."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        payload: dict[str, object] = {
            "ok": False,
            "error": "Usage: python -m work_memory.media.transcribe_worker <wav_path> <models_dir>",
        }
        print(json.dumps(payload), flush=True)
        return 1

    wav_path = Path(args[0])
    models_dir = Path(args[1])
    payload = transcribe_wav(wav_path, models_dir)
    print(json.dumps(payload), flush=True)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
