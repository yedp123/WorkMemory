"""Safe online SQLite backup, restore, and custom data-directory relocation."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from work_memory.config.paths import (
    AppPaths,
    _default_app_root,
    assert_not_inside_monitored_workspace,
    set_custom_data_dir,
)
from work_memory.core.event_bus import EventBus
from work_memory.core.ids import utc_now_iso
from work_memory.services.archive_safety import safe_archive_member_path, validate_zip_members
from work_memory.services.calendar_service import CalendarService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository

_SQLITE_HEADER = b"SQLite format 3\x00"


class BackupService:
    """Handles WAL-safe SQLite backups, verified restores, and data-dir relocation."""

    def __init__(
        self,
        database: Database,
        app_paths: AppPaths,
        event_bus: EventBus | None = None,
        *,
        workspace_service: WorkspaceService | None = None,
        calendar_service: CalendarService | None = None,
    ) -> None:
        self._db = database
        self._paths = app_paths
        self._bus = event_bus
        self._ws_service = workspace_service
        self._cal_service = calendar_service
        self._ws_repo = WorkspaceRepository(database)

    def _workspace_roots(self) -> list[Path]:
        return [Path(ws.root_path) for ws in self._ws_repo.list_all()]

    def _snapshot_db(self, dest_db_path: Path) -> None:
        dest_db_path.parent.mkdir(parents=True, exist_ok=True)
        src_conn = self._db.connect()
        try:
            dst_conn = sqlite3.connect(dest_db_path)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

    def create_full_backup(self, dest_zip_path: Path | str) -> Path:
        """Create a consistent WAL-safe full backup ZIP outside monitored workspaces."""
        dest = Path(dest_zip_path).expanduser().resolve(strict=False)
        assert_not_inside_monitored_workspace(dest, self._workspace_roots())

        self._paths.drafts_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._paths.drafts_dir) as tmp_dir:
            snap_db = Path(tmp_dir) / "work_memory.db"
            self._snapshot_db(snap_db)

            dest.parent.mkdir(parents=True, exist_ok=True)
            meta = {"schema_version": "1.0", "created_at_utc": utc_now_iso()}
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("backup_meta.json", json.dumps(meta, indent=2))
                zf.write(snap_db, arcname="work_memory.db")
                settings_file = self._paths.base_dir / "settings.json"
                if settings_file.is_file():
                    zf.write(settings_file, arcname="settings.json")
                for folder_name, folder_path in (
                    ("attachments", self._paths.attachments_dir),
                    ("covers", self._paths.covers_dir),
                ):
                    if folder_path.is_dir():
                        for item in folder_path.rglob("*"):
                            if item.is_file():
                                rel = item.relative_to(folder_path).as_posix()
                                zf.write(item, arcname=f"{folder_name}/{rel}")
        return dest

    def restore_full_backup(self, backup_zip_path: Path | str) -> None:
        """Verify and restore a full backup ZIP, removing stale WAL/SHM sidecars safely."""
        src = Path(backup_zip_path).expanduser().resolve(strict=False)
        with zipfile.ZipFile(src, "r") as zf:
            validate_zip_members(zf)
            names = set(zf.namelist())
            if "backup_meta.json" not in names or "work_memory.db" not in names:
                raise ValueError("Invalid backup ZIP: missing backup_meta.json or work_memory.db.")
            meta = json.loads(zf.read("backup_meta.json").decode("utf-8"))
            if not isinstance(meta, dict) or meta.get("schema_version") != "1.0":
                raise ValueError(f"Unsupported backup schema_version: {meta.get('schema_version')!r}")
            db_bytes = zf.read("work_memory.db")
            if not db_bytes.startswith(_SQLITE_HEADER):
                raise ValueError("Invalid backup ZIP: work_memory.db is not a valid SQLite file.")

            with tempfile.TemporaryDirectory(dir=self._paths.drafts_dir) as tmp_dir:
                tmp_root = Path(tmp_dir)
                zf.extractall(tmp_root)
                self._apply_verified_restore(tmp_root)

        if self._bus is not None:
            self._bus.workspaces_changed.emit()
            self._bus.projects_changed.emit()
            self._bus.calendar_updated.emit()
            self._bus.status_message.emit("Backup restored cleanly.")

    def _apply_verified_restore(self, extracted_root: Path) -> None:
        if self._ws_service is not None:
            self._ws_service.pause_monitoring()
            self._ws_service.wait_for_scans(timeout=10.0)
        if self._cal_service is not None:
            self._cal_service.stop_poller()

        self._paths.logs_dir.mkdir(parents=True, exist_ok=True)
        if self._paths.db_path.is_file():
            pre_bak = self._paths.logs_dir / "work_memory.pre_restore.bak"
            shutil.copy2(self._paths.db_path, pre_bak)

        for sidecar in (Path(f"{self._paths.db_path}-wal"), Path(f"{self._paths.db_path}-shm")):
            if sidecar.is_file():
                sidecar.unlink()

        shutil.copy2(extracted_root / "work_memory.db", self._paths.db_path)
        self._db.run_migrations()

        extracted_settings = extracted_root / "settings.json"
        if extracted_settings.is_file():
            shutil.copy2(extracted_settings, self._paths.base_dir / "settings.json")

        for folder_name, dest_dir in (
            ("attachments", self._paths.attachments_dir),
            ("covers", self._paths.covers_dir),
        ):
            extracted_dir = extracted_root / folder_name
            if extracted_dir.is_dir():
                dest_dir.mkdir(parents=True, exist_ok=True)
                for item in extracted_dir.rglob("*"):
                    if item.is_file():
                        rel = safe_archive_member_path(item.relative_to(extracted_dir).as_posix()).as_posix()
                        target = (dest_dir / rel).resolve(strict=False)
                        if not target.is_relative_to(dest_dir):
                            raise PermissionError(f"{folder_name} path escapes storage: {rel!r}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)

    def relocate_data_dir(
        self, new_dir: Path | str, *, bootstrap_file: Path | None = None
    ) -> Path:
        """Safely copy live DB, attachments, settings, and models to ``new_dir`` and update bootstrap."""
        resolved = Path(new_dir).expanduser().resolve(strict=False)
        roots = self._workspace_roots()
        assert_not_inside_monitored_workspace(resolved, roots)

        if self._ws_service is not None:
            self._ws_service.pause_monitoring()
            self._ws_service.wait_for_scans(timeout=10.0)

        resolved.mkdir(parents=True, exist_ok=True)
        self._snapshot_db(resolved / "work_memory.db")

        settings_file = self._paths.base_dir / "settings.json"
        if settings_file.is_file():
            shutil.copy2(settings_file, resolved / "settings.json")

        for folder_name in ("attachments", "covers", "models"):
            src_sub = getattr(self._paths, f"{folder_name}_dir")
            dst_sub = resolved / folder_name
            if src_sub.is_dir() and src_sub.resolve(strict=False) != dst_sub.resolve(strict=False):
                shutil.copytree(src_sub, dst_sub, dirs_exist_ok=True)

        # If the active data dir was already relocated earlier without models,
        # also copy any downloaded models from the default %LOCALAPPDATA%\WorkMemory\models.
        dst_models = resolved / "models"
        default_models = _default_app_root() / "models"
        if (
            default_models.is_dir()
            and default_models.resolve(strict=False) != dst_models.resolve(strict=False)
            and not any(dst_models.rglob("model.bin"))
        ):
            shutil.copytree(default_models, dst_models, dirs_exist_ok=True)

        set_custom_data_dir(resolved, workspace_roots=roots, bootstrap_file=bootstrap_file)
        return resolved
