"""Geometric cover banner and calm status/date formatting helpers for project cards."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

_COVER_PALETTES: dict[str, tuple[tuple[float, float], str, str, str, str]] = {
    "c1": ((0.50, 0.35), "#52647b", "#29313d", "#20242c", "#d4dff1"),
    "c2": ((0.65, 0.30), "#76647d", "#38313f", "#24232b", "#e0cfe8"),
    "c3": ((0.45, 0.35), "#677f79", "#303d3d", "#202a2c", "#d0e4dc"),
    "c4": ((0.55, 0.35), "#81745d", "#3e3931", "#24231f", "#ead9b9"),
    "c5": ((0.50, 0.35), "#63708d", "#303746", "#20242d", "#d4dcf2"),
    "c6": ((0.50, 0.35), "#806b60", "#40332f", "#252120", "#e9cfc4"),
}
STATUS_ONGOING_COLOR = "#e09b52"
STATUS_COMPLETED_COLOR = "#6ec494"


def status_display(status: str) -> tuple[str, str]:
    """Return human label and accent hex color for ``ongoing`` / ``completed``."""
    if status == "completed":
        return "Completed", STATUS_COMPLETED_COLOR
    return "Ongoing", STATUS_ONGOING_COLOR


def format_activity_date(iso_utc: str | None) -> str:
    """Format an ISO-8601 UTC timestamp as a calm human-readable local date label."""
    if not iso_utc:
        return "No activity yet"
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
    except ValueError:
        return iso_utc[:10]
    today = datetime.now().astimezone().date()
    delta = (today - dt.date()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return (
        f"{dt.strftime('%b')} {dt.day}"
        if dt.year == today.year
        else f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    )


class CoverBanner(QWidget):
    """Paints aspect-preserved dark gradient, geometric motif, or centered-crop preview."""

    def __init__(
        self,
        cover_style: str = "c1",
        *,
        corner_label: str = "PROJECT",
        radius: int = 12,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._style = cover_style if cover_style in _COVER_PALETTES else "c1"
        self._corner_label, self._radius, self._hovered = corner_label, radius, False
        self._pixmap: QPixmap | None = None

    def set_cover(self, cover_style: str, corner_label: str | None = None) -> None:
        """Update the cover palette and optional corner caption."""
        self._style = cover_style if cover_style in _COVER_PALETTES else "c1"
        if corner_label is not None:
            self._corner_label = corner_label
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        """Set or clear an optional raster preview rendered with centered aspect-fill crop."""
        self._pixmap = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self.update()

    def set_hovered(self, hovered: bool) -> None:
        """Highlight the hairline border subtly on parent card hover."""
        if self._hovered != hovered:
            self._hovered = hovered
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render the rounded cover artwork without distortion."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(clip)

        if self._pixmap is not None and not self._pixmap.isNull():
            self._paint_pixmap_cover(painter, rect, self._pixmap)
        else:
            self._paint_gradient_cover(painter, rect)

        if self._corner_label and self._pixmap is None:
            painter.setPen(QColor(255, 255, 255, 184))
            font = QFont("Segoe UI", 8)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(14, 0, -14, -12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                self._corner_label.upper(),
            )

        painter.setClipping(False)
        painter.setPen(QPen(QColor("#596274" if self._hovered else "#343941"), 1.0))
        painter.drawRoundedRect(rect, self._radius, self._radius)

    def _paint_pixmap_cover(self, painter: QPainter, rect: QRectF, pm: QPixmap) -> None:
        dpr = max(1.0, self.devicePixelRatioF())
        phys_w = max(1, round(rect.width() * dpr))
        phys_h = max(1, round(rect.height() * dpr))
        scaled = pm.scaled(
            phys_w,
            phys_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(1.0)
        sx = max(0.0, (scaled.width() - phys_w) / 2.0)
        sy = max(0.0, (scaled.height() - phys_h) / 2.0)
        painter.drawPixmap(rect, scaled, QRectF(sx, sy, float(phys_w), float(phys_h)))

    def _paint_gradient_cover(self, painter: QPainter, rect: QRectF) -> None:
        center_frac, c_in, c_mid, c_out, stroke_hex = _COVER_PALETTES[self._style]
        radial = QRadialGradient(
            QPointF(rect.width() * center_frac[0], rect.height() * center_frac[1]),
            max(rect.width(), rect.height()) * 0.72,
        )
        radial.setColorAt(0.0, QColor(c_in))
        radial.setColorAt(0.65, QColor(c_mid))
        radial.setColorAt(1.0, QColor(c_out))
        painter.fillRect(rect, radial)

        sheen = QLinearGradient(0, 0, rect.width(), rect.height())
        sheen.setColorAt(0.4, QColor(0, 0, 0, 0))
        sheen.setColorAt(1.0, QColor(0, 0, 0, 51))
        painter.fillRect(rect, sheen)
        self._draw_motif(painter, rect, QColor(stroke_hex))

    def _draw_motif(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        painter.save()
        scale = min(rect.width() / 300.0, rect.height() / 180.0)
        offset_x = rect.left() + (rect.width() - 300.0 * scale) / 2.0
        offset_y = rect.top() + (rect.height() - 180.0 * scale) / 2.0
        painter.translate(offset_x, offset_y)
        painter.scale(scale, scale)
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 195), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._style == "c1":
            painter.drawPolyline([QPointF(78, 145), QPointF(112, 40), QPointF(138, 83), QPointF(163, 21), QPointF(208, 145)])
            painter.drawEllipse(QPointF(164, 43), 18, 18)
            for p1, p2 in (((164, 62), (164, 118)), ((164, 83), (130, 109)), ((164, 83), (202, 104))):
                painter.drawLine(QPointF(*p1), QPointF(*p2))
        elif self._style == "c2":
            painter.drawRoundedRect(QRectF(82, 35, 136, 104), 8, 8)
            tri = QPainterPath()
            tri.moveTo(137, 66)
            tri.lineTo(180, 87)
            tri.lineTo(137, 109)
            tri.closeSubpath()
            painter.fillPath(tri, QColor(color.red(), color.green(), color.blue(), 180))
        elif self._style == "c3":
            painter.drawPolyline([QPointF(150, 32), QPointF(215, 69), QPointF(215, 142), QPointF(150, 179), QPointF(85, 142), QPointF(85, 69), QPointF(150, 32)])
            for p1, p2 in (((85, 69), (150, 107)), ((215, 69), (150, 107)), ((150, 107), (150, 179))):
                painter.drawLine(QPointF(*p1), QPointF(*p2))
        elif self._style == "c4":
            painter.drawPolyline([QPointF(65, 130), QPointF(116, 43), QPointF(160, 130), QPointF(198, 65), QPointF(237, 130), QPointF(65, 130)])
            painter.drawLine(QPointF(116, 43), QPointF(116, 130))
            painter.drawLine(QPointF(92, 86), QPointF(204, 86))
        elif self._style == "c5":
            painter.drawRoundedRect(QRectF(91, 35, 118, 110), 5, 5)
            for y, right in ((61, 189), (78, 189), (95, 166), (112, 181)):
                painter.drawLine(QPointF(111, y), QPointF(right, y))
        else:
            painter.drawEllipse(QPointF(150, 75), 34, 34)
            arc = QPainterPath()
            arc.moveTo(93, 153)
            arc.quadTo(150, 82, 207, 153)
            painter.drawPath(arc)
        painter.restore()


def build_pin_button(is_pinned: bool) -> QPushButton:
    """Create the pin toggle button used on project cards."""
    btn = QPushButton("\U0001f4cc")
    btn.setObjectName("projectPinButton")
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedSize(26, 24)
    btn.setToolTip("Unpin project" if is_pinned else "Pin project to top")
    if is_pinned:
        btn.setStyleSheet(
            "QPushButton#projectPinButton { background-color: rgba(23, 25, 29, 0.85); "
            "border: 1px solid #d8b57c; border-radius: 9px; color: #d8b57c; font-size: 11px; padding: 0; }"
            "QPushButton#projectPinButton:hover { background-color: rgba(36, 40, 46, 0.95); }"
        )
    else:
        btn.setStyleSheet(
            "QPushButton#projectPinButton { background-color: rgba(23, 25, 29, 0.60); "
            "border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 9px; color: #929aa5; font-size: 11px; padding: 0; }"
            "QPushButton#projectPinButton:hover { border-color: rgba(255, 255, 255, 0.28); color: #edf0f3; }"
        )
    return btn


def build_status_badge(status: str) -> tuple[QFrame, QLabel]:
    """Create the compact status pill badge for project cards."""
    status_text, color = status_display(status)
    badge = QFrame()
    badge.setObjectName("statusPillBadge")
    badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    badge.setStyleSheet(
        "QFrame#statusPillBadge { background-color: rgba(23, 25, 29, 0.78); "
        "border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 10px; }"
    )
    row = QHBoxLayout(badge)
    row.setContentsMargins(8, 3, 8, 3)
    row.setSpacing(5)
    dot = QLabel()
    dot.setFixedSize(6, 6)
    dot.setStyleSheet(f"background-color: {color}; border-radius: 3px; border: none;")
    text_lbl = QLabel(status_text)
    text_lbl.setStyleSheet(
        f"color: {color}; font-size: 11px; font-weight: 600; background: transparent; border: none;"
    )
    row.addWidget(dot)
    row.addWidget(text_lbl)
    return badge, text_lbl


CoverBannerWidget = CoverBanner
