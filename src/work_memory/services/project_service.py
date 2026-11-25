"""Application service for project registration, discovery, path matching, and status."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from work_memory.config.paths import AppPaths, resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.ids import utc_now_iso
from work_memory.core.models import (
    CoverStyle,
    DismissedSuggestion,
    ObservedEvent,
    Project,
    ProjectStatus,
    ProjectSuggestion,
    Workspace,
)
from work_memory.media.cover_storage import (
    delete_cover_file,
    resolve_cover_path,
    save_project_cover,
)
from work_memory.services.project_discovery import ProjectDiscoveryScanner, normalized_path_parts
from work_memory.storage.database import Database
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository
from work_memory.watcher.filters import ExclusionFilter, to_rel_path

if TYPE_CHECKING:
    from work_memory.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)
_COVER_CYCLE: tuple[CoverStyle, ...] = ("c1", "c2", "c3", "c4", "c5", "c6")


def _match_longest_project(
    target_parts: tuple[str, ...], project_parts: Sequence[tuple[Project, tuple[str, ...]]]
) -> Project | None:
    hits = [
        (len(pp), proj) for proj, pp in project_parts
        if len(target_parts) >= len(pp) and target_parts[: len(pp)] == pp
    ]
    return max(hits, key=lambda pair: pair[0])[1] if hits else None


class ProjectService:
    """Coordinates project lifecycle, read-only discovery, and nested path resolution."""

    def __init__(
        self, database: Database, event_bus: EventBus | None = None, *,
        workspace_service: WorkspaceService | None = None, exclusion_filter: ExclusionFilter | None = None,
        app_paths: AppPaths | None = None,
    ) -> None:
        self._bus, self._ws_service = event_bus, workspace_service
        self._app_paths = app_paths
        self._ws_repo = WorkspaceRepository(database)
        self._project_repo = ProjectRepository(database)
        self._ev_repo = ObservedEventRepository(database)
        self._scanner = ProjectDiscoveryScanner(exclusion_filter)
        self._lock = threading.RLock()

    def list_projects(self, *, workspace_id: str | None = None, status: ProjectStatus | None = None) -> list[Project]:
        """Return registered projects ordered by recent activity and creation time."""
        with self._lock:
            return self._project_repo.list_all(workspace_id=workspace_id, status=status)
    def get_project(self, project_id: str) -> Project | None:
        """Return a registered project by ID, or ``None`` if not found."""
        with self._lock:
            return self._project_repo.get(project_id)
    def search_projects(self, query: str) -> list[Project]:
        """Search all registered projects (including completed ones)."""
        with self._lock:
            return self._project_repo.search(query)
    def register_existing_project(
        self, folder_path: Path | str, name: str | None = None,
        description: str = "", cover_style: CoverStyle | None = None,
        *, created_at_utc: str | None = None,
    ) -> Project:
        """Register an existing directory as a project strictly read-only."""
        resolved = Path(folder_path).expanduser().resolve(strict=False)
        if not resolved.is_dir():
            raise FileNotFoundError(f"Project folder does not exist: {resolved}")
        project_name = (name or resolved.name or str(resolved)).strip()
        if not project_name:
            raise ValueError("Project name cannot be empty.")
        with self._lock:
            if self._project_repo.get_by_abs_path(str(resolved)) is not None:
                raise ValueError(f"Project folder is already registered: {resolved}")
            ws = self._find_containing_workspace(resolved)
            if ws is None:
                ws = self._ws_service.add_workspace(resolved, name=project_name, background_scan=True) if self._ws_service else self._ws_repo.create(Workspace(name=project_name, root_path=str(resolved), is_active=True))
                rel_path = ""
            else:
                rel_path = to_rel_path(resolved, Path(ws.root_path))
            if self._project_repo.get_by_workspace_rel_path(ws.id, rel_path) is not None:
                raise ValueError(f"Project folder is already registered: {resolved}")
            picked_cover = cover_style or _COVER_CYCLE[len(self._project_repo.list_all()) % len(_COVER_CYCLE)]
            created_ts = created_at_utc or utc_now_iso()
            project = Project(
                workspace_id=ws.id, name=project_name, rel_path=rel_path, description=description.strip(),
                cover_style=picked_cover, root_rel_path=rel_path, abs_path=str(resolved),
                created_at_utc=created_ts,
            )
            self._project_repo.create(project)
            self._backfill_workspace_events(ws)
            created = self._project_repo.get(project.id) or project
        self._emit(project=created, projects=True, suggestions=True, status=f"Project '{created.name}' registered (read-only)")
        return created
    def create_new_project(
        self, target_folder: Path | str, name: str | None = None, description: str = "",
        *, confirm_create_folder: bool = False, cover_style: CoverStyle | None = None,
        created_at_utc: str | None = None,
    ) -> Project:
        """Create an empty project folder ONLY when explicitly confirmed, then register it."""
        if not confirm_create_folder:
            raise PermissionError("Explicit user confirmation is required before creating a new project folder.")
        resolved = Path(target_folder).expanduser().resolve(strict=False)
        if resolved.exists() and not resolved.is_dir():
            raise FileExistsError(f"Target path exists and is not a folder: {resolved}")
        resolved.mkdir(parents=True, exist_ok=True)
        return self.register_existing_project(
            resolved, name=name or resolved.name, description=description,
            cover_style=cover_style, created_at_utc=created_at_utc,
        )
    def discover_suggestions(self, workspace_id: str | None = None) -> list[ProjectSuggestion]:
        """Scan registered workspaces read-only for unregistered, non-dismissed project folders."""
        with self._lock:
            workspaces = [ws] if (workspace_id and (ws := self._ws_repo.get_by_id(workspace_id))) else ([] if workspace_id else self._ws_repo.list_all())
            suggestions: list[ProjectSuggestion] = []
            for ws in workspaces:
                projects, dismissed = self._project_repo.list_all(workspace_id=ws.id), self._project_repo.list_dismissed(ws.id)
                suggestions.extend(self._scanner.scan_workspace(
                    ws.id, Path(ws.root_path),
                    registered_rel_paths=[p.root_rel_path or p.rel_path for p in projects],
                    dismissed_rel_paths=[d.rel_path for d in dismissed],
                ))
        suggestions.sort(key=lambda item: (-item.score, item.rel_path.count("/"), item.name.lower()))
        return suggestions
    def confirm_suggestion(
        self, suggestion: ProjectSuggestion, *, name: str | None = None,
        description: str = "", cover_style: CoverStyle | None = None,
    ) -> Project:
        """Explicitly register a user-confirmed project discovery suggestion."""
        return self.register_existing_project(Path(suggestion.abs_path), name=name or suggestion.name, description=description, cover_style=cover_style)
    def dismiss_suggestion(self, workspace_id: str, rel_path: str) -> DismissedSuggestion:
        """Dismiss a project discovery suggestion so it stays hidden across restarts."""
        with self._lock:
            record = self._project_repo.dismiss_suggestion(workspace_id, rel_path)
        self._emit(suggestions=True)
        return record
    def list_dismissed_suggestions(self, workspace_id: str | None = None) -> list[DismissedSuggestion]:
        """Return persisted dismissed project suggestions."""
        with self._lock:
            return self._project_repo.list_dismissed(workspace_id)
    def resolve_project_for_path(self, file_path: Path | str) -> Project | None:
        """Resolve the deepest registered project containing ``file_path`` via path segments."""
        project_parts, _ = self._load_project_parts()
        return _match_longest_project(normalized_path_parts(Path(file_path)), project_parts)
    def attach_project_ids(self, events: Sequence[ObservedEvent], workspace_roots: Mapping[str, Path] | None = None) -> None:
        """Populate ``project_id`` on newly observed events using longest-prefix path matching."""
        if not events:
            return
        project_parts, workspaces = self._load_project_parts()
        if not project_parts:
            return
        for ev in events:
            ws_root = (workspace_roots or {}).get(ev.workspace_id)
            if ws_root is None and (ws := workspaces.get(ev.workspace_id)) is not None:
                ws_root = Path(ws.root_path)
            if ws_root is not None and (matched := _match_longest_project(normalized_path_parts(ws_root / ev.rel_path), project_parts)):
                ev.project_id = matched.id
    def record_activity_for_events(self, events: Sequence[ObservedEvent]) -> None:
        """Update ``last_activity_utc`` for projects associated with observed events."""
        latest: dict[str, str] = {}
        for ev in events:
            if ev.project_id and (ev.project_id not in latest or ev.occurred_at_utc > latest[ev.project_id]):
                latest[ev.project_id] = ev.occurred_at_utc
        if not latest:
            return
        with self._lock:
            updated = [p for pid, ts in latest.items() if (p := self._project_repo.update_last_activity(pid, ts)) is not None]
        for proj in updated:
            self._emit(project=proj, projects=True)
    def toggle_status(self, project_id: str) -> Project | None:
        """Manually toggle a project between ``ongoing`` and ``completed``."""
        with self._lock:
            if (existing := self._project_repo.get(project_id)) is None:
                return None
            next_status: ProjectStatus = "completed" if existing.status == "ongoing" else "ongoing"
            updated = self._project_repo.update_status(project_id, next_status)
        if updated is not None:
            self._emit(project=updated, projects=True, status=f"{updated.name} marked as {updated.status}")
        return updated
    def set_status(self, project_id: str, status: ProjectStatus) -> Project | None:
        """Manually set project status without inferring completion from inactivity."""
        with self._lock:
            updated = self._project_repo.update_status(project_id, status)
        if updated is not None:
            self._emit(project=updated, projects=True)
        return updated
    def toggle_pin(self, project_id: str) -> bool:
        """Toggle pin state for ``project_id``, persist to DB, and emit ``project_updated``."""
        with self._lock:
            if (existing := self._project_repo.get(project_id)) is None:
                return False
            next_pinned = not existing.is_pinned
            self._project_repo.set_pinned(project_id, next_pinned)
            updated = self._project_repo.get(project_id)
        if updated is not None:
            self._emit(project=updated, projects=True, status=f"{updated.name} {'pinned' if next_pinned else 'unpinned'}")
        return next_pinned
    def update_details(
        self, project_id: str, *, name: str | None = None, description: str | None = None, cover_style: CoverStyle | None = None,
    ) -> Project | None:
        """Update editable project metadata."""
        with self._lock:
            updated = self._project_repo.update_details(project_id, name=name, description=description, cover_style=cover_style)
        if updated is not None:
            self._emit(project=updated, projects=True)
        return updated

    def set_project_cover(self, project_id: str, source_image_path: Path | str) -> Project:
        """Copy/resize ``source_image_path`` into app-owned ``covers/`` and update ``project_id``."""
        covers_dir = self._covers_dir()
        with self._lock:
            existing = self._project_repo.get(project_id)
            if existing is None:
                raise ValueError(f"Unknown project_id: {project_id!r}")
            roots = [Path(ws.root_path) for ws in self._ws_repo.list_all()]
            filename = save_project_cover(source_image_path, covers_dir, workspace_roots=roots)
            updated = self._project_repo.set_cover_image(project_id, filename)
            if updated is None:
                delete_cover_file(covers_dir, filename, workspace_roots=roots)
                raise ValueError(f"Unknown project_id: {project_id!r}")
            if existing.cover_image_path and existing.cover_image_path != filename:
                delete_cover_file(covers_dir, existing.cover_image_path, workspace_roots=roots)
        self._emit(project=updated, projects=True, status=f"Updated cover for '{updated.name}'")
        return updated

    def clear_project_cover(self, project_id: str) -> Project:
        """Reset a project's custom cover back to its default geometric motif."""
        covers_dir = self._covers_dir()
        with self._lock:
            existing = self._project_repo.get(project_id)
            if existing is None:
                raise ValueError(f"Unknown project_id: {project_id!r}")
            roots = [Path(ws.root_path) for ws in self._ws_repo.list_all()]
            updated = self._project_repo.set_cover_image(project_id, None) or existing
            if existing.cover_image_path:
                delete_cover_file(covers_dir, existing.cover_image_path, workspace_roots=roots)
        self._emit(project=updated, projects=True, status=f"Reset cover for '{updated.name}'")
        return updated

    def get_project_cover_path(self, project: Project) -> Path | None:
        """Return the resolved app-owned cover image path for ``project``, or ``None``."""
        return resolve_cover_path(self._covers_dir(), project.cover_image_path)

    def _covers_dir(self) -> Path:
        if self._app_paths is not None:
            return self._app_paths.covers_dir
        return resolve_app_paths().covers_dir
    def delete_project(self, project_id: str) -> bool:
        """Remove a project registration from Work Memory (original folder untouched)."""
        covers_dir = self._covers_dir()
        with self._lock:
            existing = self._project_repo.get(project_id)
            deleted = self._project_repo.delete(project_id)
            if deleted and existing is not None and existing.cover_image_path:
                roots = [Path(ws.root_path) for ws in self._ws_repo.list_all()]
                delete_cover_file(covers_dir, existing.cover_image_path, workspace_roots=roots)
        if deleted:
            msg = (
                f"Removed '{existing.name}' from Work Memory (files untouched)"
                if existing is not None
                else None
            )
            self._emit(projects=True, suggestions=True, status=msg)
        return deleted
    def list_project_events(self, project_id: str, *, limit: int = 100) -> list[ObservedEvent]:
        """Return recent observed filesystem events associated with ``project_id``."""
        with self._lock:
            return self._ev_repo.list_by_project(project_id, limit=limit)

    def _load_project_parts(self) -> tuple[list[tuple[Project, tuple[str, ...]]], dict[str, Workspace]]:
        with self._lock:
            projects, workspaces = self._project_repo.list_all(), {ws.id: ws for ws in self._ws_repo.list_all()}
        parts = []
        for proj in projects:
            if proj.abs_path:
                parts.append((proj, normalized_path_parts(Path(proj.abs_path))))
            elif (ws := workspaces.get(proj.workspace_id)) is not None:
                parts.append((proj, normalized_path_parts(Path(ws.root_path) / proj.rel_path if proj.rel_path else Path(ws.root_path))))
        return parts, workspaces
    def _find_containing_workspace(self, folder_path: Path) -> Workspace | None:
        target_parts = normalized_path_parts(folder_path)
        matches = [
            (len(wp), ws) for ws in self._ws_repo.list_all()
            if len(target_parts) >= len(wp := normalized_path_parts(Path(ws.root_path))) and target_parts[: len(wp)] == wp
        ]
        return max(matches, key=lambda pair: pair[0])[1] if matches else None
    def _backfill_workspace_events(self, workspace: Workspace) -> None:
        if not (events := self._ev_repo.list_by_workspace(workspace.id, limit=5000)):
            return
        original_ids = {ev.id: ev.project_id for ev in events}
        self.attach_project_ids(events, {workspace.id: Path(workspace.root_path)})
        if updates := [(ev.project_id, ev.id) for ev in events if ev.project_id != original_ids[ev.id]]:
            self._ev_repo.assign_project_ids(updates)
        self.record_activity_for_events(events)
    def _emit(
        self, *, project: Project | None = None, projects: bool = False, suggestions: bool = False, status: str | None = None,
    ) -> None:
        if self._bus is None:
            return
        if project is not None:
            self._bus.project_updated.emit(project)
        if status:
            self._bus.status_message.emit(status)
        if projects:
            self._bus.projects_changed.emit()
        if suggestions:
            self._bus.suggestions_changed.emit()
