"""Procedural calm UI sound synthesizer and Bluetooth-safe async audio cue player."""

from __future__ import annotations

import logging
import math
import os
import struct
import sys
import wave
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

from work_memory.config.paths import assert_not_inside_monitored_workspace
from work_memory.config.settings import AppSettings, normalize_volume

logger = logging.getLogger(__name__)
_SAMPLE_RATE = 44_100
_WAKEUP_SEC = 0.085
_WAKEUP_AMP = 1e-4


def _quantize_volume(volume: int) -> int:
    clamped = normalize_volume(volume, 70)
    return 0 if clamped <= 0 else max(5, min(100, round(clamped / 5) * 5))


def _write_mono_wav(
    dest: Path,
    samples: list[float],
    workspace_roots: Sequence[Path] = (),
) -> Path:
    resolved = dest.expanduser().resolve(strict=False)
    assert_not_inside_monitored_workspace(resolved, list(workspace_roots))
    resolved.parent.mkdir(parents=True, exist_ok=True)
    pcm = bytearray()
    for sample in samples:
        clamped = max(-1.0, min(1.0, sample))
        pcm.extend(struct.pack("<h", int(clamped * 32767.0)))
    with wave.open(str(resolved), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(bytes(pcm))
    return resolved


def _wakeup_lead_samples() -> list[float]:
    count = int(_SAMPLE_RATE * _WAKEUP_SEC)
    return [
        _WAKEUP_AMP * math.sin(2.0 * math.pi * 60.0 * (i / _SAMPLE_RATE))
        for i in range(count)
    ]


def _synthesize_screenshot_click(volume_scale: float = 1.0) -> list[float]:
    out = _wakeup_lead_samples()
    body_sec = 0.090
    total = int(_SAMPLE_RATE * body_sec)
    p1 = p2 = 0.0
    for i in range(total):
        t = i / _SAMPLE_RATE
        f1 = 480.0 + 780.0 * math.exp(-t / 0.012)
        p1 += 2.0 * math.pi * f1 / _SAMPLE_RATE
        e1 = min(1.0, t / 0.002) * math.exp(-t / 0.016)
        sig = (math.sin(p1) * 0.72 + math.sin(p1 * 1.95) * 0.28) * e1
        if t >= 0.034:
            dt = t - 0.034
            f2 = 420.0 + 620.0 * math.exp(-dt / 0.010)
            p2 += 2.0 * math.pi * f2 / _SAMPLE_RATE
            e2 = min(1.0, dt / 0.002) * math.exp(-dt / 0.014)
            sig += 0.65 * (math.sin(p2) * 0.75 + math.sin(p2 * 2.0) * 0.25) * e2
        out.append(0.62 * volume_scale * sig)
    return out


def _synthesize_notification_ding(volume_scale: float = 1.0) -> list[float]:
    out = _wakeup_lead_samples()
    body_sec = 0.290
    total = int(_SAMPLE_RATE * body_sec)
    for i in range(total):
        t = i / _SAMPLE_RATE
        env = min(1.0, t / 0.007) * math.exp(-t / 0.088)
        fundamental = math.sin(2.0 * math.pi * 587.33 * t)
        overtone = math.sin(2.0 * math.pi * 1174.66 * t) * 0.22
        out.append(0.48 * volume_scale * env * (fundamental + overtone))
    return out


def ensure_sound_assets(
    sounds_cache_dir: Path,
    workspace_roots: Sequence[Path] = (),
    *,
    volume: int = 100,
) -> tuple[Path, Path]:
    """Generate procedural v2 WAV cues inside ``sounds_cache_dir`` if not yet present."""
    resolved_dir = Path(sounds_cache_dir).expanduser().resolve(strict=False)
    q_vol = _quantize_volume(volume)
    scale = q_vol / 100.0
    click_path = resolved_dir / f"screenshot_click_v2_{q_vol}.wav"
    ding_path = resolved_dir / f"notification_ding_v2_{q_vol}.wav"
    if not click_path.is_file():
        _write_mono_wav(click_path, _synthesize_screenshot_click(scale), workspace_roots)
    if not ding_path.is_file():
        _write_mono_wav(ding_path, _synthesize_notification_ding(scale), workspace_roots)
    return click_path, ding_path


class SoundEffectsPlayer(QObject):
    """Plays gentle UI audio cues asynchronously respecting volume, mute, and Bluetooth wakes."""

    def __init__(
        self,
        sounds_cache_dir: Path,
        settings: AppSettings,
        *,
        workspace_roots_provider: Callable[[], Sequence[Path]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sounds_dir = Path(sounds_cache_dir).expanduser().resolve(strict=False)
        self._settings = settings
        self._ws_provider = workspace_roots_provider
        self._fx_cache: dict[str, QSoundEffect] = {}
        self._media_devices: QMediaDevices | None = None

    def update_settings(self, settings: AppSettings) -> None:
        """Update active ``AppSettings`` reference."""
        self._settings = settings

    def play_screenshot_click(self) -> bool:
        """Play the soft tactile camera click if sounds are enabled and unmuted."""
        return self._play_with_policy("click", force_audible=False)

    def play_notification_ding(self) -> bool:
        """Play the gentle notification chime if sounds are enabled and unmuted."""
        return self._play_with_policy("ding", force_audible=False)

    def play_test_click(self) -> bool:
        """Play a live test camera click when unmuted (minimum 15% volume floor)."""
        return self._play_with_policy("click", force_audible=True)

    def play_test_ding(self) -> bool:
        """Play a live test notification ding when unmuted (minimum 15% volume floor)."""
        return self._play_with_policy("ding", force_audible=True)

    def _effective_volume(self, *, force_audible: bool) -> int | None:
        if not self._settings.enable_sounds or self._settings.sound_muted:
            return None
        vol = normalize_volume(self._settings.sound_volume, 70)
        if force_audible:
            return max(vol, 15)
        return vol if vol > 0 else None

    def _play_with_policy(self, kind: str, *, force_audible: bool) -> bool:
        vol = self._effective_volume(force_audible=force_audible)
        if vol is None:
            return False
        roots = list(self._ws_provider()) if self._ws_provider is not None else []
        try:
            if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                click_path, ding_path = ensure_sound_assets(self._sounds_dir, roots, volume=vol)
                target = click_path if kind == "click" else ding_path
                return self._play_winsound(target)
            click_path, ding_path = ensure_sound_assets(self._sounds_dir, roots, volume=100)
            target = click_path if kind == "click" else ding_path
            return self._play_qt_effect(kind, target, vol / 100.0)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("Audio cue playback skipped (%s): %s", kind, exc)
            return False

    @staticmethod
    def _play_winsound(wav_path: Path) -> bool:
        import winsound

        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        winsound.PlaySound(str(wav_path), flags)
        return True

    def _play_qt_effect(self, kind: str, wav_path: Path, volume_float: float) -> bool:
        if (
            self._media_devices is None
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        ):
            try:
                self._media_devices = QMediaDevices(self)
                self._media_devices.audioOutputsChanged.connect(self._reset_qt_effects)
            except (RuntimeError, OSError):
                self._media_devices = None
        fx = self._fx_cache.get(kind)
        if fx is None or fx.source() != QUrl.fromLocalFile(str(wav_path)):
            fx = QSoundEffect(self)
            fx.setSource(QUrl.fromLocalFile(str(wav_path)))
            self._fx_cache[kind] = fx
        fx.setVolume(max(0.0, min(1.0, volume_float)))
        fx.play()
        return True

    def _reset_qt_effects(self) -> None:
        for fx in self._fx_cache.values():
            fx.stop()
            fx.deleteLater()
        self._fx_cache.clear()
