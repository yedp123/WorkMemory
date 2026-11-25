"""Multi-monitor, HiDPI frozen desktop capture and pixel-exact region cropping."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap, QScreen

logger = logging.getLogger(__name__)


def pixmap_to_png_bytes(pixmap: QPixmap) -> bytes:
    """Encode a ``QPixmap`` into PNG bytes in memory."""
    if pixmap.isNull():
        return b""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return bytes(buf.data())


def _virtual_geometry(screens: Sequence[QScreen]) -> QRect:
    rect = screens[0].geometry()
    for scr in screens[1:]:
        rect = rect.united(scr.geometry())
    return rect


def grab_virtual_desktop() -> tuple[QPixmap, QRect]:
    """Capture all screens at native DPR into one unified ``QPixmap`` and ``virtual_rect``."""
    screens = QGuiApplication.screens()
    if not screens:
        logger.warning("Virtual desktop grab aborted: no QScreen instances available.")
        return QPixmap(), QRect()

    virtual_rect = _virtual_geometry(screens)
    for idx, scr in enumerate(screens):
        geo = scr.geometry()
        dpr = scr.devicePixelRatio() or 1.0
        logger.info(
            "Detected screen %d (%s): geometry=%s, dpr=%.2f",
            idx,
            scr.name(),
            geo.getRect(),
            dpr,
        )

    if len(screens) == 1:
        scr = screens[0]
        dpr = scr.devicePixelRatio() or 1.0
        grab = scr.grabWindow(0)
        if grab.isNull():
            logger.warning("Single-screen grabWindow(0) returned null pixmap.")
            return QPixmap(), virtual_rect
        geo = scr.geometry()
        if (
            grab.devicePixelRatio() != dpr
            and grab.width() == round(geo.width() * dpr)
            and grab.height() == round(geo.height() * dpr)
        ):
            grab.setDevicePixelRatio(dpr)
        logger.info(
            "Virtual desktop grabbed: 1 screen, virtual_rect=%s, pixmap=%dx%d px, dpr=%.2f",
            virtual_rect.getRect(),
            grab.width(),
            grab.height(),
            grab.devicePixelRatio(),
        )
        return grab, virtual_rect

    max_dpr = max((scr.devicePixelRatio() or 1.0 for scr in screens), default=1.0)
    canvas = QPixmap(
        max(1, round(virtual_rect.width() * max_dpr)),
        max(1, round(virtual_rect.height() * max_dpr)),
    )
    canvas.setDevicePixelRatio(max_dpr)
    canvas.fill(Qt.GlobalColor.black)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    try:
        for scr in screens:
            grab = scr.grabWindow(0)
            if grab.isNull():
                logger.warning("Screen grabWindow(0) returned null for %s", scr.geometry().getRect())
                continue
            geo = scr.geometry()
            offset = geo.topLeft() - virtual_rect.topLeft()
            painter.drawPixmap(QRect(offset, geo.size()), grab, grab.rect())
    finally:
        painter.end()

    logger.info(
        "Virtual desktop grabbed: %d screens, virtual_rect=%s, pixmap=%dx%d px, max_dpr=%.2f",
        len(screens),
        virtual_rect.getRect(),
        canvas.width(),
        canvas.height(),
        max_dpr,
    )
    return canvas, virtual_rect


def crop_from_desktop(
    desktop_pixmap: QPixmap,
    virtual_rect: QRect,
    selection_global_rect: QRect,
) -> QPixmap:
    """Crop ``selection_global_rect`` from ``desktop_pixmap`` respecting negative offsets and DPR."""
    if desktop_pixmap.isNull() or virtual_rect.isEmpty():
        return QPixmap()
    sel = selection_global_rect.normalized()
    if sel.width() <= 0 or sel.height() <= 0:
        return QPixmap()

    local_rect = sel.translated(-virtual_rect.topLeft()).intersected(
        QRect(0, 0, virtual_rect.width(), virtual_rect.height())
    )
    if local_rect.width() <= 0 or local_rect.height() <= 0:
        return QPixmap()

    dpr = desktop_pixmap.devicePixelRatio() or 1.0
    expected_w = round(virtual_rect.width() * dpr)
    expected_h = round(virtual_rect.height() * dpr)
    if abs(desktop_pixmap.width() - expected_w) <= 1 and abs(desktop_pixmap.height() - expected_h) <= 1:
        sx = sy = dpr
    else:
        sx = desktop_pixmap.width() / max(1, virtual_rect.width())
        sy = desktop_pixmap.height() / max(1, virtual_rect.height())

    src_rect = QRect(
        round(local_rect.x() * sx),
        round(local_rect.y() * sy),
        round(local_rect.width() * sx),
        round(local_rect.height() * sy),
    ).intersected(desktop_pixmap.rect())
    if src_rect.width() <= 0 or src_rect.height() <= 0:
        return QPixmap()

    cropped = desktop_pixmap.copy(src_rect)
    cropped.setDevicePixelRatio(dpr)
    return cropped
