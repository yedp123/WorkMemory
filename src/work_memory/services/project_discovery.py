"""Read-only project discovery scanner using os.scandir() and exclusion filters."""

from __future__ import annotations

import logging
import os
import sys
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from work_memory.core.models import ProjectSuggestion
from work_memory.watcher.filters import ExclusionFilter, normalize_rel_path

logger = logging.getLogger(__name__)
MAX_DISCOVERY_DEPTH = 3
MIN_SUGGESTION_SCORE = 3

PROJECT_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".mb", ".ma", ".blend", ".ztl", ".psd", ".prproj", ".aep", ".unity",
    ".3mf", ".step", ".stp", ".hip", ".c4d", ".max", ".uproject", ".sln",
})
PROJECT_MANIFEST_FILES: frozenset[str] = frozenset({
    "pyproject.toml", "package.json", "cargo.toml", "go.mod", "pom.xml", "cmakelists.txt",
})
ASSET_SUBFOLDER_NAMES: frozenset[str] = frozenset({
    "scenes", "renders", "assets", "textures", "exports", "source", "src", "docs",
    "scripts", "models", "audio", "footage", "comps", "comp", "materials", "prefabs",
    "tests", "reference", "refs", "output", "outputs",
})
ASSET_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".fbx", ".obj", ".stl",
    ".glb", ".gltf", ".wav", ".mp3", ".mp4", ".mov", ".py", ".ts", ".js", ".cpp", ".cs",
})


def _norm_key(rel_path: str) -> str:
    norm = normalize_rel_path(rel_path)
    return norm.casefold() if sys.platform == "win32" else norm


def normalized_path_parts(path: Path) -> tuple[str, ...]:
    """Return resolved path segment parts (casefolded on Windows) for prefix matching."""
    resolved = path.expanduser().resolve(strict=False)
    return tuple(p.casefold() for p in resolved.parts) if sys.platform == "win32" else resolved.parts


@dataclass(slots=True)
class _Candidate:
    rel_path: str
    abs_path: Path
    depth: int
    score: int
    reasons: tuple[str, ...]
    has_own_identity: bool


def _list_dir_entries(path: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError as exc:
        logger.debug("Skipping unreadable directory %s: %s", path, exc)
        return []


def _peek_asset_subfolder(
    folder_path: Path, rel_path: str, exclusion_filter: ExclusionFilter
) -> tuple[bool, int]:
    """Inspect immediate files of a structural asset subfolder read-only."""
    has_project_file, asset_count = False, 0
    for entry in _list_dir_entries(folder_path):
        child_rel = f"{rel_path}/{entry.name}"
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        if exclusion_filter.is_ignored(child_rel, is_dir=False):
            continue
        ext = PurePosixPath(entry.name).suffix.lower()
        if ext in PROJECT_FILE_EXTENSIONS:
            has_project_file = True
        elif ext in ASSET_FILE_EXTENSIONS:
            asset_count += 1
    return has_project_file, asset_count


class ProjectDiscoveryScanner:
    """Read-only folder scorer that proposes candidate projects without auto-registering."""

    def __init__(self, exclusion_filter: ExclusionFilter | None = None) -> None:
        self._filter = exclusion_filter or ExclusionFilter()

    def scan_workspace(
        self,
        workspace_id: str,
        workspace_root: Path,
        *,
        registered_rel_paths: Iterable[str] = (),
        dismissed_rel_paths: Iterable[str] = (),
        max_depth: int = MAX_DISCOVERY_DEPTH,
    ) -> list[ProjectSuggestion]:
        """Scan ``workspace_root`` up to ``max_depth`` and return ranked project suggestions."""
        root = Path(workspace_root)
        if not root.is_dir():
            return []

        registered_keys = {_norm_key(p) for p in registered_rel_paths if normalize_rel_path(p)}
        excluded_keys = registered_keys | {_norm_key(p) for p in dismissed_rel_paths if normalize_rel_path(p)}

        candidates: list[_Candidate] = []
        queue: deque[tuple[Path, str, int]] = deque([(root, "", 0)])

        while queue:
            current_dir, prefix, depth = queue.popleft()
            subdirs: list[tuple[Path, str, str]] = []
            files: list[str] = []
            has_git = False

            for entry in _list_dir_entries(current_dir):
                name_lower = entry.name.lower()
                rel_path = f"{prefix}/{entry.name}" if prefix else entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name_lower == ".git":
                            has_git = True
                        elif not self._filter.is_ignored(rel_path, is_dir=True):
                            subdirs.append((Path(entry.path), rel_path, name_lower))
                    elif entry.is_file(follow_symlinks=False) and not self._filter.is_ignored(rel_path, is_dir=False):
                        files.append(entry.name)
                except OSError:
                    continue

            if depth > 0 and (cand := self._score_folder(prefix, current_dir, depth, files, subdirs, has_git)) is not None:
                candidates.append(cand)
            if depth < max_depth:
                for sub_path, sub_rel, _ in subdirs:
                    queue.append((sub_path, sub_rel, depth + 1))

        candidate_keys = {_norm_key(c.rel_path) for c in candidates} | registered_keys
        suggestions: list[ProjectSuggestion] = []
        for cand in candidates:
            if _norm_key(cand.rel_path) in excluded_keys:
                continue
            posix = PurePosixPath(cand.rel_path)
            parent_rel = "" if posix.parent == PurePosixPath(".") else posix.parent.as_posix()
            if (
                posix.name.lower() in ASSET_SUBFOLDER_NAMES
                and parent_rel
                and _norm_key(parent_rel) in candidate_keys
                and not cand.has_own_identity
            ):
                continue
            suggestions.append(
                ProjectSuggestion(
                    workspace_id=workspace_id, name=posix.name, rel_path=cand.rel_path,
                    abs_path=str(cand.abs_path), score=cand.score, reasons=cand.reasons,
                )
            )
        suggestions.sort(key=lambda item: (-item.score, item.rel_path.count("/"), item.rel_path.lower()))
        return suggestions

    def _score_folder(
        self, rel_path: str, folder_path: Path, depth: int,
        files: list[str], subdirs: list[tuple[Path, str, str]], has_git: bool,
    ) -> _Candidate | None:
        score, reasons = 0, []
        has_manifest = has_project_file = has_readme = False
        asset_file_count = 0

        for filename in files:
            lower_name, ext = filename.lower(), PurePosixPath(filename).suffix.lower()
            if ext in PROJECT_FILE_EXTENSIONS:
                has_project_file = True
            elif lower_name in PROJECT_MANIFEST_FILES:
                has_manifest = True
            elif lower_name.startswith("readme"):
                has_readme = True
            elif ext in ASSET_FILE_EXTENSIONS:
                asset_file_count += 1

        if has_project_file:
            score += 5
            reasons.append("project file")
        if has_manifest:
            score += 4
            reasons.append("project manifest")
        if has_git:
            score += 4
            reasons.append("git repository")
        if has_readme:
            score += 3
            reasons.append("README documentation")
        if asset_file_count >= 4:
            score += 2
            reasons.append("related asset files")

        asset_dirs = [item for item in subdirs if item[2] in ASSET_SUBFOLDER_NAMES]
        if len(asset_dirs) >= 2:
            score += 3
            reasons.append("grouped asset folders")
        elif len(asset_dirs) == 1:
            score += 1

        nested_project_file, nested_assets = False, 0
        for sub_path, sub_rel, _ in asset_dirs:
            found_proj, count = _peek_asset_subfolder(sub_path, sub_rel, self._filter)
            nested_project_file = nested_project_file or found_proj
            nested_assets += count
        if nested_project_file:
            score += 4
            reasons.append("asset folder project file")
        elif nested_assets >= 3 and "grouped asset folders" not in reasons:
            score += 2
            reasons.append("grouped asset files")

        if score < MIN_SUGGESTION_SCORE:
            return None
        return _Candidate(rel_path, folder_path, depth, score, tuple(reasons), has_git or has_manifest)
