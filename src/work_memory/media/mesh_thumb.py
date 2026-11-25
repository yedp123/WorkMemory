"""Clay-shaded software 3D thumbnail renderer producing ``QImage`` off the GUI thread."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from work_memory.media.mesh_parsers import (
    MeshInfo,
    extract_3mf_thumbnail_bytes,
    parse_3mf_model,
    parse_obj,
    parse_stl,
)

_BG_COLOR = QColor("#1b1f25")


def _rotation_matrix(yaw_deg: float = -35.0, pitch_deg: float = 25.0) -> np.ndarray:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float32)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]], dtype=np.float32)
    return rx @ ry


_ISO_ROT = _rotation_matrix()
_KEY_LIGHT = np.array([0.45, 0.65, 0.61], dtype=np.float32)
_KEY_LIGHT /= float(np.linalg.norm(_KEY_LIGHT))
_RIM_LIGHT = np.array([-0.60, 0.25, 0.76], dtype=np.float32)
_RIM_LIGHT /= float(np.linalg.norm(_RIM_LIGHT))


def render_3d_thumbnail(path: Path, size_px: int = 128) -> tuple[QImage, MeshInfo] | None:
    """Render a read-only ``QImage`` preview for ``.3mf``, ``.stl``, or ``.obj``."""
    ext = path.suffix.lower()
    if ext == ".3mf":
        if (embedded := extract_3mf_thumbnail_bytes(path)) is not None:
            raw_bytes, label = embedded
            img = QImage.fromData(raw_bytes)
            if not img.isNull():
                return _fit_on_dark_canvas(img, size_px), MeshInfo(0, 0, label)
        parsed = parse_3mf_model(path)
    elif ext == ".stl":
        parsed = parse_stl(path)
    elif ext == ".obj":
        parsed = parse_obj(path)
    else:
        return None

    if parsed is None or len(parsed.triangles) == 0:
        return None
    img = _render_clay_mesh(parsed.triangles, size_px)
    return (img, parsed.info) if not img.isNull() else None


def _fit_on_dark_canvas(source: QImage, size_px: int) -> QImage:
    canvas = QImage(size_px, size_px, QImage.Format.Format_ARGB32)
    canvas.fill(_BG_COLOR)
    scaled = source.scaled(
        size_px,
        size_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(canvas)
    x = (size_px - scaled.width()) // 2
    y = (size_px - scaled.height()) // 2
    painter.drawImage(x, y, scaled)
    painter.end()
    return canvas


def _render_clay_mesh(triangles: np.ndarray, size_px: int) -> QImage:
    flat = triangles.reshape(-1, 3)
    vmin = flat.min(axis=0)
    vmax = flat.max(axis=0)
    extent = float(np.max(vmax - vmin))
    if extent <= 1e-8 or not math.isfinite(extent):
        return QImage()

    center = (vmin + vmax) * 0.5
    normed = (triangles - center) / extent
    rotated = normed @ _ISO_ROT.T

    v0, v1, v2 = rotated[:, 0, :], rotated[:, 1, :], rotated[:, 2, :]
    normals = np.cross(v1 - v0, v2 - v0)
    lengths = np.linalg.norm(normals, axis=1)
    keep = lengths > 1e-9
    if not np.any(keep):
        return QImage()

    rotated = rotated[keep]
    normals = normals[keep] / lengths[keep, None]

    # Cull backfaces where possible; if winding is inverted on the whole mesh, flip.
    front = normals[:, 2] > 0.0
    if not np.any(front):
        normals = -normals
        front = normals[:, 2] > 0.0
    rotated = rotated[front]
    normals = normals[front]
    if len(rotated) == 0:
        return QImage()

    order = np.argsort(rotated[:, :, 2].mean(axis=1))
    rotated = rotated[order]
    normals = normals[order]

    key_dot = np.clip(normals @ _KEY_LIGHT, 0.0, 1.0)
    rim_dot = np.clip(normals @ _RIM_LIGHT, 0.0, 1.0)
    shade = np.clip(0.26 + 0.58 * key_dot + 0.16 * rim_dot, 0.18, 1.0)

    pts_xy = rotated[:, :, :2]
    span = float(max(np.ptp(pts_xy[:, :, 0]), np.ptp(pts_xy[:, :, 1]), 1e-5))
    margin = size_px * 0.10
    scale = (size_px - 2.0 * margin) / span
    cx = float((pts_xy[:, :, 0].min() + pts_xy[:, :, 0].max()) * 0.5)
    cy = float((pts_xy[:, :, 1].min() + pts_xy[:, :, 1].max()) * 0.5)
    sx = size_px * 0.5 + (pts_xy[:, :, 0] - cx) * scale
    sy = size_px * 0.5 - (pts_xy[:, :, 1] - cy) * scale

    img = QImage(size_px, size_px, QImage.Format.Format_ARGB32)
    img.fill(_BG_COLOR)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, size_px >= 96)

    for idx in range(len(rotated)):
        s = float(shade[idx])
        color = QColor(int(188 * s), int(196 * s), int(208 * s))
        painter.setBrush(color)
        painter.setPen(QPen(color, 0.6))
        poly = QPolygonF(
            [
                QPointF(float(sx[idx, 0]), float(sy[idx, 0])),
                QPointF(float(sx[idx, 1]), float(sy[idx, 1])),
                QPointF(float(sx[idx, 2]), float(sy[idx, 2])),
            ]
        )
        painter.drawPolygon(poly)
    painter.end()
    return img
