"""Read-only path resolution for opening recorded files in their default application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from work_memory.core.models import Project, Workspace
from work_memory.services.relink_service import to_project_relative_path
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository


@dataclass(frozen=True, slots=True)
class ResolvedFileResult:
    """Result of resolving a stored relative path against project/workspace roots read-only."""

    found: bool
    resolved_path: Path | None
    display_name: str


@dataclass(frozen=True, slots=True)
class RevealTargetResult:
    """Resolved target path and bounding root for safe folder-reveal fallback."""

    target_path: Path | None
    root_bound: Path | None
    display_name: str


def strip_sequence_suffix(rel_path: str) -> str:
    """Return the leading relative file path from coalesced image-sequence labels."""
    raw = rel_path.strip()
    if " .. " in raw:
        return raw.split(" .. ", 1)[0].strip()
    return raw


def _is_unsafe_relative(raw_first: str, norm_posix: str) -> bool:
    if not norm_posix or norm_posix.startswith("/"):
        return True
    if Path(raw_first).is_absolute():
        return True
    first_seg = norm_posix.split("/", 1)[0]
    if ":" in first_seg:
        return True
    return ".." in PurePosixPath(norm_posix).parts


def _safe_join(root: Path, rel_posix: str) -> Path | None:
    norm = rel_posix.replace("\\", "/").strip("/")
    if _is_unsafe_relative(rel_posix, norm):
        return None
    resolved_root = root.expanduser().resolve(strict=False)
    candidate = (resolved_root / norm).resolve(strict=False)
    if not candidate.is_relative_to(resolved_root):
        return None
    return candidate


def resolve_relative_file(
    rel_path: str,
    *,
    project: Project | None = None,
    workspace: Workspace | None = None,
) -> ResolvedFileResult:
    """Resolve ``rel_path`` read-only against ``project`` and/or ``workspace`` roots.

    Never opens file contents or writes to disk; blocks ``..`` path traversal.
    """
    raw_first = strip_sequence_suffix(rel_path)
    norm = raw_first.replace("\\", "/").strip("/")
    display_name = PurePosixPath(norm).name or raw_first or rel_path
    if _is_unsafe_relative(raw_first, norm):
        return ResolvedFileResult(found=False, resolved_path=None, display_name=display_name)

    candidates: list[tuple[Path, str]] = []
    if project is not None and project.abs_path.strip():
        proj_root = Path(project.abs_path)
        for prefix in (project.root_rel_path, project.rel_path):
            if prefix:
                stripped = to_project_relative_path(norm, prefix)
                if stripped and stripped != norm:
                    candidates.append((proj_root, stripped))
        candidates.append((proj_root, norm))

    if workspace is not None and workspace.root_path.strip():
        candidates.append((Path(workspace.root_path), norm))

    seen: set[tuple[str, str]] = set()
    for root, rel in candidates:
        key = (str(root), rel)
        if key in seen:
            continue
        seen.add(key)
        resolved = _safe_join(root, rel)
        if resolved is not None and resolved.is_file():
            return ResolvedFileResult(
                found=True, resolved_path=resolved, display_name=display_name
            )

    return ResolvedFileResult(found=False, resolved_path=None, display_name=display_name)


def _lookup_project_and_workspace(
    *,
    project_repo: ProjectRepository,
    workspace_repo: WorkspaceRepository,
    event_repo: ObservedEventRepository | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    event_id: str | None = None,
) -> tuple[Project | None, Workspace | None]:
    pid = project_id or None
    wid = workspace_id or None
    if (
        (pid is None or wid is None)
        and event_id
        and event_repo is not None
        and (ev := event_repo.get(event_id)) is not None
    ):
        pid = pid or ev.project_id
        wid = wid or ev.workspace_id
    project = project_repo.get(pid) if pid else None
    ws_lookup_id = wid or (project.workspace_id if project is not None else None)
    workspace = workspace_repo.get_by_id(ws_lookup_id) if ws_lookup_id else None
    return project, workspace


def resolve_file_from_repos(
    rel_path: str,
    *,
    project_repo: ProjectRepository,
    workspace_repo: WorkspaceRepository,
    event_repo: ObservedEventRepository | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    event_id: str | None = None,
) -> ResolvedFileResult:
    """Look up owning project/workspace records and resolve ``rel_path`` read-only."""
    project, workspace = _lookup_project_and_workspace(
        project_repo=project_repo, workspace_repo=workspace_repo,
        event_repo=event_repo, project_id=project_id, workspace_id=workspace_id, event_id=event_id,
    )
    return resolve_relative_file(rel_path, project=project, workspace=workspace)


def resolve_reveal_target(
    rel_path: str,
    *,
    project: Project | None = None,
    workspace: Workspace | None = None,
) -> RevealTargetResult:
    """Resolve a target path (and bounding root) for revealing a file or its parent folder."""
    raw_first = strip_sequence_suffix(rel_path)
    norm = raw_first.replace("\\", "/").strip("/")
    display_name = PurePosixPath(norm).name or raw_first or rel_path
    if _is_unsafe_relative(raw_first, norm):
        return RevealTargetResult(target_path=None, root_bound=None, display_name=display_name)

    candidates: list[tuple[Path, str]] = []
    if project is not None and project.abs_path.strip():
        proj_root = Path(project.abs_path)
        for prefix in (project.root_rel_path, project.rel_path):
            if prefix:
                stripped = to_project_relative_path(norm, prefix)
                if stripped and stripped != norm:
                    candidates.append((proj_root, stripped))
        candidates.append((proj_root, norm))

    if workspace is not None and workspace.root_path.strip():
        candidates.append((Path(workspace.root_path), norm))

    seen: set[tuple[str, str]] = set()
    unique_candidates: list[tuple[Path, str]] = []
    for root, rel in candidates:
        key = (str(root), rel)
        if key not in seen:
            seen.add(key)
            unique_candidates.append((root, rel))

    for root, rel in unique_candidates:
        resolved = _safe_join(root, rel)
        if resolved is not None and resolved.is_file():
            return RevealTargetResult(
                target_path=resolved,
                root_bound=root.expanduser().resolve(strict=False),
                display_name=display_name,
            )

    for root, rel in unique_candidates:
        resolved_root = root.expanduser().resolve(strict=False)
        if resolved_root.is_dir():
            resolved = _safe_join(root, rel)
            if resolved is not None:
                return RevealTargetResult(
                    target_path=resolved,
                    root_bound=resolved_root,
                    display_name=display_name,
                )

    return RevealTargetResult(target_path=None, root_bound=None, display_name=display_name)


def resolve_reveal_from_repos(
    rel_path: str,
    *,
    project_repo: ProjectRepository,
    workspace_repo: WorkspaceRepository,
    event_repo: ObservedEventRepository | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    event_id: str | None = None,
) -> RevealTargetResult:
    """Look up owning project/workspace records and resolve a folder-reveal target."""
    project, workspace = _lookup_project_and_workspace(
        project_repo=project_repo, workspace_repo=workspace_repo,
        event_repo=event_repo, project_id=project_id, workspace_id=workspace_id, event_id=event_id,
    )
    return resolve_reveal_target(rel_path, project=project, workspace=workspace)
