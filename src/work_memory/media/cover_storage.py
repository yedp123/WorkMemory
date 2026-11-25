"""Read-only image loader and app-owned cover storage inside ``covers/``."""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader

from work_memory.config.paths import assert_not_inside_monitored_workspace
from work_memory.core.ids import new_id
from work_memory.services.archive_safety import safe_archive_member_path

logger = logging.getLogger(__name__)
MAX_COVER_WIDTH = 1280


def save_project_cover(
    source_path: Path | str,
    covers_dir: Path,
    workspace_roots: Sequence[Path] = (),
) -> str:
    """Read ``source_path`` read-only, downscale if >1280px wide, and save in ``covers_dir``."""
    src = Path(source_path).expanduser().resolve(strict=False)
    if not src.is_file():
        raise FileNotFoundError(f"Cover image does not exist: {src}")

    reader = QImageReader(str(src))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        err = reader.errorString() or "Unsupported or unreadable image"
        raise ValueError(f"Could not read image '{src.name}': {err}")

    if image.width() > MAX_COVER_WIDTH:
        image = image.scaledToWidth(
            MAX_COVER_WIDTH, Qt.TransformationMode.SmoothTransformation
        )

    use_png = image.hasAlphaChannel()
    ext = "png" if use_png else "jpg"
    filename = f"{new_id()}.{ext}"

    resolved_covers = Path(covers_dir).expanduser().resolve(strict=False)
    dest = (resolved_covers / filename).resolve(strict=False)
    assert_not_inside_monitored_workspace(dest, list(workspace_roots))
    if not dest.is_relative_to(resolved_covers):
        raise PermissionError(f"Cover target escapes covers_dir: {dest}")

    resolved_covers.mkdir(parents=True, exist_ok=True)
    saved = image.save(str(dest), "PNG" if use_png else "JPG", -1 if use_png else 90)
    if not saved or not dest.is_file():
        raise OSError(f"Failed to write resized project cover to {dest}")
    return filename


def resolve_cover_path(covers_dir: Path, cover_filename: str | None) -> Path | None:
    """Resolve a bare cover filename inside ``covers_dir`` safely, or return ``None``."""
    if not cover_filename:
        return None
    clean = cover_filename.strip()
    if not clean or "/" in clean or "\\" in clean or ".." in clean:
        return None
    resolved_covers = Path(covers_dir).expanduser().resolve(strict=False)
    candidate = (resolved_covers / clean).resolve(strict=False)
    if candidate.parent != resolved_covers or not candidate.is_file():
        return None
    return candidate


def delete_cover_file(
    covers_dir: Path,
    cover_filename: str | None,
    workspace_roots: Sequence[Path] = (),
) -> bool:
    """Delete an app-owned cover file inside ``covers_dir`` if present."""
    target = resolve_cover_path(covers_dir, cover_filename)
    if target is None:
        return False
    assert_not_inside_monitored_workspace(target, list(workspace_roots))
    try:
        target.unlink()
        return True
    except OSError as exc:
        logger.warning("Failed to remove old cover file %s: %s", target, exc)
        return False


def export_cover_entry(covers_dir: Path, cover_filename: str | None) -> tuple[str, Path] | None:
    """Return ``(archive_path, src_path)`` if ``cover_filename`` resolves cleanly."""
    if (src := resolve_cover_path(covers_dir, cover_filename)) is None:
        return None
    return f"covers/{src.name}", src


def import_cover_from_zip(
    zf: zipfile.ZipFile,
    cover_filename: str | None,
    covers_dir: Path,
    workspace_roots: Sequence[Path],
    *,
    rename_copy: bool = False,
) -> str | None:
    """Extract a validated project cover image from ``zf`` into app-owned ``covers_dir``."""
    if not cover_filename:
        return None
    clean = Path(safe_archive_member_path(str(cover_filename).strip()).as_posix()).name
    arc = f"covers/{clean}"
    if arc not in zf.namelist():
        return None
    ext = Path(clean).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return None
    out_name = f"{new_id()}{ext}" if rename_copy else clean
    resolved_covers = Path(covers_dir).expanduser().resolve(strict=False)
    dest = (resolved_covers / out_name).resolve(strict=False)
    assert_not_inside_monitored_workspace(dest, list(workspace_roots))
    if dest.parent != resolved_covers:
        raise PermissionError(f"Cover target escapes covers_dir: {dest}")
    resolved_covers.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(zf.read(arc))
    return out_name
