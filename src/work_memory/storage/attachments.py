"""App-owned attachment storage isolated from monitored user workspaces."""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from work_memory.config.paths import assert_not_inside_monitored_workspace
from work_memory.core.ids import new_id

_ALLOWED_IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff"})


@dataclass(frozen=True, slots=True)
class StoredAttachmentFile:
    """Metadata returned after writing an app-owned attachment file."""

    stored_rel_path: str
    abs_path: Path
    mime_type: str
    byte_size: int
    sha256: str


class AttachmentStorage:
    """Manages read-safe attachment copies strictly inside ``attachments_dir``."""

    def __init__(
        self,
        attachments_dir: Path,
        workspace_roots_provider: Callable[[], list[Path]] | None = None,
    ) -> None:
        self._dir = Path(attachments_dir).expanduser().resolve(strict=False)
        self._workspace_roots_provider = workspace_roots_provider

    @property
    def attachments_dir(self) -> Path:
        """Return the resolved root directory for app-owned attachments."""
        return self._dir

    def save_image_bytes(self, data: bytes, ext: str = "png") -> StoredAttachmentFile:
        """Persist raw image bytes inside ``attachments_dir`` using a UUIDv7 filename."""
        if not data:
            raise ValueError("Cannot save empty attachment data.")
        clean_ext = self._normalize_ext(ext)
        rel_path, target = self._allocate_target(clean_ext)
        assert_not_inside_monitored_workspace(target, self._workspace_roots())

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        digest = hashlib.sha256(data).hexdigest()
        mime = mimetypes.guess_type(f"file.{clean_ext}")[0] or "image/png"
        return StoredAttachmentFile(
            stored_rel_path=rel_path,
            abs_path=target,
            mime_type=mime,
            byte_size=len(data),
            sha256=digest,
        )

    def import_external_image(self, source_path: Path | str) -> StoredAttachmentFile:
        """Copy an external image into ``attachments_dir`` strictly read-only on source."""
        src = Path(source_path).expanduser().resolve(strict=False)
        if not src.is_file():
            raise FileNotFoundError(f"Source image does not exist: {src}")

        clean_ext = self._normalize_ext(src.suffix)
        rel_path, target = self._allocate_target(clean_ext)
        assert_not_inside_monitored_workspace(target, self._workspace_roots())

        target.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        total = 0
        with src.open("rb") as reader, target.open("wb") as writer:
            while chunk := reader.read(65536):
                writer.write(chunk)
                hasher.update(chunk)
                total += len(chunk)

        mime = mimetypes.guess_type(str(src))[0] or "image/png"
        return StoredAttachmentFile(
            stored_rel_path=rel_path,
            abs_path=target,
            mime_type=mime,
            byte_size=total,
            sha256=hasher.hexdigest(),
        )

    def save_audio_file(self, temp_wav_path: Path | str) -> Path:
        """Copy a temporary WAV file into ``attachments_dir`` using a UUIDv7 filename."""
        return self.store_audio_file(temp_wav_path).abs_path

    def store_audio_file(self, temp_wav_path: Path | str) -> StoredAttachmentFile:
        """Copy a temporary WAV file into ``attachments_dir`` and return metadata."""
        src = Path(temp_wav_path).expanduser().resolve(strict=False)
        if not src.is_file():
            raise FileNotFoundError(f"Source audio file does not exist: {src}")

        rel_path, target = self._allocate_target("wav")
        assert_not_inside_monitored_workspace(target, self._workspace_roots())

        target.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        total = 0
        with src.open("rb") as reader, target.open("wb") as writer:
            while chunk := reader.read(65536):
                writer.write(chunk)
                hasher.update(chunk)
                total += len(chunk)

        return StoredAttachmentFile(
            stored_rel_path=rel_path,
            abs_path=target,
            mime_type="audio/wav",
            byte_size=total,
            sha256=hasher.hexdigest(),
        )

    def resolve_path(self, stored_rel_path: str) -> Path:
        """Resolve a stored POSIX relative path inside ``attachments_dir`` safely."""
        rel = stored_rel_path.replace("\\", "/").lstrip("/")
        candidate = (self._dir / rel).resolve(strict=False)
        if not candidate.is_relative_to(self._dir):
            raise PermissionError(f"Invalid attachment path outside storage: {stored_rel_path!r}")
        return candidate

    def delete_stored(self, stored_rel_path: str) -> bool:
        """Delete an app-owned attachment file if it exists inside ``attachments_dir``."""
        target = self.resolve_path(stored_rel_path)
        assert_not_inside_monitored_workspace(target, self._workspace_roots())
        if target.is_file():
            target.unlink()
            return True
        return False

    def _allocate_target(self, clean_ext: str) -> tuple[str, Path]:
        now = datetime.now(UTC)
        rel = f"{now.strftime('%Y/%m')}/{new_id()}.{clean_ext}"
        return rel, self.resolve_path(rel)

    @staticmethod
    def _normalize_ext(ext: str) -> str:
        clean = ext.strip().lower().lstrip(".")
        return clean if clean in _ALLOWED_IMAGE_EXTS else "png"

    def _workspace_roots(self) -> list[Path]:
        return self._workspace_roots_provider() if self._workspace_roots_provider else []
