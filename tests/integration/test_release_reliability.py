"""Phase 9 integration reliability suite: scale, restarts, drafts, backups, and portability."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from work_memory.config.paths import resolve_app_paths
from work_memory.core.event_bus import EventBus
from work_memory.core.models import CalendarEvent, ObservedEvent
from work_memory.services.backup_service import BackupService
from work_memory.services.calendar_service import CalendarService
from work_memory.services.capture_service import CaptureService
from work_memory.services.manifest_service import ManifestService
from work_memory.services.project_service import ProjectService
from work_memory.services.workspace_service import WorkspaceService
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository


def _snapshot_tree(root: Path) -> tuple[set[str], dict[str, tuple[str, int]]]:
    dirs: set[str] = set()
    files: dict[str, tuple[str, int]] = {}
    for entry in root.rglob("*"):
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            dirs.add(rel)
        elif entry.is_file():
            digest = hashlib.sha256(entry.read_bytes()).hexdigest()
            files[rel] = (digest, entry.stat().st_mtime_ns)
    return dirs, files


def test_large_workspace_baseline_restart_recovery_and_readonly(tmp_path: Path) -> None:
    """1,000-file baseline scan + ignored noise + offline restart recovery stays read-only."""
    ws_root = tmp_path / "LargeStudio"
    for folder_idx in range(10):
        sub = ws_root / f"Folder_{folder_idx:02d}" / "assets"
        sub.mkdir(parents=True)
        for file_idx in range(100):
            (sub / f"asset_{file_idx:03d}.txt").write_bytes(b"data")

    # Add ignored noise directories and temp files that must never enter baseline or events.
    (ws_root / "Library").mkdir()
    (ws_root / "Library" / "cache.bin").write_bytes(b"ignored")
    (ws_root / "node_modules" / "pkg").mkdir(parents=True)
    (ws_root / "node_modules" / "pkg" / "index.js").write_text("ignored", encoding="utf-8")
    (ws_root / "Folder_00" / "scratch.tmp").write_text("tmp", encoding="utf-8")

    before_baseline = _snapshot_tree(ws_root)
    paths = resolve_app_paths(tmp_path / "app_data")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()

    t0 = time.monotonic()
    ws_svc = WorkspaceService(db, EventBus(), window_ms=100)
    try:
        ws = ws_svc.add_workspace(ws_root, background_scan=False)
        assert ws_svc.list_events(ws.id) == []
        assert ws_svc.count_baseline(ws.id) == 1000
    finally:
        ws_svc.shutdown()
    assert (time.monotonic() - t0) < 10.0
    assert _snapshot_tree(ws_root) == before_baseline

    # Simulate offline edits/adds/deletes plus ignored noise while Work Memory is closed.
    (ws_root / "Folder_01" / "assets" / "asset_000.txt").write_bytes(b"modified-data-1")
    (ws_root / "Folder_02" / "assets" / "asset_005.txt").write_bytes(b"modified-data-2")
    (ws_root / "Folder_03" / "assets" / "brand_new_1.txt").write_bytes(b"new1")
    (ws_root / "Folder_04" / "assets" / "brand_new_2.txt").write_bytes(b"new2")
    (ws_root / "Folder_05" / "assets" / "asset_009.txt").unlink()
    (ws_root / "Folder_06" / "ignored_backup.bak").write_text("bak", encoding="utf-8")
    after_offline_edits = _snapshot_tree(ws_root)

    restarted = WorkspaceService(db, EventBus(), window_ms=100)
    try:
        restarted.start(background_scans=False)
        restarted.wait_for_scans(timeout=10.0)
        events = restarted.list_events(ws.id, limit=50)
        assert restarted.count_baseline(ws.id) == 1001
    finally:
        restarted.shutdown()

    by_rel = {ev.rel_path: ev.event_type for ev in events}
    assert by_rel == {
        "Folder_01/assets/asset_000.txt": "modified",
        "Folder_02/assets/asset_005.txt": "modified",
        "Folder_03/assets/brand_new_1.txt": "created",
        "Folder_04/assets/brand_new_2.txt": "created",
        "Folder_05/assets/asset_009.txt": "deleted",
    }
    assert _snapshot_tree(ws_root) == after_offline_edits


def test_draft_recovery_backup_restore_and_cross_drive_wmem_portability(tmp_path: Path) -> None:
    """Interrupted draft recovery, full backup restore, and .wmem portability stay read-only."""
    ws_a = tmp_path / "DriveA" / "StudioA"
    proj_a_dir = ws_a / "Alpha"
    (proj_a_dir / "scenes").mkdir(parents=True)
    (proj_a_dir / "scenes" / "rig.blend").write_bytes(b"BLEND-A")

    ws_b = tmp_path / "DriveB" / "StudioB"
    proj_b_dir = ws_b / "Alpha_Relocated"
    (proj_b_dir / "scenes").mkdir(parents=True)
    (proj_b_dir / "scenes" / "rig.blend").write_bytes(b"BLEND-A")

    snap_a = _snapshot_tree(ws_a)
    snap_b = _snapshot_tree(ws_b)

    paths = resolve_app_paths(tmp_path / "app_a")
    paths.ensure_directories()
    db = Database(paths.db_path)
    db.run_migrations()
    bus = EventBus()
    ws_svc = WorkspaceService(db, bus, window_ms=100)
    proj_svc = ProjectService(db, bus, workspace_service=ws_svc)
    ws_svc.set_project_service(proj_svc)
    cap_svc = CaptureService(db, paths, bus, workspace_service=ws_svc)
    cal_svc = CalendarService(db, bus)
    try:
        ws = ws_svc.add_workspace(ws_a, background_scan=False)
        proj = proj_svc.register_existing_project(proj_a_dir, name="Alpha", description="Rigging")
        ObservedEventRepository(db).insert_batch(
            [
                ObservedEvent(
                    workspace_id=ws.id,
                    project_id=proj.id,
                    rel_path="Alpha/scenes/rig.blend",
                    event_type="modified",
                    is_milestone=True,
                    occurred_at_utc="2026-11-25T09:00:00Z",
                ),
                ObservedEvent(
                    workspace_id=ws.id,
                    project_id=proj.id,
                    rel_path="Alpha/renders/missing_shot.exr",
                    event_type="created",
                    occurred_at_utc="2026-11-25T09:05:00Z",
                ),
            ]
        )

        # 1. Interrupted capture draft recovery across service restart.
        draft_wav = cap_svc.allocate_draft_audio_path()
        draft_wav.write_bytes(b"RIFF-MOCK-WAV")
        cap_svc.save_draft(
            project_id=proj.id,
            linked_file="Alpha/scenes/rig.blend",
            note_text="Interrupted capture note",
            is_milestone=True,
            draft_audio_path=draft_wav,
            draft_transcript="Keep warm key light.",
            audio_retention="both",
        )
        restarted_cap = CaptureService(db, paths, bus, workspace_service=ws_svc)
        recovered = restarted_cap.load_draft()
        assert recovered is not None
        assert recovered.project_id == proj.id
        assert recovered.note_text == "Interrupted capture note"
        assert recovered.is_milestone is True
        assert recovered.draft_audio_path == str(draft_wav)
        assert recovered.draft_transcript == "Keep warm key light."

        saved_cap, saved_atts = restarted_cap.save_capture(
            project_id=recovered.project_id,
            note_text=recovered.note_text,
            linked_file=recovered.linked_file,
            original_screenshot_bytes=b"\x89PNG\r\n\x1a\nSHOT",
            is_milestone=recovered.is_milestone,
            audio_wav_path=recovered.draft_audio_path,
            transcription=recovered.draft_transcript,
            audio_retention=recovered.audio_retention,
        )
        assert len(saved_atts) == 2
        assert restarted_cap.has_draft() is False

        cal_ev = CalendarRepo(db).create(
            CalendarEvent(
                project_id=proj.id,
                title="Client rig review",
                event_at_utc="2026-11-28T16:00:00Z",
            )
        )

        # 2. Full backup & restore round-trip into fresh storage directory.
        bak_zip = tmp_path / "backups" / "work_memory_full.zip"
        BackupService(
            db, paths, bus, workspace_service=ws_svc, calendar_service=cal_svc
        ).create_full_backup(bak_zip)

        restored_paths = resolve_app_paths(tmp_path / "app_restored")
        restored_paths.ensure_directories()
        restored_db = Database(restored_paths.db_path)
        restored_db.run_migrations()
        BackupService(restored_db, restored_paths, EventBus()).restore_full_backup(bak_zip)

        assert ProjectRepository(restored_db).get(proj.id) is not None
        assert len(ObservedEventRepository(restored_db).list_by_project(proj.id)) == 2
        restored_caps = CaptureRepository(restored_db).list_recent(project_id=proj.id)
        assert len(restored_caps) == 1 and restored_caps[0].id == saved_cap.id
        restored_atts = CaptureRepository(restored_db).list_attachments(saved_cap.id)
        assert len(restored_atts) == 2
        assert all((restored_paths.attachments_dir / a.stored_rel_path).is_file() for a in restored_atts)
        assert CalendarRepo(restored_db).get_by_id(cal_ev.id) is not None

        # 3. Cross-drive .wmem portability into fresh DB linked to Workspace B.
        bundle = tmp_path / "exports" / "alpha.wmem"
        ManifestService(db, paths, bus).export_project_bundle(proj.id, bundle)

        port_paths = resolve_app_paths(tmp_path / "app_portable")
        port_paths.ensure_directories()
        port_db = Database(port_paths.db_path)
        port_db.run_migrations()
        import_res = ManifestService(port_db, port_paths, EventBus()).import_project_bundle(
            bundle, target_project_folder=proj_b_dir, conflict_mode="merge"
        )
        assert import_res.imported_counts == {
            "observed_events": 2,
            "capture_entries": 1,
            "attachments": 2,
            "calendar_events": 1,
        }
        assert import_res.missing_files == ["renders/missing_shot.exr"]
        port_atts = CaptureRepository(port_db).list_attachments(saved_cap.id)
        assert all((port_paths.attachments_dir / a.stored_rel_path).is_file() for a in port_atts)
    finally:
        ws_svc.shutdown()

    assert _snapshot_tree(ws_a) == snap_a
    assert _snapshot_tree(ws_b) == snap_b
