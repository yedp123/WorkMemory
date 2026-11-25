"""Shared Zip-Slip validation and SHA-256 helpers for portable bundles and backups."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path, PurePosixPath

_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")
MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def safe_archive_member_path(member_name: str) -> PurePosixPath:
    """Validate a ZIP member path against Zip-Slip traversal and return a ``PurePosixPath``."""
    raw = member_name.replace("\\", "/")
    if not raw or raw.startswith(("/", "//")) or _DRIVE_PREFIX_RE.match(raw):
        raise ValueError(f"Unsafe archive member path: {member_name!r}")
    parts = [p for p in raw.split("/") if p]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError(f"Unsafe archive member path traversal: {member_name!r}")
    return PurePosixPath(*parts)


def validate_zip_limits(
    zf: zipfile.ZipFile,
    *,
    max_member_bytes: int = MAX_ARCHIVE_MEMBER_BYTES,
    max_total_bytes: int = MAX_ARCHIVE_TOTAL_BYTES,
) -> None:
    """Reject ZIP archives whose declared uncompressed sizes exceed safe bounds."""
    total = 0
    for info in zf.infolist():
        if info.file_size < 0 or info.file_size > max_member_bytes:
            raise ValueError(
                f"Archive member {info.filename!r} exceeds size limit ({info.file_size} bytes)."
            )
        total += info.file_size
        if total > max_total_bytes:
            raise ValueError(f"Archive total uncompressed size exceeds {max_total_bytes} bytes.")


def validate_zip_members(
    zf: zipfile.ZipFile,
    *,
    max_member_bytes: int = MAX_ARCHIVE_MEMBER_BYTES,
    max_total_bytes: int = MAX_ARCHIVE_TOTAL_BYTES,
) -> None:
    """Reject any ZIP archive with unsafe paths or excessive uncompressed sizes."""
    for info in zf.infolist():
        if info.is_dir():
            # Allow directory entries like "attachments/" if their path parts are safe.
            trimmed = info.filename.rstrip("/\\")
            if trimmed:
                safe_archive_member_path(trimmed)
            continue
        safe_archive_member_path(info.filename)
    validate_zip_limits(zf, max_member_bytes=max_member_bytes, max_total_bytes=max_total_bytes)


def sha256_bytes(data: bytes) -> str:
    """Return lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Stream-compute lowercase hex SHA-256 digest of a file read-only."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()
