"""Portable .wmem project memory export and import with Zip-Slip & SHA-256 checks."""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from work_memory.config.paths import AppPaths, assert_not_inside_monitored_workspace
from work_memory.core.event_bus import EventBus
from work_memory.core.ids import new_id, utc_now_iso
from work_memory.core.models import (
    Attachment,
    CalendarEvent,
    CaptureEntry,
    ImportResult,
    ManifestPreview,
    ObservedEvent,
    Project,
    Workspace,
)
from work_memory.media.cover_storage import export_cover_entry, import_cover_from_zip
from work_memory.services.archive_safety import (
    safe_archive_member_path,
    sha256_bytes,
    sha256_file,
    validate_zip_members,
)
from work_memory.services.relink_service import to_project_relative_path
from work_memory.storage.attachments import AttachmentStorage
from work_memory.storage.database import Database
from work_memory.storage.repositories.calendar_repo import CalendarRepo
from work_memory.storage.repositories.capture_repo import CaptureRepository
from work_memory.storage.repositories.observed_event_repo import ObservedEventRepository
from work_memory.storage.repositories.project_repo import ProjectRepository
from work_memory.storage.repositories.workspace_repo import WorkspaceRepository

SCHEMA_VERSION = "1.0"


def _read_manifest_from_zip(zf: zipfile.ZipFile) -> dict[str, Any]:
    validate_zip_members(zf)
    if "manifest.json" not in zf.namelist():
        raise ValueError("Invalid .wmem archive: missing manifest.json.")
    data = json.loads(zf.read("manifest.json").decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("project"), dict):
        raise TypeError("Invalid .wmem manifest: missing project object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported .wmem schema_version: {data.get('schema_version')!r}")
    return data


def _serialize_project(p: Project) -> dict[str, Any]:
    return {
        "id": p.id, "name": p.name, "description": p.description, "status": p.status,
        "is_pinned": p.is_pinned, "cover_style": p.cover_style, "cover_image_path": p.cover_image_path,
        "relative_root": p.root_rel_path or p.rel_path, "last_known_state": p.last_known_state,
        "summary_custom": p.summary_custom, "summary_generated": p.summary_generated,
        "summary_updated_utc": p.summary_updated_utc, "last_activity_utc": p.last_activity_utc,
        "created_at_utc": p.created_at_utc, "updated_at_utc": p.updated_at_utc,
    }


class ManifestService:
    """Exports and imports portable ``.wmem`` ZIP bundles strictly outside user workspaces."""

    def __init__(self, database: Database, app_paths: AppPaths, event_bus: EventBus | None = None) -> None:
        self._db, self._paths, self._bus = database, app_paths, event_bus
        self._ws_repo = WorkspaceRepository(database)
        self._proj_repo = ProjectRepository(database)
        self._ev_repo = ObservedEventRepository(database)
        self._cap_repo = CaptureRepository(database)
        self._cal_repo = CalendarRepo(database)
        self._att_store = AttachmentStorage(app_paths.attachments_dir, self._workspace_roots)

    def _workspace_roots(self) -> list[Path]:
        return [Path(ws.root_path) for ws in self._ws_repo.list_all()]

    def export_project_bundle(self, project_id: str, dest_wmem_path: Path | str) -> Path:
        """Export one project's full history and attachments to an external ``.wmem`` ZIP."""
        project = self._proj_repo.get(project_id)
        if project is None:
            raise ValueError(f"Unknown project_id: {project_id!r}")
        dest = Path(dest_wmem_path).expanduser().resolve(strict=False)
        assert_not_inside_monitored_workspace(dest, self._workspace_roots())

        rel_root = project.root_rel_path or project.rel_path
        events = [e for e in self._ev_repo.list_by_project(project_id, limit=50000) if not e.is_baseline]
        captures = self._cap_repo.list_recent(project_id=project_id, limit=50000)
        cal_events = self._cal_repo.list_recent(project_id=project_id, limit=50000)
        att_map = self._cap_repo.list_attachments_for_entries([c.id for c in captures]) if captures else {}

        obs_dicts = []
        for ev in events:
            d = asdict(ev)
            d["rel_path"] = to_project_relative_path(ev.rel_path, rel_root) or ev.rel_path
            if ev.old_rel_path:
                d["old_rel_path"] = to_project_relative_path(ev.old_rel_path, rel_root) or ev.old_rel_path
            obs_dicts.append(d)

        cap_dicts = []
        for cap in captures:
            d = asdict(cap)
            if cap.rel_path:
                d["rel_path"] = to_project_relative_path(cap.rel_path, rel_root) or cap.rel_path
            cap_dicts.append(d)

        att_dicts: list[dict[str, Any]] = []
        files_to_pack: list[tuple[Path, str]] = []
        if (cover_pack := export_cover_entry(self._paths.covers_dir, project.cover_image_path)) is not None:
            files_to_pack.append((cover_pack[1], cover_pack[0]))
        for atts in att_map.values():
            for att in atts:
                src = self._att_store.resolve_path(att.stored_rel_path)
                archive_path = f"attachments/{att.stored_rel_path.lstrip('/')}"
                digest = sha256_file(src) if src.is_file() else att.sha256
                d = asdict(att)
                d["archive_path"] = archive_path
                d["sha256"] = digest
                att_dicts.append(d)
                if src.is_file():
                    files_to_pack.append((src, archive_path))

        manifest = {
            "schema_version": SCHEMA_VERSION, "exported_at_utc": utc_now_iso(),
            "project": _serialize_project(project),
            "observed_events": obs_dicts, "capture_entries": cap_dicts,
            "attachments": att_dicts, "calendar_events": [asdict(c) for c in cal_events],
        }
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            for src_file, arcname in files_to_pack:
                zf.write(src_file, arcname=arcname)
        return dest

    def inspect_bundle(self, wmem_path: Path | str) -> ManifestPreview:
        """Read and validate ``manifest.json`` from a ``.wmem`` bundle without importing."""
        src = Path(wmem_path).expanduser().resolve(strict=False)
        with zipfile.ZipFile(src, "r") as zf:
            data = _read_manifest_from_zip(zf)
        proj = data["project"]
        counts = {k: len(data.get(k, [])) for k in ("observed_events", "capture_entries", "attachments", "calendar_events")}
        return ManifestPreview(
            schema_version=str(data["schema_version"]), exported_at_utc=str(data.get("exported_at_utc", "")),
            project_id=str(proj["id"]), project_name=str(proj["name"]), counts=counts,
        )

    def import_project_bundle(
        self,
        wmem_path: Path | str,
        target_project_folder: Path | str | None = None,
        conflict_mode: Literal["skip", "merge", "copy"] = "merge",
    ) -> ImportResult:
        """Import a ``.wmem`` bundle with Zip-Slip, SHA-256, and conflict-mode protection."""
        src = Path(wmem_path).expanduser().resolve(strict=False)
        with zipfile.ZipFile(src, "r") as zf:
            data = _read_manifest_from_zip(zf)
            proj_data = data["project"]
            orig_pid = str(proj_data["id"])
            existing = self._proj_repo.get(orig_pid)

            if existing is not None and conflict_mode == "skip":
                return ImportResult(project_id=orig_pid, skipped=True)

            is_copy = existing is not None and conflict_mode == "copy"
            target_pid = new_id() if is_copy else orig_pid
            ws, rel_root, abs_path = self._resolve_import_location(
                proj_data, target_project_folder, make_unique_rel=is_copy
            )

            if existing is None or is_copy:
                cover_name = import_cover_from_zip(
                    zf, proj_data.get("cover_image_path"), self._paths.covers_dir,
                    self._workspace_roots(), rename_copy=is_copy,
                )
                self._proj_repo.create(
                    Project(
                        id=target_pid, workspace_id=ws.id, name=str(proj_data["name"]), rel_path=rel_root,
                        description=str(proj_data.get("description", "")), status=proj_data.get("status", "ongoing"),
                        cover_style=proj_data.get("cover_style", "c1"), cover_image_path=cover_name,
                        root_rel_path=rel_root, abs_path=abs_path,
                        last_known_state=str(proj_data.get("last_known_state", "")),
                        summary_custom=proj_data.get("summary_custom"), summary_generated=proj_data.get("summary_generated"),
                        summary_updated_utc=proj_data.get("summary_updated_utc"), last_activity_utc=proj_data.get("last_activity_utc"),
                        is_pinned=bool(proj_data.get("is_pinned", False)),
                        created_at_utc=str(proj_data.get("created_at_utc") or utc_now_iso()),
                        updated_at_utc=str(proj_data.get("updated_at_utc") or utc_now_iso()),
                    )
                )

            counts = self._import_records(zf, data, ws.id, target_pid, rel_root, is_copy)

        missing = self._compute_missing_files(data, target_project_folder)
        if self._bus is not None:
            self._bus.projects_changed.emit()
            if counts["calendar_events"]:
                self._bus.calendar_updated.emit()
        return ImportResult(project_id=target_pid, imported_counts=counts, missing_files=missing)

    def _resolve_import_location(
        self, proj_data: dict[str, Any], target_folder: Path | str | None, *, make_unique_rel: bool
    ) -> tuple[Workspace, str, str]:
        fallback_rel = str(proj_data.get("relative_root") or proj_data["name"]).strip("/") or str(proj_data["name"])
        if target_folder is not None:
            resolved = Path(target_folder).expanduser().resolve(strict=False)
            for ws in self._ws_repo.list_all():
                ws_root = Path(ws.root_path).expanduser().resolve(strict=False)
                if resolved.is_relative_to(ws_root):
                    rel = resolved.relative_to(ws_root).as_posix()
                    rel_val = fallback_rel if rel == "." else rel
                    if make_unique_rel and self._proj_repo.get_by_workspace_rel_path(ws.id, rel_val) is not None:
                        rel_val = f"{rel_val}_{new_id()[:8]}"
                    return ws, rel_val, str(resolved)
            parent_str = str(resolved.parent)
            ws = self._ws_repo.get_by_root_path(parent_str) or self._ws_repo.create(
                Workspace(name=resolved.parent.name or "Imported", root_path=parent_str, is_active=False)
            )
            rel_val = resolved.name or fallback_rel
            if make_unique_rel and self._proj_repo.get_by_workspace_rel_path(ws.id, rel_val) is not None:
                rel_val = f"{rel_val}_{new_id()[:8]}"
            return ws, rel_val, str(resolved)

        imported_root = str(self._paths.base_dir / "imported_projects")
        ws = self._ws_repo.get_by_root_path(imported_root) or self._ws_repo.create(
            Workspace(name="Imported Projects", root_path=imported_root, is_active=False)
        )
        rel_val = fallback_rel
        if make_unique_rel and self._proj_repo.get_by_workspace_rel_path(ws.id, rel_val) is not None:
            rel_val = f"{rel_val}_{new_id()[:8]}"
        return ws, rel_val, ""

    def _import_records(
        self, zf: zipfile.ZipFile, data: dict[str, Any], ws_id: str, pid: str, rel_root: str, is_copy: bool
    ) -> dict[str, int]:
        obs_to_insert: list[ObservedEvent] = []
        for raw in data.get("observed_events", []):
            ev_id = new_id() if is_copy else str(raw["id"])
            if not is_copy and self._ev_repo.get(ev_id) is not None:
                continue
            rel = str(raw["rel_path"]).lstrip("/")
            full_rel = f"{rel_root}/{rel}" if rel_root else rel
            old_rel = raw.get("old_rel_path")
            full_old = (f"{rel_root}/{str(old_rel).lstrip('/')}" if rel_root else str(old_rel)) if old_rel else None
            obs_to_insert.append(
                ObservedEvent(
                    id=ev_id, workspace_id=ws_id, project_id=pid, rel_path=full_rel, old_rel_path=full_old,
                    event_type=raw["event_type"], file_size=raw.get("file_size"),
                    is_baseline=bool(raw.get("is_baseline", False)), is_milestone=bool(raw.get("is_milestone", False)),
                    group_key=raw.get("group_key"), occurred_at_utc=str(raw["occurred_at_utc"]),
                    created_at_utc=str(raw.get("created_at_utc") or raw["occurred_at_utc"]),
                )
            )
        if obs_to_insert:
            self._ev_repo.insert_batch(obs_to_insert)

        atts_by_cap: dict[str, list[dict[str, Any]]] = {}
        for raw_att in data.get("attachments", []):
            atts_by_cap.setdefault(str(raw_att["capture_entry_id"]), []).append(raw_att)

        cap_count, att_count = 0, 0
        for raw_cap in data.get("capture_entries", []):
            orig_cid = str(raw_cap["id"])
            new_cid = new_id() if is_copy else orig_cid
            if not is_copy and self._cap_repo.get(new_cid) is not None:
                continue
            att_id_map = {str(a["id"]): (new_id() if is_copy else str(a["id"])) for a in atts_by_cap.get(orig_cid, [])}
            built_atts: list[Attachment] = []
            for raw_att in atts_by_cap.get(orig_cid, []):
                arc_member = safe_archive_member_path(str(raw_att["archive_path"])).as_posix()
                stored_rel = safe_archive_member_path(str(raw_att["stored_rel_path"])).as_posix()
                payload = zf.read(arc_member)
                expected_sha = str(raw_att.get("sha256", ""))
                if expected_sha and sha256_bytes(payload) != expected_sha:
                    raise ValueError(f"Checksum mismatch for attachment {arc_member!r}.")
                target_file = self._att_store.resolve_path(stored_rel)
                assert_not_inside_monitored_workspace(target_file, self._workspace_roots())
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_bytes(payload)
                orig_link = raw_att.get("original_attachment_id")
                mapped_orig = att_id_map.get(str(orig_link), str(orig_link)) if orig_link else None
                built_atts.append(
                    Attachment(
                        id=att_id_map[str(raw_att["id"])], capture_entry_id=new_cid, kind=raw_att["kind"],
                        stored_rel_path=stored_rel, original_attachment_id=mapped_orig,
                        mime_type=str(raw_att.get("mime_type", "")), byte_size=len(payload),
                        sha256=expected_sha or sha256_bytes(payload),
                        created_at_utc=str(raw_att.get("created_at_utc") or utc_now_iso()),
                    )
                )
            cap_rel = raw_cap.get("rel_path")
            mapped_cap_rel = (f"{rel_root}/{str(cap_rel).lstrip('/')}" if rel_root else str(cap_rel)) if cap_rel else None
            self._cap_repo.create(
                CaptureEntry(
                    id=new_cid, project_id=pid, rel_path=mapped_cap_rel,
                    note_text=str(raw_cap.get("note_text", "")), transcript_text=str(raw_cap.get("transcript_text", "")),
                    transcription=raw_cap.get("transcription"), audio_retention=raw_cap.get("audio_retention", "both"),
                    is_milestone=bool(raw_cap.get("is_milestone", False)), captured_at_utc=str(raw_cap["captured_at_utc"]),
                    created_at_utc=str(raw_cap.get("created_at_utc") or raw_cap["captured_at_utc"]),
                    updated_at_utc=str(raw_cap.get("updated_at_utc") or raw_cap["captured_at_utc"]),
                ),
                built_atts,
            )
            cap_count += 1
            att_count += len(built_atts)

        cal_count = 0
        for raw_cal in data.get("calendar_events", []):
            cal_id = new_id() if is_copy else str(raw_cal["id"])
            if not is_copy and self._cal_repo.get_by_id(cal_id) is not None:
                continue
            ev_at = str(raw_cal.get("event_at_utc") or raw_cal["starts_at_utc"])
            self._cal_repo.create(
                CalendarEvent(
                    id=cal_id, project_id=pid, title=str(raw_cal["title"]),
                    description=str(raw_cal.get("description", "")),
                    starts_at_utc=str(raw_cal.get("starts_at_utc") or ev_at), event_at_utc=ev_at,
                    reminder_minutes=raw_cal.get("reminder_minutes"), status=raw_cal.get("status", "scheduled"),
                    remind_at_utc=raw_cal.get("remind_at_utc"), notified_at_utc=raw_cal.get("notified_at_utc"),
                    created_at_utc=str(raw_cal.get("created_at_utc") or utc_now_iso()),
                    updated_at_utc=str(raw_cal.get("updated_at_utc") or utc_now_iso()),
                )
            )
            cal_count += 1

        return {"observed_events": len(obs_to_insert), "capture_entries": cap_count, "attachments": att_count, "calendar_events": cal_count}

    @staticmethod
    def _compute_missing_files(data: dict[str, Any], target_folder: Path | str | None) -> list[str]:
        refs, deleted = set(), set()
        for ev in data.get("observed_events", []):
            if rel := str(ev.get("rel_path", "")).strip("/"):
                (deleted.add(rel) if ev.get("event_type") == "deleted" else (deleted.discard(rel), refs.add(rel)))
        for cap in data.get("capture_entries", []):
            if cap.get("rel_path"):
                refs.add(str(cap["rel_path"]).strip("/"))
        active = sorted(refs - deleted)
        if target_folder is None:
            return active
        root = Path(target_folder).expanduser().resolve(strict=False)
        return [rel for rel in active if not (root / rel).is_dir() and not (root / rel).exists()]
