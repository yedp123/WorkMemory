"""Read-only path normalization and configurable exclusion rules."""

from __future__ import annotations

import os
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    "*.tmp",
    "*.bak",
    "~$*",
    "*.swp",
    ".DS_Store",
    "Thumbs.db",
    ".git/objects/",
    "node_modules/",
    "Library/",
    "Temp/",
    "Cache/",
    "Auto-Save/",
)


def normalize_rel_path(rel_path: str) -> str:
    """Normalize a relative path into clean POSIX format without leading/trailing slashes."""
    posix = rel_path.replace("\\", "/").strip("/")
    while posix.startswith("./"):
        posix = posix[2:]
    if posix in ("", "."):
        return ""
    return PurePosixPath(posix).as_posix()


def to_rel_path(path: Path | str, workspace_root: Path | str) -> str:
    """Convert an OS path inside ``workspace_root`` to a POSIX ``rel_path``.

    Raises ``ValueError`` if ``path`` lies outside ``workspace_root``.
    """
    abs_target = Path(os.path.abspath(Path(path).expanduser()))
    abs_root = Path(os.path.abspath(Path(workspace_root).expanduser()))
    try:
        rel = abs_target.relative_to(abs_root)
    except ValueError:
        resolved_target = abs_target.resolve(strict=False)
        resolved_root = abs_root.resolve(strict=False)
        rel = resolved_target.relative_to(resolved_root)

    posix = rel.as_posix()
    return "" if posix == "." else posix


def _contains_subsequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    limit = len(haystack) - len(needle) + 1
    return any(haystack[idx : idx + len(needle)] == needle for idx in range(limit))


class ExclusionFilter:
    """Configurable filter suppressing temp, backup, lock, and cache noise."""

    def __init__(
        self,
        patterns: Iterable[str] | None = None,
        extra_patterns: Iterable[str] = (),
    ) -> None:
        base = list(DEFAULT_IGNORE_PATTERNS) if patterns is None else list(patterns)
        combined = [p.strip() for p in (*base, *extra_patterns) if p and p.strip()]
        self._patterns: tuple[str, ...] = tuple(dict.fromkeys(combined))

        dir_segments: list[tuple[str, ...]] = []
        path_globs: list[str] = []
        name_globs: list[str] = []

        for pattern in self._patterns:
            norm = pattern.replace("\\", "/")
            if norm.endswith("/"):
                segs = tuple(part.lower() for part in norm.strip("/").split("/") if part)
                if segs:
                    dir_segments.append(segs)
            elif "/" in norm:
                path_globs.append(norm.lstrip("/").lower())
            else:
                name_globs.append(norm.lower())

        self._dir_segments = tuple(dir_segments)
        self._path_globs = tuple(path_globs)
        self._name_globs = tuple(name_globs)

    @property
    def patterns(self) -> tuple[str, ...]:
        """Return active exclusion pattern strings."""
        return self._patterns

    def is_ignored_directory(self, rel_path: str) -> bool:
        """Return ``True`` if a directory ``rel_path`` should be pruned from observation."""
        return self.is_ignored(rel_path, is_dir=True)

    def is_ignored(self, rel_path: str, *, is_dir: bool = False) -> bool:
        """Return ``True`` if ``rel_path`` matches any configured exclusion rule."""
        norm = normalize_rel_path(rel_path)
        if not norm:
            return False

        parts = tuple(part for part in norm.split("/") if part)
        lower_parts = tuple(part.lower() for part in parts)
        dir_parts = lower_parts if is_dir else lower_parts[:-1]

        for segs in self._dir_segments:
            if _contains_subsequence(dir_parts, segs):
                return True

        lower_norm = norm.lower()
        for glob in self._path_globs:
            if fnmatchcase(lower_norm, glob):
                return True

        if not is_dir:
            filename = lower_parts[-1]
            for glob in self._name_globs:
                if fnmatchcase(filename, glob):
                    return True

        return False
