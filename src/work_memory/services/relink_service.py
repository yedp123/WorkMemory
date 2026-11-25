"""Resilient read-only project and workspace folder relinking service."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from work_memory.core.event_bus import EventBus
from work_memory.core.models import Project
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository


def is_project_folder_missing(project: Project) -> bool:
    """Return ``True`` when ``project.abs_path`` is set but missing on disk."""
    raw = project.abs_path.strip()
    if not raw:
        return False
    return not Path(raw).is_dir()


def to_project_relative_path(raw_rel: str, project_rel_root: str) -> str:
    """Normalize a workspace- or project-relative POSIX path to project-relative."""
    norm = raw_rel.replace("\\", "/").strip("/")
    root = project_rel_root.replace("\\", "/").strip("/")
    if not norm:
        return ""
    if root and norm == root:
        return ""
    if root and norm.lower().startswith(f"{root.lower()}/"):
        return norm[len(root) + 1 :]
    return PurePosixPath(norm).as_posix()


class RelinkService:
    """Reconnects moved/renamed project or workspace folders without altering user files."""

    def __init__(
        self,
        database: Database,
        event_bus: EventBus | None = None,
        *,
        workspace_service: WorkspaceService | None = None,
    ) -> None:
        self._bus = event_bus
        self._ws_service = workspace_service
        self._ws_repo = WorkspaceRepository(database)
        self._proj_repo = ProjectRepository(database)
        self._ev_repo = ObservedEventRepository(database)
        self._cap_repo = CaptureRepository(database)

    def relink_project(self, project_id: str, new_folder: Path | str) -> Project:
        """Update stored folder path for ``project_id`` without modifying disk files."""
        resolved = Path(new_folder).expanduser().resolve(strict=False)
        if not resolved.is_dir():
            raise FileNotFoundError(f"Project folder does not exist: {resolved}")
        existing = self._proj_repo.get(project_id)
        if existing is None:
            raise ValueError(f"Unknown project_id: {project_id!r}")

        next_ws_id: str | None = None
        next_rel: str | None = None
        for ws in self._ws_repo.list_all():
            ws_root = Path(ws.root_path).expanduser().resolve(strict=False)
            if resolved.is_relative_to(ws_root):
                rel = resolved.relative_to(ws_root).as_posix()
                next_ws_id = ws.id
                next_rel = "" if rel == "." else rel
                break

        updated = self._proj_repo.update_location(
            project_id,
            abs_path=str(resolved),
            rel_path=next_rel,
            workspace_id=next_ws_id,
        )
        if updated is None:
            raise ValueError(f"Failed to update project_id: {project_id!r}")
        if self._bus is not None:
            self._bus.project_updated.emit(updated)
            self._bus.projects_changed.emit()
        return updated

    def relink_workspace(
        self,
        workspace_id: str,
        new_root: Path | str,
        *,
        background_scan: bool = False,
    ) -> int:
        """Relink a moved workspace root and all its child projects, returning project count."""
        resolved = Path(new_root).expanduser().resolve(strict=False)
        if not resolved.is_dir():
            raise FileNotFoundError(f"Workspace folder does not exist: {resolved}")
        existing_ws = self._ws_repo.get_by_id(workspace_id)
        if existing_ws is None:
            raise ValueError(f"Unknown workspace_id: {workspace_id!r}")

        conflict = self._ws_repo.get_by_root_path(str(resolved))
        if conflict is not None and conflict.id != workspace_id:
            raise ValueError(f"Workspace is already registered at: {resolved}")

        self._ws_repo.update_root_path(workspace_id, str(resolved))
        projects = self._proj_repo.list_all(workspace_id=workspace_id)
        for proj in projects:
            rel = (proj.root_rel_path or proj.rel_path).strip("/")
            next_abs = str(resolved / rel) if rel else str(resolved)
            self._proj_repo.update_location(proj.id, abs_path=next_abs)

        if self._ws_service is not None:
            self._ws_service.rebind_workspace_root(
                workspace_id, resolved, background_scan=background_scan
            )
        if self._bus is not None:
            self._bus.projects_changed.emit()
            self._bus.workspaces_changed.emit()
        return len(projects)

    def check_project_missing_files(self, project_id: str) -> list[str]:
        """Return sorted project-relative POSIX paths recorded in DB but missing on disk."""
        project = self._proj_repo.get(project_id)
        if project is None:
            raise ValueError(f"Unknown project_id: {project_id!r}")

        proj_root = Path(project.abs_path).expanduser().resolve(strict=False) if project.abs_path.strip() else None
        rel_root = project.root_rel_path or project.rel_path

        referenced: set[str] = set()
        deleted_paths: set[str] = set()
        for ev in self._ev_repo.list_by_project(project_id, limit=5000):
            rel = to_project_relative_path(ev.rel_path, rel_root)
            if not rel:
                continue
            if ev.event_type == "deleted":
                deleted_paths.add(rel)
            else:
                deleted_paths.discard(rel)
                referenced.add(rel)

        for cap in self._cap_repo.list_recent(project_id=project_id, limit=5000):
            if cap.rel_path:
                rel = to_project_relative_path(cap.rel_path, rel_root)
                if rel:
                    referenced.add(rel)

        active_refs = sorted(referenced - deleted_paths)
        if proj_root is None or not proj_root.is_dir():
            return active_refs
        return [rel for rel in active_refs if not (proj_root / rel).exists()]
