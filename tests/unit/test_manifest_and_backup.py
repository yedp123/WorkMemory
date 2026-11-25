"""Unit tests for Phase 8B: Portable .wmem Export/Import, Zip-Slip, Backup & Relocation."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from work_memory.config.paths import is_likely_cloud_synced_path, resolve_app_paths
from work_memory.config.settings import AppSettings, load_settings, save_settings
from work_memory.core.event_bus import EventBus
from work_memory.core.models import (
    Attachment,
    CalendarEvent,
    CaptureEntry,
    ObservedEvent,
    Project,
    Workspace,
)
from work_memory.services.backup_service import BackupService
from work_memory.services.manifest_service import ManifestService
from work_memory.storage.attachments import AttachmentStorage
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository


def _seed_project(tmp_path: Path) -> tuple[Database, Path, Project, Path]:
    paths = resolve_app_paths(tmp_path / "src_app")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()

    ws_root = tmp_path / "SrcStudio"
    proj_dir = ws_root / "RenderJob"
    proj_dir.mkdir(parents=True)
    (proj_dir / "scene.blend").write_text("scene", encoding="utf-8")

    ws = WorkspaceRepository(db).create(Workspace(name="SrcStudio", root_path=str(ws_root)))
    proj = ProjectRepository(db).create(
        Project(
            workspace_id=ws.id,
            name="RenderJob",
            rel_path="RenderJob",
            abs_path=str(proj_dir),
            summary_custom="Client approved rough lighting.",
            is_pinned=True,
        )
    )
    ObservedEventRepository(db).insert_batch(
        [
            ObservedEvent(
                workspace_id=ws.id,
                project_id=proj.id,
                rel_path="RenderJob/scene.blend",
                event_type="modified",
                is_milestone=True,
                occurred_at_utc="2026-11-24T08:00:00Z",
            ),
            ObservedEvent(
                workspace_id=ws.id,
                project_id=proj.id,
                rel_path="RenderJob/missing_tex.png",
                event_type="created",
                occurred_at_utc="2026-11-24T08:05:00Z",
            ),
        ]
    )
    att_store = AttachmentStorage(paths.attachments_dir)
    orig_file = att_store.save_image_bytes(b"\x89PNG\r\n\x1a\nORIG", "png")
    ann_file = att_store.save_image_bytes(b"\x89PNG\r\n\x1a\nANN", "png")
    cap = CaptureEntry(
        project_id=proj.id,
        rel_path="RenderJob/scene.blend",
        note_text="Check specular highlights.",
        transcription="Voice memo about specular.",
        is_milestone=True,
        captured_at_utc="2026-11-24T08:10:00Z",
    )
    a1 = Attachment(
        capture_entry_id=cap.id,
        kind="screenshot",
        stored_rel_path=orig_file.stored_rel_path,
        mime_type="image/png",
        byte_size=orig_file.byte_size,
        sha256=orig_file.sha256,
    )
    a2 = Attachment(
        capture_entry_id=cap.id,
        kind="annotated_screenshot",
        original_attachment_id=a1.id,
        stored_rel_path=ann_file.stored_rel_path,
        mime_type="image/png",
        byte_size=ann_file.byte_size,
        sha256=ann_file.sha256,
    )
    CaptureRepository(db).create(cap, [a1, a2])
    CalendarRepo(db).create(
        CalendarEvent(
            project_id=proj.id,
            title="Final render delivery",
            event_at_utc="2026-11-28T15:00:00Z",
        )
    )
    return db, paths.base_dir, proj, ws_root


def test_wmem_roundtrip_import_merge_copy_and_skip(tmp_path: Path) -> None:
    src_db, src_base, proj, ws_root = _seed_project(tmp_path)
    src_paths = resolve_app_paths(src_base)
    src_manifest = ManifestService(src_db, src_paths)

    # Exporting inside a monitored workspace must be blocked.
    with pytest.raises(PermissionError):
        src_manifest.export_project_bundle(proj.id, ws_root / "leak.wmem")

    bundle = tmp_path / "exports" / "render_job.wmem"
    src_manifest.export_project_bundle(proj.id, bundle)

    # Import into a brand-new empty SQLite database on a different folder path.
    dst_paths = resolve_app_paths(tmp_path / "dst_app")
    dst_paths.ensure_directories()
    dst_db = Database(dst_paths.db_path)
    dst_db.run_migrations()
    dst_manifest = ManifestService(dst_db, dst_paths, EventBus())

    dst_proj_dir = tmp_path / "NewPC" / "RenderJob_Copy"
    dst_proj_dir.mkdir(parents=True)
    (dst_proj_dir / "scene.blend").write_text("scene", encoding="utf-8")

    preview = dst_manifest.inspect_bundle(bundle)
    assert preview.project_name == "RenderJob"
    assert preview.counts["capture_entries"] == 1
    assert preview.counts["attachments"] == 2

    res = dst_manifest.import_project_bundle(bundle, target_project_folder=dst_proj_dir, conflict_mode="merge")
    assert res.skipped is False
    assert res.imported_counts == {
        "observed_events": 2,
        "capture_entries": 1,
        "attachments": 2,
        "calendar_events": 1,
    }
    assert res.missing_files == ["missing_tex.png"]

    imported_proj = ProjectRepository(dst_db).get(proj.id)
    assert imported_proj is not None
    assert imported_proj.summary_custom == "Client approved rough lighting."
    assert imported_proj.is_pinned is True
    caps = CaptureRepository(dst_db).list_recent(project_id=proj.id)
    assert len(caps) == 1 and caps[0].transcription == "Voice memo about specular."
    atts = CaptureRepository(dst_db).list_attachments(caps[0].id)
    assert len(atts) == 2 and all((dst_paths.attachments_dir / a.stored_rel_path).is_file() for a in atts)

    # Conflict mode "skip" does nothing; "merge" only inserts missing records; "copy" mints new IDs.
    assert dst_manifest.import_project_bundle(bundle, dst_proj_dir, conflict_mode="skip").skipped is True
    merge_again = dst_manifest.import_project_bundle(bundle, dst_proj_dir, conflict_mode="merge")
    assert merge_again.imported_counts["capture_entries"] == 0

    copy_res = dst_manifest.import_project_bundle(bundle, dst_proj_dir, conflict_mode="copy")
    assert copy_res.project_id != proj.id
    copy_caps = CaptureRepository(dst_db).list_recent(project_id=copy_res.project_id)
    assert len(copy_caps) == 1
    copy_atts = CaptureRepository(dst_db).list_attachments(copy_caps[0].id)
    by_kind = {a.kind: a for a in copy_atts}
    assert by_kind["annotated_screenshot"].original_attachment_id == by_kind["screenshot"].id


def test_zip_slip_rejected_on_wmem_and_backup(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()

    evil_zip = tmp_path / "evil.wmem"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
        zf.writestr("manifest.json", '{"schema_version":"1.0","project":{"id":"1","name":"X"}}')

    with pytest.raises(ValueError, match="Unsafe archive"):
        ManifestService(db, paths).inspect_bundle(evil_zip)

    with pytest.raises(ValueError, match="Unsafe archive"):
        BackupService(db, paths).restore_full_backup(evil_zip)


def test_full_backup_restore_and_data_dir_relocation(tmp_path: Path) -> None:
    src_db, src_base, proj, _ws_root = _seed_project(tmp_path)
    src_paths = resolve_app_paths(src_base)
    save_settings(src_paths, AppSettings(repeated_save_interval=12, minimize_to_tray_on_close=False))

    bak_svc = BackupService(src_db, src_paths, EventBus())
    bak_zip = tmp_path / "backups" / "full_backup.zip"
    bak_svc.create_full_backup(bak_zip)

    # Restore into a fresh app data dir that has stale WAL/SHM sidecars.
    dst_paths = resolve_app_paths(tmp_path / "restored_app")
    dst_paths.ensure_directories()
    dst_db = Database(dst_paths.db_path)
    dst_db.run_migrations()
    Path(f"{dst_paths.db_path}-wal").write_bytes(b"stale-wal")
    Path(f"{dst_paths.db_path}-shm").write_bytes(b"stale-shm")

    BackupService(dst_db, dst_paths, EventBus()).restore_full_backup(bak_zip)
    assert not Path(f"{dst_paths.db_path}-wal").exists()
    assert not Path(f"{dst_paths.db_path}-shm").exists()
    assert ProjectRepository(dst_db).get(proj.id) is not None
    assert load_settings(dst_paths).repeated_save_interval == 12

    # Relocate data dir writes bootstrap.json; resolve_app_paths honors it only when base_dir is None.
    bootstrap_file = tmp_path / "bootstrap.json"
    new_data_dir = tmp_path / "D_Drive" / "WorkMemoryData"
    bak_svc.relocate_data_dir(new_data_dir, bootstrap_file=bootstrap_file)

    resolved_from_bootstrap = resolve_app_paths(base_dir=None, bootstrap_file=bootstrap_file)
    assert resolved_from_bootstrap.base_dir == new_data_dir.resolve()
    isolated_test_paths = resolve_app_paths(tmp_path / "isolated", bootstrap_file=bootstrap_file)
    assert isolated_test_paths.base_dir == (tmp_path / "isolated").resolve()

    # Cloud-sync detection
    assert is_likely_cloud_synced_path(Path("C:/Users/Alice/OneDrive/WorkMemory")) is True
    assert is_likely_cloud_synced_path(Path("D:/Dropbox/WorkMemory")) is True
    assert is_likely_cloud_synced_path(Path("D:/WorkMemoryData")) is False


def test_relocate_data_dir_copies_models_and_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()

    # Case 1: Active data dir has models -> copied to new location
    model_snap = paths.models_dir / "models--Systran--faster-whisper-base" / "snapshots" / "rev1"
    model_snap.mkdir(parents=True)
    (model_snap / "model.bin").write_bytes(b"weights")

    bak_svc = BackupService(db, paths, EventBus())
    dest1 = tmp_path / "relocated_1"
    bak_svc.relocate_data_dir(dest1, bootstrap_file=tmp_path / "bootstrap1.json")
    assert (dest1 / "models" / "models--Systran--faster-whisper-base" / "snapshots" / "rev1" / "model.bin").is_file()

    # Case 2: Active data dir has empty models/, but default %LOCALAPPDATA%\WorkMemory\models has it
    paths2 = resolve_app_paths(tmp_path / "app_data_no_models")
    paths2.ensure_directories()
    db2 = Database(paths2.db_path)
    db2.run_migrations()
    fake_default_root = tmp_path / "default_localappdata" / "WorkMemory"
    default_snap = fake_default_root / "models" / "base"
    default_snap.mkdir(parents=True)
    (default_snap / "model.bin").write_bytes(b"default-weights")
    monkeypatch.setattr("work_memory.services.backup_service._default_app_root", lambda: fake_default_root)

    dest2 = tmp_path / "relocated_2"
    BackupService(db2, paths2, EventBus()).relocate_data_dir(dest2, bootstrap_file=tmp_path / "bootstrap2.json")
    assert (dest2 / "models" / "base" / "model.bin").is_file()
