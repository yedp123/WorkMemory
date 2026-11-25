"""Pure geometry, 8-handle hit-testing, and scrim/border painters for CaptureOverlay."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen

HandleKind = Literal["nw", "n", "ne", "e", "se", "s", "sw", "w", "move"]

ACCENT_GREEN = QColor("#6ec494")
SCRIM_COLOR = QColor(0, 0, 0, 125)
_HANDLE_SPECS: tuple[tuple[HandleKind, float, float], ...] = (
    ("nw", 0.0, 0.0),
    ("n", 0.5, 0.0),
    ("ne", 1.0, 0.0),
    ("e", 1.0, 0.5),
    ("se", 1.0, 1.0),
    ("s", 0.5, 1.0),
    ("sw", 0.0, 1.0),
    ("w", 0.0, 0.5),
)


def handle_points(sel: QRect) -> dict[HandleKind, QPoint]:
    """Return center points for all 8 resize handles around ``sel``."""
    return {
        kind: QPoint(
            round(sel.left() + sel.width() * fx),
            round(sel.top() + sel.height() * fy),
        )
        for kind, fx, fy in _HANDLE_SPECS
    }


def hit_test_handle(sel: QRect, pos: QPoint, *, radius: int = 8) -> HandleKind | None:
    """Return which resize handle (or ``'move'`` inside ``sel``) contains ``pos``."""
    for kind, center in handle_points(sel).items():
        if abs(pos.x() - center.x()) <= radius and abs(pos.y() - center.y()) <= radius:
            return kind
    if sel.contains(pos):
        return "move"
    return None


def cursor_for_handle(handle: HandleKind | None) -> Qt.CursorShape:
    """Map a hit-test handle to its corresponding Qt resize/move cursor."""
    if handle in ("nw", "se"):
        return Qt.CursorShape.SizeFDiagCursor
    if handle in ("ne", "sw"):
        return Qt.CursorShape.SizeBDiagCursor
    if handle in ("n", "s"):
        return Qt.CursorShape.SizeVerCursor
    if handle in ("e", "w"):
        return Qt.CursorShape.SizeHorCursor
    if handle == "move":
        return Qt.CursorShape.SizeAllCursor
    return Qt.CursorShape.ArrowCursor


def apply_handle_drag(
    start_rect: QRect,
    handle: HandleKind,
    delta: QPoint,
    bounds: QRect,
    *,
    min_size: int = 10,
) -> QRect:
    """Compute a clamped selection ``QRect`` after dragging a resize handle or moving."""
    if handle == "move":
        nx = max(bounds.left(), min(start_rect.left() + delta.x(), bounds.right() - start_rect.width() + 1))
        ny = max(bounds.top(), min(start_rect.top() + delta.y(), bounds.bottom() - start_rect.height() + 1))
        return QRect(nx, ny, start_rect.width(), start_rect.height())

    left, top, right, bottom = start_rect.left(), start_rect.top(), start_rect.right(), start_rect.bottom()
    if "w" in handle:
        left = max(bounds.left(), min(left + delta.x(), right - min_size + 1))
    if "e" in handle:
        right = min(bounds.right(), max(right + delta.x(), left + min_size - 1))
    if "n" in handle:
        top = max(bounds.top(), min(top + delta.y(), bottom - min_size + 1))
    if "s" in handle:
        bottom = min(bounds.bottom(), max(bottom + delta.y(), top + min_size - 1))
    return QRect(QPoint(left, top), QPoint(right, bottom))


def active_screen_bounds_local(selection: QRect, virtual_rect: QRect, fallback: QRect) -> QRect:
    """Return the monitor rect (in overlay-local coords) containing ``selection``."""
    global_pt = selection.center() + virtual_rect.topLeft()
    scr = QGuiApplication.screenAt(global_pt) or QGuiApplication.primaryScreen()
    if scr is None:
        return fallback
    local_geo = scr.geometry().translated(-virtual_rect.topLeft()).intersected(fallback)
    return local_geo if not local_geo.isEmpty() else fallback


def paint_outer_scrim(painter: QPainter, full_rect: QRect, sel: QRect) -> None:
    """Dim the area outside ``sel`` while keeping ``sel`` 100% clear."""
    if sel.isEmpty():
        painter.fillRect(full_rect, SCRIM_COLOR)
        return
    painter.fillRect(QRect(full_rect.left(), full_rect.top(), full_rect.width(), max(0, sel.top() - full_rect.top())), SCRIM_COLOR)
    bottom_y = sel.bottom() + 1
    painter.fillRect(QRect(full_rect.left(), bottom_y, full_rect.width(), max(0, full_rect.bottom() - sel.bottom())), SCRIM_COLOR)
    painter.fillRect(QRect(full_rect.left(), sel.top(), max(0, sel.left() - full_rect.left()), sel.height()), SCRIM_COLOR)
    right_x = sel.right() + 1
    painter.fillRect(QRect(right_x, sel.top(), max(0, full_rect.right() - sel.right()), sel.height()), SCRIM_COLOR)


def paint_selection_chrome(
    painter: QPainter,
    sel: QRect,
    full_rect: QRect,
    *,
    dpr: float,
    show_handles: bool,
) -> None:
    """Draw the crisp 2px green border, optional 8 resize handles, and pixel size pill."""
    painter.save()
    painter.setPen(QPen(ACCENT_GREEN, 2.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(sel)

    if show_handles:
        painter.setPen(QPen(QColor("#17191d"), 1.0))
        painter.setBrush(ACCENT_GREEN)
        for center in handle_points(sel).values():
            painter.drawRect(QRect(center.x() - 4, center.y() - 4, 8, 8))

    px_w = max(1, round(sel.width() * dpr))
    px_h = max(1, round(sel.height() * dpr))
    label = f"{px_w} \u00d7 {px_h}"
    font = QFont("Segoe UI", 10)
    font.setBold(True)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    bw, bh = metrics.horizontalAdvance(label) + 14, metrics.height() + 6
    bx = max(6, min(sel.left(), full_rect.right() - bw - 6))
    by = sel.top() - bh - 6 if sel.top() >= bh + 10 else min(sel.top() + 6, full_rect.bottom() - bh - 6)
    pill = QRect(bx, by, bw, bh)
    painter.setPen(QPen(QColor("#30353d"), 1.0))
    painter.setBrush(QColor(23, 25, 29, 230))
    painter.drawRoundedRect(pill, 5.0, 5.0)
    painter.setPen(QColor("#edf0f3"))
    painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
    painter.restore()
