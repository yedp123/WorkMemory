"""Safe read-only helpers for opening files and revealing them in Windows Explorer."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap

logger = logging.getLogger(__name__)


def build_folder_icon(color_hex: str = "#9aa3af", size: int = 16) -> QIcon:
    """Draw a crisp monochrome vector folder icon without external image assets."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    path = QPainterPath()
    path.moveTo(s * 0.14, s * 0.25)
    path.lineTo(s * 0.42, s * 0.25)
    path.lineTo(s * 0.52, s * 0.36)
    path.lineTo(s * 0.86, s * 0.36)
    path.lineTo(s * 0.86, s * 0.78)
    path.lineTo(s * 0.14, s * 0.78)
    path.closeSubpath()

    color = QColor(color_hex)
    fill = QColor(color)
    fill.setAlpha(38)
    pen = QPen(color, 1.35)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(fill)
    painter.drawPath(path)
    painter.drawLine(QPointF(s * 0.14, s * 0.44), QPointF(s * 0.86, s * 0.44))
    painter.end()
    return QIcon(pm)


def open_file_default(abs_path: Path) -> tuple[bool, str]:
    """Open ``abs_path`` in the user's OS default application."""
    if not abs_path.exists():
        return False, "missing"
    ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_path)))
    return (True, "opened") if ok else (False, "error")


def build_reveal_command(
    abs_path: Path, *, root_bound: Path | None = None
) -> tuple[list[str] | None, str]:
    """Build the Windows Explorer command to highlight ``abs_path`` or open its nearest parent."""
    target = Path(os.path.normpath(os.fspath(abs_path)))
    if target.exists():
        return ["explorer", "/select,", os.path.normpath(os.fspath(target))], "revealed"

    resolved_bound = root_bound.expanduser().resolve(strict=False) if root_bound is not None else None
    cur = target.parent
    while True:
        if resolved_bound is not None and not cur.resolve(strict=False).is_relative_to(resolved_bound):
            break
        if cur.is_dir():
            return ["explorer", os.path.normpath(os.fspath(cur))], "parent_opened"
        if cur.parent == cur:
            break
        cur = cur.parent
    return None, "missing"


def reveal_in_folder(
    abs_path: Path, *, root_bound: Path | None = None
) -> tuple[bool, str]:
    """Launch Windows Explorer highlighting ``abs_path`` (or its nearest existing parent)."""
    cmd, status = build_reveal_command(abs_path, root_bound=root_bound)
    if cmd is None:
        return False, status
    try:
        subprocess.Popen(cmd, shell=False)
    except OSError as exc:
        logger.warning("Failed to reveal path in Explorer (%s): %s", cmd, exc)
        return False, "error"
    return True, status
