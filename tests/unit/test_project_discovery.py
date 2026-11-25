"""Unit tests for read-only ProjectDiscoveryScanner and persistent dismissals."""

from __future__ import annotations

from pathlib import Path

from work_memory.core.models import Workspace
from work_memory.services.project_service import ProjectService
from work_memory.storage.database import Database
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository


def test_discovery_detects_clue_folders_ignores_caches_and_never_auto_registers(
    tmp_path: Path,
) -> None:
    ws_root = tmp_path / "Workspace"
    (ws_root / "Sculpt_Hero").mkdir(parents=True)
    (ws_root / "Sculpt_Hero" / "hero.blend").write_bytes(b"BLEND")

    (ws_root / "KeyArt_Paint").mkdir(parents=True)
    (ws_root / "KeyArt_Paint" / "poster.psd").write_bytes(b"8BPS")

    (ws_root / "Guide_Docs").mkdir(parents=True)
    (ws_root / "Guide_Docs" / "README.md").write_text("# Docs\n", encoding="utf-8")

    (ws_root / "Repo_Tool" / ".git" / "objects" / "ab").mkdir(parents=True)
    (ws_root / "Repo_Tool" / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    (ws_root / "Structured_Shot" / "scenes").mkdir(parents=True)
    (ws_root / "Structured_Shot" / "renders").mkdir(parents=True)
    (ws_root / "Structured_Shot" / "scenes" / "shot_01.ma").write_text("// maya\n", encoding="utf-8")

    # Ignored noise/cache directories must never be walked or suggested.
    (ws_root / "node_modules" / "pkg").mkdir(parents=True)
    (ws_root / "node_modules" / "pkg" / "package.json").write_text("{}", encoding="utf-8")
    (ws_root / "Temp" / "Scratch").mkdir(parents=True)
    (ws_root / "Temp" / "Scratch" / "temp.blend").write_bytes(b"tmp")
    (ws_root / "Library" / "ShaderCache").mkdir(parents=True)
    (ws_root / "Library" / "ShaderCache" / "README.md").write_text("cache", encoding="utf-8")

    # Plain folders without project clues should not be treated as projects.
    (ws_root / "Empty_Dir").mkdir()
    (ws_root / "Loose_Notes").mkdir()
    (ws_root / "Loose_Notes" / "todo.txt").write_text("buy milk", encoding="utf-8")

    # Depth 4 is beyond max depth 3.
    (ws_root / "A" / "B" / "C" / "TooDeep").mkdir(parents=True)
    (ws_root / "A" / "B" / "C" / "TooDeep" / "deep.blend").write_bytes(b"BLEND")

    db = Database(tmp_path / "app" / "work_memory.db")
    db.run_migrations()
    ws = WorkspaceRepository(db).create(Workspace(name="Workspace", root_path=str(ws_root.resolve())))
    service = ProjectService(db)

    suggestions = service.discover_suggestions(ws.id)
    rel_paths = {s.rel_path for s in suggestions}

    assert rel_paths == {
        "Sculpt_Hero",
        "KeyArt_Paint",
        "Guide_Docs",
        "Repo_Tool",
        "Structured_Shot",
    }
    assert "Structured_Shot/scenes" not in rel_paths
    assert "node_modules/pkg" not in rel_paths
    assert "Temp/Scratch" not in rel_paths
    assert "Library/ShaderCache" not in rel_paths
    assert "Empty_Dir" not in rel_paths
    assert "Loose_Notes" not in rel_paths
    assert "A/B/C/TooDeep" not in rel_paths

    # Suggestions MUST NEVER auto-register anything.
    assert service.list_projects() == []


def test_discovery_supports_nested_projects_and_persistent_dismissal(tmp_path: Path) -> None:
    ws_root = tmp_path / "Work"
    (ws_root / "Client" / "README.md").parent.mkdir(parents=True)
    (ws_root / "Client" / "README.md").write_text("# Client\n", encoding="utf-8")
    (ws_root / "Client" / "SubProject").mkdir(parents=True)
    (ws_root / "Client" / "SubProject" / "model.blend").write_bytes(b"BLEND")
    (ws_root / "OtherProj").mkdir(parents=True)
    (ws_root / "OtherProj" / "art.psd").write_bytes(b"8BPS")

    db_path = tmp_path / "app" / "work_memory.db"
    db1 = Database(db_path)
    db1.run_migrations()
    ws = WorkspaceRepository(db1).create(Workspace(name="Work", root_path=str(ws_root.resolve())))
    s1 = ProjectService(db1)

    # Registering parent Client must still leave nested Client/SubProject discoverable.
    s1.register_existing_project(ws_root / "Client", name="Client")
    suggestions = s1.discover_suggestions(ws.id)
    assert {s.rel_path for s in suggestions} == {"Client/SubProject", "OtherProj"}

    # Dismiss OtherProj and confirm persistence across a fresh ProjectService + Database restart.
    s1.dismiss_suggestion(ws.id, "OtherProj")
    assert {s.rel_path for s in s1.discover_suggestions(ws.id)} == {"Client/SubProject"}

    db2 = Database(db_path)
    s2 = ProjectService(db2)
    assert {s.rel_path for s in s2.discover_suggestions(ws.id)} == {"Client/SubProject"}

    # Confirming Client/SubProject registers it and removes it from suggestions.
    sub_suggestion = s2.discover_suggestions(ws.id)[0]
    registered = s2.confirm_suggestion(sub_suggestion)
    assert registered.rel_path == "Client/SubProject"
    assert s2.discover_suggestions(ws.id) == []
