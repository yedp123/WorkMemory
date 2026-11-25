"""Asynchronous read-only thumbnail generator and app-owned disk cache."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from PySide6.QtCore import QObject, QPointF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPolygonF

from work_memory.config.paths import assert_not_inside_monitored_workspace
from work_memory.media.mesh_thumb import render_3d_thumbnail

logger = logging.getLogger(__name__)

MediaKind = Literal["image", "video", "model_3d"]
IMAGE_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm"})
MODEL_3D_EXTS: frozenset[str] = frozenset({".3mf", ".stl", ".obj"})


@dataclass(frozen=True, slots=True)
class MediaPreviewData:
    """High-resolution preview image and metadata for ``MediaPreviewDialog``."""

    kind: MediaKind
    abs_path: Path
    file_size: int
    image: QImage | None
    info_label: str = ""


def get_media_kind(path_or_rel: Path | str) -> MediaKind | None:
    """Return ``'image'``, ``'video'``, or ``'model_3d'`` for supported extensions."""
    raw = str(path_or_rel).strip()
    if " .. " in raw:
        raw = raw.split(" .. ", 1)[0].strip()
    ext = PurePosixPath(raw.replace("\\", "/")).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in MODEL_3D_EXTS:
        return "model_3d"
    return None


class _ResultBridge(QObject):
    done = Signal(object, object)


class _ThumbRunnable(QRunnable):
    def __init__(self, fn: Callable[[], object], cb: Callable[[object], None], bridge: _ResultBridge) -> None:
        super().__init__()
        self._fn, self._cb, self._bridge = fn, cb, bridge

    def run(self) -> None:
        try:
            res = self._fn()
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.debug("Thumbnail worker failed: %s", exc)
            res = None
        self._bridge.done.emit(self._cb, res)


class ThumbnailService(QObject):
    """Generates and caches read-only image, video, and 3D thumbnails off the GUI thread."""

    def __init__(
        self,
        thumbs_cache_dir: Path,
        *,
        path_resolver: Callable[[str, str | None, str | None], Path | None] | None = None,
        workspace_roots_provider: Callable[[], Sequence[Path]] | None = None,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache_dir = Path(thumbs_cache_dir).expanduser().resolve(strict=False)
        self._path_resolver = path_resolver
        self._ws_provider = workspace_roots_provider
        self._pool = thread_pool or QThreadPool.globalInstance()
        self._bridge = _ResultBridge(self)
        self._bridge.done.connect(lambda cb, res: cb(res))

    def set_path_resolver(
        self, resolver: Callable[[str, str | None, str | None], Path | None] | None
    ) -> None:
        """Attach or replace the off-thread relative-path resolver."""
        self._path_resolver = resolver

    def request_thumbnail(
        self,
        rel_or_abs: str,
        *,
        project_id: str | None = None,
        workspace_id: str | None = None,
        size_px: int = 76,
        callback: Callable[[QImage | None], None],
    ) -> None:
        """Resolve ``rel_or_abs`` and generate a cached ``QImage`` off the GUI thread."""

        def _work() -> QImage | None:
            if self._path_resolver is not None:
                target = self._path_resolver(rel_or_abs, project_id, workspace_id)
            else:
                target = Path(rel_or_abs)
            if target is None or not target.is_file():
                return None
            return self.generate_thumbnail(target, size_px=size_px)

        self._pool.start(_ThumbRunnable(_work, callback, self._bridge))  # type: ignore[arg-type]

    def request_preview(
        self,
        abs_path: Path,
        *,
        size_px: int = 640,
        callback: Callable[[MediaPreviewData], None],
    ) -> None:
        """Generate a high-resolution preview payload off the GUI thread."""
        self._pool.start(
            _ThumbRunnable(lambda: self.build_preview_sync(abs_path, size_px=size_px), callback, self._bridge)  # type: ignore[arg-type]
        )

    def generate_thumbnail(self, abs_path: Path, *, size_px: int = 76) -> QImage | None:
        """Generate or load a cached ``QImage`` thumbnail for ``abs_path``."""
        if not abs_path.is_file():
            return None
        kind = get_media_kind(abs_path)
        if kind is None:
            return None
        try:
            st = abs_path.stat()
        except OSError:
            return None

        cache_file = self._cache_path(abs_path, st.st_mtime_ns, st.st_size, size_px)
        if cache_file.is_file():
            cached = QImage(str(cache_file))
            if not cached.isNull():
                return cached

        img: QImage | None = None
        if kind == "image":
            img = _render_image_thumb(abs_path, size_px)
        elif kind == "video":
            img = _render_video_thumb(abs_path, size_px, draw_play_badge=(size_px <= 96))
        elif kind == "model_3d":
            res = render_3d_thumbnail(abs_path, size_px)
            img = res[0] if res is not None else None

        if img is None or img.isNull():
            return None
        self._save_cache_image(cache_file, img)
        return img

    def build_preview_sync(self, abs_path: Path, *, size_px: int = 640) -> MediaPreviewData:
        """Build high-resolution preview image and metadata for ``MediaPreviewDialog``."""
        kind = get_media_kind(abs_path) or "image"
        try:
            file_size = abs_path.stat().st_size if abs_path.is_file() else 0
        except OSError:
            file_size = 0

        if not abs_path.is_file():
            return MediaPreviewData(kind, abs_path, 0, None, "File not found on disk")

        if kind == "image":
            reader = QImageReader(str(abs_path))
            reader.setAutoTransform(True)
            orig_size = reader.size()
            img = reader.read()
            info = f"{orig_size.width()} \u00d7 {orig_size.height()} px" if orig_size.isValid() else "Image"
            return MediaPreviewData(kind, abs_path, file_size, None if img.isNull() else img, info)

        if kind == "model_3d":
            res = render_3d_thumbnail(abs_path, size_px)
            if res is None:
                return MediaPreviewData(kind, abs_path, file_size, None, "Unable to parse 3D geometry")
            img, mesh_info = res
            if mesh_info.triangle_count > 0:
                info = f"{mesh_info.vertex_count:,} vertices \u00b7 {mesh_info.triangle_count:,} triangles"
            else:
                info = mesh_info.label or "3D Model"
            return MediaPreviewData(kind, abs_path, file_size, img, info)

        img = _render_video_thumb(abs_path, size_px, draw_play_badge=False)
        return MediaPreviewData(kind, abs_path, file_size, img, "Video")

    def _cache_path(self, abs_path: Path, mtime_ns: int, file_size: int, size_px: int) -> Path:
        raw = f"{abs_path}|{mtime_ns}|{file_size}|{size_px}".encode("utf-8", errors="replace")
        digest = hashlib.sha256(raw).hexdigest()[:24]
        return (self._cache_dir / f"{digest}.png").resolve(strict=False)

    def _save_cache_image(self, cache_file: Path, image: QImage) -> None:
        roots = list(self._ws_provider()) if self._ws_provider is not None else []
        assert_not_inside_monitored_workspace(cache_file, roots)
        if not cache_file.is_relative_to(self._cache_dir):
            raise PermissionError(f"Thumbnail cache path escapes cache_dir: {cache_file}")
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(cache_file), "PNG")
        except OSError as exc:
            logger.debug("Unable to write thumbnail cache %s: %s", cache_file, exc)


def _render_image_thumb(abs_path: Path, size_px: int) -> QImage | None:
    reader = QImageReader(str(abs_path))
    reader.setAutoTransform(True)
    orig = reader.size()
    if orig.isValid() and orig.width() > 0 and orig.height() > 0:
        scaled = orig.scaled(QSize(size_px, size_px), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        reader.setScaledSize(scaled)
    img = reader.read()
    if img.isNull():
        return None
    if img.width() != size_px or img.height() != size_px:
        img = img.scaled(size_px, size_px, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = max(0, (img.width() - size_px) // 2)
        y = max(0, (img.height() - size_px) // 2)
        img = img.copy(x, y, min(size_px, img.width()), min(size_px, img.height()))
    return img


def _render_video_thumb(abs_path: Path, size_px: int, *, draw_play_badge: bool) -> QImage | None:
    try:
        import av  # type: ignore[import-untyped]
    except ImportError:
        return None
    container = None
    try:
        container = av.open(str(abs_path))
        video_stream = next((s for s in container.streams if s.type == "video"), None)
        if video_stream is None:
            return None
        if video_stream.duration and video_stream.duration > 10:
            try:
                container.seek(int(video_stream.duration * 0.1), stream=video_stream, any_frame=False, backward=True)
            except av.FFmpegError:
                pass
        frame = next(container.decode(video_stream), None)
        if frame is None:
            container.seek(0)
            frame = next(container.decode(video_stream), None)
        if frame is None:
            return None
        rgb = frame.to_ndarray(format="rgb24")
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
    except (av.FFmpegError, OSError, RuntimeError, ValueError, StopIteration) as exc:
        logger.debug("Video thumbnail failed for %s: %s", abs_path, exc)
        return None
    finally:
        if container is not None:
            try:
                container.close()
            except (av.FFmpegError, OSError, RuntimeError) as exc:
                logger.debug("Closing video container %s: %s", abs_path, exc)

    if draw_play_badge:
        scaled = qimg.scaled(size_px, size_px, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - size_px) // 2)
        y = max(0, (scaled.height() - size_px) // 2)
        out = scaled.copy(x, y, min(size_px, scaled.width()), min(size_px, scaled.height()))
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(18, 20, 24, 150))
        painter.setPen(Qt.PenStyle.NoPen)
        r = size_px * 0.28
        cx, cy = size_px * 0.5, size_px * 0.5
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setBrush(QColor(240, 244, 250, 230))
        tri = QPolygonF([
            QPointF(cx - r * 0.30, cy - r * 0.45),
            QPointF(cx + r * 0.52, cy),
            QPointF(cx - r * 0.30, cy + r * 0.45),
        ])
        painter.drawPolygon(tri)
        painter.end()
        return out
    return qimg.scaled(size_px, size_px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
