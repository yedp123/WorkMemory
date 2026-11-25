"""Application bootstrap, logging setup, and service-graph assembly."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from work_memory.config import paths as cfg_paths
from work_memory.config.settings import AppSettings, load_settings
from work_memory.core.event_bus import EventBus
from work_memory.media.sound_effects import SoundEffectsPlayer
from work_memory.media.thumbnail_service import ThumbnailService
from work_memory.services.backup_service import BackupService
from work_memory.services.calendar_service import CalendarService
from work_memory.services.capture_service import CaptureService
from work_memory.services.history_service import HistoryService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.notification_service import NotificationService
from work_memory.services.project_service import ProjectService
from work_memory.services.relink_service import RelinkService
from work_memory.services.startup_service import StartupService
from work_memory.services.summary_service import SummaryService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database


@dataclass(slots=True)
class AppServices:
    """Assembled core application services wired for ``MainWindow``."""

    paths: cfg_paths.AppPaths
    db: Database
    bus: EventBus
    settings: AppSettings
    workspace_service: WorkspaceService
    project_service: ProjectService
    history_service: HistoryService
    capture_service: CaptureService
    notification_service: NotificationService
    calendar_service: CalendarService
    summary_service: SummaryService
    relink_service: RelinkService
    manifest_service: ManifestService
    backup_service: BackupService
    startup_service: StartupService
    thumbnail_service: ThumbnailService
    sound_player: SoundEffectsPlayer


def configure_logging(logs_dir: Path) -> None:
    """Initialize rotating file logging (and stream logging when stderr exists)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            logs_dir / "work_memory.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def bootstrap(base_dir: Path | None = None) -> tuple[cfg_paths.AppPaths, Database, EventBus]:
    """Prepare app-owned paths, logging, database migrations, and EventBus."""
    paths = cfg_paths.resolve_app_paths(base_dir=base_dir)
    paths.ensure_directories()
    configure_logging(paths.logs_dir)
    db = Database(paths.db_path)
    db.run_migrations()
    return paths, db, EventBus()


def build_app_services(base_dir: Path | None = None) -> AppServices:
    """Bootstrap storage and instantiate the full application service graph."""
    paths, db, bus = bootstrap(base_dir=base_dir)
    settings = load_settings(paths)
    ws_svc = WorkspaceService(database=db, event_bus=bus)
    cal_svc = CalendarService(database=db, event_bus=bus)
    proj_svc = ProjectService(
        database=db, event_bus=bus, workspace_service=ws_svc, app_paths=paths
    )
    ws_svc.set_project_service(proj_svc)
    hist_svc = HistoryService(database=db, event_bus=bus, app_paths=paths)
    roots_fn = lambda: [Path(ws.root_path) for ws in ws_svc.cached_workspaces()]
    thumb_svc = ThumbnailService(
        paths.thumbs_cache_dir,
        path_resolver=lambda r, p, w: hist_svc.resolve_file_path(r, project_id=p, workspace_id=w).resolved_path,
        workspace_roots_provider=roots_fn,
    )
    sound_player = SoundEffectsPlayer(
        paths.sounds_cache_dir,
        settings,
        workspace_roots_provider=roots_fn,
    )

    return AppServices(
        paths=paths,
        db=db,
        bus=bus,
        settings=settings,
        workspace_service=ws_svc,
        project_service=proj_svc,
        history_service=hist_svc,
        capture_service=CaptureService(
            database=db, app_paths=paths, event_bus=bus, workspace_service=ws_svc
        ),
        notification_service=NotificationService(
            settings, project_service=proj_svc, event_bus=bus
        ),
        calendar_service=cal_svc,
        summary_service=SummaryService(database=db),
        relink_service=RelinkService(database=db, event_bus=bus, workspace_service=ws_svc),
        manifest_service=ManifestService(database=db, app_paths=paths, event_bus=bus),
        backup_service=BackupService(
            database=db,
            app_paths=paths,
            event_bus=bus,
            workspace_service=ws_svc,
            calendar_service=cal_svc,
        ),
        startup_service=StartupService(),
        thumbnail_service=thumb_svc,
        sound_player=sound_player,
    )
