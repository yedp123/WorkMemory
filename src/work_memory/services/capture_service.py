"""Application service for Quick Capture entries, attachments, and draft recovery."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from work_memory.config.paths import AppPaths, assert_not_inside_monitored_workspace
from work_memory.core.event_bus import EventBus
from work_memory.core.ids import new_id, utc_now_iso
from work_memory.core.models import Attachment, CaptureEntry
from work_memory.storage.attachments import AttachmentStorage
from work_memory.storage.database import Database
from work_memory.storage.repositories.capture_repo import CaptureRepository

if TYPE_CHECKING:
    from work_memory.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScreenshotData:
    """Pair of original screenshot PNG bytes and optional annotated PNG bytes."""

    original_bytes: bytes
    annotated_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class CaptureDraft:
    """Recovered unfinished Quick Capture state stored in app-owned ``drafts/``."""

    project_id: str | None = None
    linked_file: str = ""
    note_text: str = ""
    temp_image_path: str | None = None
    is_milestone: bool = False
    draft_audio_path: str | None = None
    draft_transcript: str = ""
    audio_retention: str = "both"
    updated_at_utc: str = ""


class CaptureService:
    """Coordinates combined capture persistence, app-owned attachments, and draft recovery."""

    def __init__(
        self,
        database: Database,
        app_paths: AppPaths,
        event_bus: EventBus | None = None,
        *,
        workspace_service: WorkspaceService | None = None,
    ) -> None:
        self._bus = event_bus
        self._app_paths = app_paths
        self._ws_service = workspace_service
        self._repo = CaptureRepository(database)
        self._storage = AttachmentStorage(
            app_paths.attachments_dir,
            workspace_roots_provider=self._workspace_roots,
        )

    @property
    def attachments_dir(self) -> Path:
        """Return the app-owned attachments directory."""
        return self._storage.attachments_dir

    @property
    def models_dir(self) -> Path:
        """Return the app-owned offline Whisper models directory."""
        return self._app_paths.models_dir

    def allocate_draft_audio_path(self) -> Path:
        """Return a safe temporary WAV path inside app-owned ``drafts/``."""
        drafts_dir = self._app_paths.drafts_dir.expanduser().resolve(strict=False)
        target = drafts_dir / f"draft_audio_{new_id()}.wav"
        assert_not_inside_monitored_workspace(target, self._workspace_roots())
        drafts_dir.mkdir(parents=True, exist_ok=True)
        return target

    def save_capture(
        self,
        *,
        project_id: str | None,
        note_text: str = "",
        linked_file: str | None = None,
        original_screenshot_bytes: bytes | None = None,
        annotated_screenshot_bytes: bytes | None = None,
        screenshots: Sequence[ScreenshotData | tuple[bytes, bytes | None]] = (),
        external_image_paths: Sequence[Path | str] = (),
        is_milestone: bool = False,
        audio_wav_path: Path | str | None = None,
        transcription: str | None = None,
        audio_retention: str = "both",
    ) -> tuple[CaptureEntry, list[Attachment]]:
        """Persist a combined capture entry and any attached screenshots, images, or audio."""
        if audio_retention not in ("both", "text", "audio"):
            raise ValueError(f"Invalid audio retention mode: {audio_retention!r}")
        clean_note = note_text.strip()
        clean_file = (linked_file or "").strip().replace("\\", "/") or None
        clean_transcript = (transcription or "").strip() or None
        audio_src = Path(audio_wav_path).expanduser().resolve(strict=False) if audio_wav_path else None
        keep_audio = audio_src is not None and audio_retention in ("both", "audio")
        stored_transcription = clean_transcript if audio_retention in ("both", "text") else None

        shot_pairs: list[tuple[bytes | None, bytes | None]] = []
        for item in screenshots:
            orig, ann = (
                (item.original_bytes, item.annotated_bytes)
                if isinstance(item, ScreenshotData)
                else (item[0], item[1])
            )
            if orig or ann:
                shot_pairs.append((orig, ann))
        if original_screenshot_bytes or annotated_screenshot_bytes:
            shot_pairs.append((original_screenshot_bytes, annotated_screenshot_bytes))

        if (
            not clean_note
            and not shot_pairs
            and not external_image_paths
            and not stored_transcription
            and not keep_audio
        ):
            raise ValueError("Cannot save an empty capture without a note or attachment.")

        entry = CaptureEntry(
            project_id=project_id or None,
            rel_path=clean_file,
            note_text=clean_note,
            transcript_text=stored_transcription or "",
            transcription=stored_transcription,
            audio_retention=audio_retention,
            is_milestone=is_milestone,
        )
        attachments: list[Attachment] = []

        for orig_bytes, ann_bytes in shot_pairs:
            orig_att: Attachment | None = None
            if orig_bytes:
                stored = self._storage.save_image_bytes(orig_bytes, "png")
                orig_att = Attachment(
                    capture_entry_id=entry.id,
                    kind="screenshot",
                    stored_rel_path=stored.stored_rel_path,
                    mime_type=stored.mime_type,
                    byte_size=stored.byte_size,
                    sha256=stored.sha256,
                )
                attachments.append(orig_att)

            if ann_bytes:
                stored_ann = self._storage.save_image_bytes(ann_bytes, "png")
                attachments.append(
                    Attachment(
                        capture_entry_id=entry.id,
                        original_attachment_id=orig_att.id if orig_att is not None else None,
                        kind="annotated_screenshot",
                        stored_rel_path=stored_ann.stored_rel_path,
                        mime_type=stored_ann.mime_type,
                        byte_size=stored_ann.byte_size,
                        sha256=stored_ann.sha256,
                    )
                )

        for raw_path in external_image_paths:
            stored_img = self._storage.import_external_image(Path(raw_path))
            attachments.append(
                Attachment(
                    capture_entry_id=entry.id,
                    kind="image",
                    stored_rel_path=stored_img.stored_rel_path,
                    mime_type=stored_img.mime_type,
                    byte_size=stored_img.byte_size,
                    sha256=stored_img.sha256,
                )
            )

        if keep_audio and audio_src is not None:
            stored_audio = self._storage.store_audio_file(audio_src)
            attachments.append(
                Attachment(
                    capture_entry_id=entry.id,
                    kind="audio",
                    stored_rel_path=stored_audio.stored_rel_path,
                    mime_type=stored_audio.mime_type,
                    byte_size=stored_audio.byte_size,
                    sha256=stored_audio.sha256,
                )
            )
        elif audio_src is not None and audio_retention == "text":
            drafts_root = self._app_paths.drafts_dir.expanduser().resolve(strict=False)
            if audio_src.is_file() and audio_src.is_relative_to(drafts_root):
                try:
                    audio_src.unlink()
                except OSError as exc:
                    logger.warning("Failed to clean up text-only draft audio %s: %s", audio_src, exc)

        self._repo.create(entry, attachments)
        self.clear_draft()
        if self._bus is not None:
            self._bus.capture_saved.emit(entry)
            if entry.is_milestone:
                self._bus.milestone_updated.emit("capture", entry.id, True)
            self._bus.status_message.emit("Memory saved to project history")
        return entry, attachments

    create_capture = save_capture

    def list_project_captures(self, project_id: str, *, limit: int = 50) -> list[CaptureEntry]:
        """Return recent captures for a project."""
        return self._repo.list_recent(project_id=project_id, limit=limit)

    def list_attachments(self, capture_id: str) -> list[Attachment]:
        """Return attachments belonging to ``capture_id``."""
        return self._repo.list_attachments(capture_id)

    def save_draft(
        self,
        *,
        project_id: str | None,
        linked_file: str = "",
        note_text: str = "",
        preview_image_bytes: bytes | None = None,
        is_milestone: bool = False,
        draft_audio_path: str | Path | None = None,
        draft_transcript: str = "",
        audio_retention: str = "both",
    ) -> CaptureDraft:
        """Persist unfinished capture state strictly inside app-owned ``drafts/``."""
        drafts_dir = self._app_paths.drafts_dir.expanduser().resolve(strict=False)
        draft_json = drafts_dir / "draft.json"
        preview_file = drafts_dir / "draft_preview.png"
        roots = self._workspace_roots()
        assert_not_inside_monitored_workspace(draft_json, roots)
        assert_not_inside_monitored_workspace(preview_file, roots)

        drafts_dir.mkdir(parents=True, exist_ok=True)
        temp_img_str: str | None = None
        if preview_image_bytes:
            preview_file.write_bytes(preview_image_bytes)
            temp_img_str = str(preview_file)
        elif preview_file.is_file():
            preview_file.unlink()

        audio_str = str(draft_audio_path) if draft_audio_path else None
        retention = audio_retention if audio_retention in ("both", "text", "audio") else "both"
        now = utc_now_iso()
        payload = {
            "project_id": project_id or None,
            "linked_file": linked_file.strip(),
            "note_text": note_text,
            "temp_image_path": temp_img_str,
            "is_milestone": bool(is_milestone),
            "draft_audio_path": audio_str,
            "draft_transcript": draft_transcript,
            "audio_retention": retention,
            "updated_at_utc": now,
        }
        draft_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return CaptureDraft(
            project_id=payload["project_id"],  # type: ignore[arg-type]
            linked_file=str(payload["linked_file"]),
            note_text=str(payload["note_text"]),
            temp_image_path=temp_img_str,
            is_milestone=bool(is_milestone),
            draft_audio_path=audio_str,
            draft_transcript=draft_transcript,
            audio_retention=retention,
            updated_at_utc=now,
        )

    def load_draft(self) -> CaptureDraft | None:
        """Load any saved unfinished capture draft from ``drafts/``, or ``None``."""
        draft_json = self._app_paths.drafts_dir / "draft.json"
        if not draft_json.is_file():
            return None
        try:
            data = json.loads(draft_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable capture draft %s: %s", draft_json, exc)
            return None
        if not isinstance(data, dict):
            return None
        temp_path = data.get("temp_image_path")
        if temp_path and not Path(str(temp_path)).is_file():
            temp_path = None
        audio_path = data.get("draft_audio_path")
        if audio_path and not Path(str(audio_path)).is_file():
            audio_path = None
        note = str(data.get("note_text") or "")
        linked = str(data.get("linked_file") or "")
        transcript = str(data.get("draft_transcript") or "")
        retention = str(data.get("audio_retention") or "both")
        if retention not in ("both", "text", "audio"):
            retention = "both"
        if not note.strip() and not linked.strip() and not temp_path and not audio_path and not transcript.strip():
            return None
        return CaptureDraft(
            project_id=str(data["project_id"]) if data.get("project_id") else None,
            linked_file=linked,
            note_text=note,
            temp_image_path=str(temp_path) if temp_path else None,
            is_milestone=bool(data.get("is_milestone", False)),
            draft_audio_path=str(audio_path) if audio_path else None,
            draft_transcript=transcript,
            audio_retention=retention,
            updated_at_utc=str(data.get("updated_at_utc") or ""),
        )

    def has_draft(self) -> bool:
        """Return ``True`` when a recoverable non-empty draft exists."""
        return self.load_draft() is not None

    def clear_draft(self) -> None:
        """Remove any saved draft files from app-owned ``drafts/``."""
        drafts_dir = self._app_paths.drafts_dir
        targets: list[Path] = [drafts_dir / "draft.json", drafts_dir / "draft_preview.png"]
        if drafts_dir.is_dir():
            targets.extend(drafts_dir.glob("draft_audio_*.wav"))
        for target in targets:
            if target.is_file():
                try:
                    target.unlink()
                except OSError as exc:
                    logger.warning("Failed to remove draft file %s: %s", target, exc)

    def _workspace_roots(self) -> list[Path]:
        if self._ws_service is None:
            return []
        return [Path(ws.root_path) for ws in self._ws_service.cached_workspaces()]
