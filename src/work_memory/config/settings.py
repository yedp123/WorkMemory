"""Typed application settings persisted strictly inside app-owned local storage."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from work_memory.config.paths import AppPaths, assert_not_inside_monitored_workspace

logger = logging.getLogger(__name__)
DEFAULT_REMINDER_MESSAGE = "Remember to save your work"
VALID_GALLERY_VIEW_MODES: tuple[str, ...] = ("list", "small", "medium", "large")
VALID_THEME_MODES: tuple[str, ...] = ("dark", "light")


def normalize_gallery_view_mode(raw: object) -> str:
    """Return a valid gallery view mode, falling back to ``'medium'``."""
    if isinstance(raw, str):
        candidate = raw.strip().lower()
        if candidate in VALID_GALLERY_VIEW_MODES:
            return candidate
    return "medium"


def normalize_theme_mode(raw: object) -> str:
    """Return a valid UI theme mode (``'dark'`` or ``'light'``), defaulting to ``'dark'``."""
    if isinstance(raw, str):
        candidate = raw.strip().lower()
        if candidate in VALID_THEME_MODES:
            return candidate
    return "dark"


def normalize_volume(raw: object, default: int = 70) -> int:
    """Clamp an integer UI sound volume strictly within ``0..100``."""
    if isinstance(raw, bool):
        return default
    try:
        val = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, min(val, 100))


def normalize_interval(
    raw: object,
    default: int,
    *,
    min_positive: int = 1,
    max_value: int = 999,
) -> int:
    """Validate an interval setting allowing ``0`` (disabled) or ``min_positive..max_value``."""
    if isinstance(raw, bool):
        return default
    try:
        val = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if val < 0:
        return default
    if val == 0:
        return 0
    return max(min_positive, min(val, max_value))


def normalize_reminder_message(raw: object) -> str:
    """Return a trimmed reminder message or the safe default when blank."""
    if raw is None:
        return DEFAULT_REMINDER_MESSAGE
    text = str(raw).strip()
    return text or DEFAULT_REMINDER_MESSAGE


@dataclass(slots=True)
class AppSettings:
    """User-configurable notification, tray, hotkey, startup, and UI preferences."""

    new_file_notifications: bool = True
    repeated_save_interval: int = 5
    notification_duration_sec: int = 60
    save_reminder_minutes: int = 30
    save_reminder_message: str = DEFAULT_REMINDER_MESSAGE
    minimize_to_tray_on_close: bool = True
    global_hotkey_enabled: bool = True
    gallery_view_mode: str = "medium"
    launch_at_startup: bool = False
    enable_sounds: bool = True
    sound_volume: int = 70
    sound_muted: bool = False
    theme_mode: str = "dark"

    def __post_init__(self) -> None:
        self.repeated_save_interval = normalize_interval(
            self.repeated_save_interval, 5, min_positive=1, max_value=999
        )
        self.notification_duration_sec = normalize_interval(
            self.notification_duration_sec, 60, min_positive=5, max_value=3600
        )
        self.save_reminder_minutes = normalize_interval(
            self.save_reminder_minutes, 30, min_positive=1, max_value=480
        )
        self.save_reminder_message = normalize_reminder_message(self.save_reminder_message)
        self.gallery_view_mode = normalize_gallery_view_mode(self.gallery_view_mode)
        self.sound_volume = normalize_volume(self.sound_volume, 70)
        self.sound_muted = bool(self.sound_muted)
        self.theme_mode = normalize_theme_mode(self.theme_mode)


def load_settings(app_paths: AppPaths) -> AppSettings:
    """Load ``AppSettings`` from ``app_paths.base_dir / 'settings.json'``, or defaults."""
    settings_path = app_paths.base_dir / "settings.json"
    if not settings_path.is_file():
        return AppSettings()
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable settings %s: %s", settings_path, exc)
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()

    defaults = AppSettings()
    return AppSettings(
        new_file_notifications=bool(data.get("new_file_notifications", defaults.new_file_notifications)),
        repeated_save_interval=normalize_interval(
            data.get("repeated_save_interval"), defaults.repeated_save_interval, min_positive=1, max_value=999
        ),
        notification_duration_sec=normalize_interval(
            data.get("notification_duration_sec"), defaults.notification_duration_sec, min_positive=5, max_value=3600
        ),
        save_reminder_minutes=normalize_interval(
            data.get("save_reminder_minutes"), defaults.save_reminder_minutes, min_positive=1, max_value=480
        ),
        save_reminder_message=normalize_reminder_message(data.get("save_reminder_message")),
        minimize_to_tray_on_close=bool(data.get("minimize_to_tray_on_close", defaults.minimize_to_tray_on_close)),
        global_hotkey_enabled=bool(data.get("global_hotkey_enabled", defaults.global_hotkey_enabled)),
        gallery_view_mode=normalize_gallery_view_mode(data.get("gallery_view_mode", defaults.gallery_view_mode)),
        launch_at_startup=bool(data.get("launch_at_startup", defaults.launch_at_startup)),
        enable_sounds=bool(data.get("enable_sounds", defaults.enable_sounds)),
        sound_volume=normalize_volume(data.get("sound_volume", defaults.sound_volume), defaults.sound_volume),
        sound_muted=bool(data.get("sound_muted", defaults.sound_muted)),
        theme_mode=normalize_theme_mode(data.get("theme_mode", defaults.theme_mode)),
    )


def save_settings(
    app_paths: AppPaths,
    settings: AppSettings,
    *,
    workspace_roots: Sequence[Path] = (),
) -> Path:
    """Persist ``settings`` to ``app_paths.base_dir / 'settings.json'`` safely."""
    settings_path = (app_paths.base_dir / "settings.json").expanduser().resolve(strict=False)
    assert_not_inside_monitored_workspace(settings_path, workspace_roots)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return settings_path
