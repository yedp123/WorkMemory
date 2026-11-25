"""Unit tests for exclusion filtering, atomic-save coalescing, and image sequences."""

from __future__ import annotations

from pathlib import Path

from work_memory.watcher.coalescer import EventCoalescer, RawFsEvent
from work_memory.watcher.filters import ExclusionFilter, to_rel_path


def test_exclusion_filter_defaults_and_posix_rel_path(tmp_path: Path) -> None:
    root = tmp_path / "StudioWork"
    nested = root / "Project_A" / "scenes" / "hero.blend"
    assert to_rel_path(nested, root) == "Project_A/scenes/hero.blend"
    assert to_rel_path(root, root) == ""

    filt = ExclusionFilter(extra_patterns=["*.cache"])
    for ignored in (
        "notes/draft.tmp",
        "scenes/rig.ma.bak",
        "docs/~$brief.docx",
        "scenes/.scene.ma.swp",
        "renders/Thumbs.db",
        "renders/.DS_Store",
        ".git/objects/ab/123456",
        "web/node_modules/pkg/index.js",
        "UnityApp/Library/ShaderCache/a.bin",
        "Temp/scratch.dat",
        "Cache/preview.png",
        "Auto-Save/backup_01.blend",
        "sims/cloth.cache",
    ):
        assert filt.is_ignored(ignored), f"Expected ignored: {ignored}"

    assert filt.is_ignored_directory("node_modules")
    assert filt.is_ignored_directory("Sub/.git/objects")
    assert not filt.is_ignored(".git/HEAD")
    assert not filt.is_ignored("Project_A/scenes/hero.blend")


def test_photoshop_maya_atomic_save_collapses_to_single_modified() -> None:
    coalescer = EventCoalescer(window_ms=1000)
    ws_id = "ws-1"

    # Photoshop-style atomic save: temp create/modify -> original delete -> temp rename to original
    coalescer.push(RawFsEvent(ws_id, "created", "art/hero_painting.psd.tmp", file_size=512, monotonic_ts=1.00))
    coalescer.push(RawFsEvent(ws_id, "modified", "art/hero_painting.psd.tmp", file_size=2048, monotonic_ts=1.05))
    coalescer.push(RawFsEvent(ws_id, "deleted", "art/hero_painting.psd", file_size=1900, monotonic_ts=1.10))
    coalescer.push(
        RawFsEvent(
            ws_id,
            "moved",
            "art/hero_painting.psd.tmp",
            dest_rel_path="art/hero_painting.psd",
            file_size=2048,
            monotonic_ts=1.15,
        )
    )

    # Not flushed yet before 1000ms window
    assert coalescer.flush_expired(now_monotonic=1.80) == []

    events = coalescer.flush_expired(now_monotonic=2.20)
    assert len(events) == 1
    assert events[0].event_type == "modified"
    assert events[0].rel_path == "art/hero_painting.psd"
    assert events[0].old_rel_path is None
    assert events[0].file_size == 2048


def test_backup_rotate_atomic_save_collapses_to_single_modified() -> None:
    coalescer = EventCoalescer(window_ms=1000)
    ws_id = "ws-1"

    # Maya/CAD backup-rotate save: temp create -> original renamed to .bak -> temp renamed to original
    coalescer.push(RawFsEvent(ws_id, "created", "scenes/rig.ma.tmp", file_size=4096))
    coalescer.push(RawFsEvent(ws_id, "moved", "scenes/rig.ma", dest_rel_path="scenes/rig.ma.bak"))
    coalescer.push(
        RawFsEvent(ws_id, "moved", "scenes/rig.ma.tmp", dest_rel_path="scenes/rig.ma", file_size=4096)
    )

    events = coalescer.flush()
    assert len(events) == 1
    assert events[0].event_type == "modified"
    assert events[0].rel_path == "scenes/rig.ma"


def test_rapid_modified_burst_dedup_ephemeral_and_rename_vs_move() -> None:
    coalescer = EventCoalescer(window_ms=1000)
    ws_id = "ws-1"

    for size in (100, 200, 300, 450):
        coalescer.push(RawFsEvent(ws_id, "modified", "docs/notes.md", file_size=size))
    coalescer.push(RawFsEvent(ws_id, "created", "docs/scratch_unsaved.txt", file_size=10))
    coalescer.push(RawFsEvent(ws_id, "deleted", "docs/scratch_unsaved.txt"))
    coalescer.push(RawFsEvent(ws_id, "moved", "scenes/old.blend", dest_rel_path="scenes/new.blend"))
    coalescer.push(RawFsEvent(ws_id, "moved", "drafts/prop.fbx", dest_rel_path="final/prop.fbx"))
    coalescer.push(RawFsEvent(ws_id, "created", "docs/orphan.tmp", file_size=64))

    events = coalescer.flush()
    by_path = {ev.rel_path: ev for ev in events}

    assert set(by_path) == {"docs/notes.md", "scenes/new.blend", "final/prop.fbx"}
    assert by_path["docs/notes.md"].event_type == "modified"
    assert by_path["docs/notes.md"].file_size == 450
    assert by_path["scenes/new.blend"].event_type == "renamed"
    assert by_path["scenes/new.blend"].old_rel_path == "scenes/old.blend"
    assert by_path["final/prop.fbx"].event_type == "moved"
    assert by_path["final/prop.fbx"].old_rel_path == "drafts/prop.fbx"


def test_fifty_exr_frames_collapse_into_one_grouped_sequence_event() -> None:
    coalescer = EventCoalescer(window_ms=1000)
    ws_id = "ws-1"

    for frame in range(1, 51):
        coalescer.push(
            RawFsEvent(
                ws_id,
                "created",
                f"renders/shot04/shot04_{frame:04d}.exr",
                file_size=1024,
            )
        )
    # Non-image numbered files must remain individual events.
    for idx in range(1, 4):
        coalescer.push(RawFsEvent(ws_id, "created", f"scripts/step_{idx:02d}.py", file_size=50))

    events = coalescer.flush()
    seq_events = [ev for ev in events if ev.group_key is not None]
    py_events = [ev for ev in events if ev.rel_path.endswith(".py")]

    assert len(seq_events) == 1
    assert seq_events[0].event_type == "created"
    assert seq_events[0].rel_path == "renders/shot04/shot04_0001.exr .. shot04_0050.exr (50 frames)"
    assert seq_events[0].file_size == 51200
    assert seq_events[0].group_key == "seq:renders/shot04/shot04_####.exr:0001-0050:50"
    assert len(py_events) == 3
