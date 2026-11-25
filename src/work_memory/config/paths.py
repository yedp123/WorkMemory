"""Application-owned local storage paths and monitored workspace write guards."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
_CLOUD_DIR_NAMES = frozenset({"onedrive", "dropbox", "google drive", "googledrive", "iclouddrive", "nextcloud"})


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved app-owned storage paths isolated from user project folders."""

    base_dir: Path
    db_path: Path
    attachments_dir: Path
    covers_dir: Path
    drafts_dir: Path
    logs_dir: Path
    models_dir: Path
    thumbs_cache_dir: Path
    sounds_cache_dir: Path

    def ensure_directories(self) -> None:
        """Create Work Memory's own storage directories if they do not exist."""
        for directory in (
            self.base_dir,
            self.attachments_dir,
            self.covers_dir,
            self.drafts_dir,
            self.logs_dir,
            self.models_dir,
            self.thumbs_cache_dir,
            self.sounds_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _default_app_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "WorkMemory"
    return Path.home() / "AppData" / "Local" / "WorkMemory"


def default_bootstrap_file() -> Path:
    """Return the default ``bootstrap.json`` pointer path in ``%LOCALAPPDATA%\\WorkMemory``."""
    return _default_app_root() / "bootstrap.json"


def is_likely_cloud_synced_path(path: Path) -> bool:
    """Return ``True`` if any path segment matches a common cloud-sync folder name."""
    parts = {part.strip().lower() for part in path.expanduser().parts if part.strip()}
    return bool(parts & _CLOUD_DIR_NAMES)


def set_custom_data_dir(
    new_dir: Path,
    *,
    workspace_roots: Sequence[Path] = (),
    bootstrap_file: Path | None = None,
) -> Path:
    """Persist ``data_dir`` in ``bootstrap.json`` after verifying workspace safety."""
    resolved_dir = Path(new_dir).expanduser().resolve(strict=False)
    assert_not_inside_monitored_workspace(resolved_dir, list(workspace_roots))
    target = (bootstrap_file or default_bootstrap_file()).expanduser().resolve(strict=False)
    assert_not_inside_monitored_workspace(target, list(workspace_roots))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"data_dir": str(resolved_dir)}, indent=2), encoding="utf-8")
    return target


def resolve_app_paths(
    base_dir: Path | None = None,
    *,
    bootstrap_file: Path | None = None,
) -> AppPaths:
    """Resolve app-owned paths under %LOCALAPPDATA%\\WorkMemory, bootstrap.json, or base_dir."""
    if base_dir is not None:
        root = base_dir
    else:
        root = _default_app_root()
        pointer = (bootstrap_file or default_bootstrap_file()).expanduser()
        if pointer.is_file():
            try:
                raw = json.loads(pointer.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("data_dir"), str) and raw["data_dir"].strip():
                    root = Path(raw["data_dir"].strip())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Ignoring unreadable bootstrap pointer %s: %s", pointer, exc)

    resolved_root = root.expanduser().resolve(strict=False)
    return AppPaths(
        base_dir=resolved_root,
        db_path=resolved_root / "work_memory.db",
        attachments_dir=resolved_root / "attachments",
        covers_dir=resolved_root / "covers",
        drafts_dir=resolved_root / "drafts",
        logs_dir=resolved_root / "logs",
        models_dir=resolved_root / "models",
        thumbs_cache_dir=resolved_root / "cache" / "thumbs",
        sounds_cache_dir=resolved_root / "cache" / "sounds",
    )


def assert_not_inside_monitored_workspace(
    target: Path,
    workspace_roots: list[Path],
) -> None:
    """Raise PermissionError if target (after symlink resolution) lies inside a workspace."""
    expanded_target = target.expanduser()
    resolved_target = expanded_target.resolve(strict=False)
    raw_target = Path(os.path.abspath(expanded_target))

    for root in workspace_roots:
        expanded_root = root.expanduser()
        resolved_root = expanded_root.resolve(strict=False)
        raw_root = Path(os.path.abspath(expanded_root))

        if (
            resolved_target.is_relative_to(resolved_root)
            or resolved_target.is_relative_to(raw_root)
            or raw_target.is_relative_to(resolved_root)
            or raw_target.is_relative_to(raw_root)
        ):
            raise PermissionError(
                f"Write target '{target}' is inside monitored workspace '{root}'."
            )
