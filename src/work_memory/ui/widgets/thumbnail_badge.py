"""Clickable 38x38 thumbnail badge for timeline media rows with async swap."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QPushButton, QWidget

from work_memory.ui.theme import BORDER


class ThumbnailBadgeButton(QPushButton):
    """Displays an extension badge immediately, swapping to a rounded thumbnail when ready."""

    def __init__(self, ext_text: str, parent: QWidget | None = None) -> None:
        super().__init__(ext_text, parent)
        self.setObjectName("timelineThumbnailBadge")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 38)
        self.setToolTip("Preview file")
        self._has_thumbnail = False
        self.setStyleSheet(
            "QPushButton#timelineThumbnailBadge { background-color: #2a3039; color: #aebbd7; "
            "border: 1px solid #353b45; border-radius: 7px; font-size: 10px; font-weight: 600; padding: 0px; }"
            "QPushButton#timelineThumbnailBadge:hover { border-color: #6b7b99; color: #edf0f3; }"
        )

    @property
    def has_thumbnail(self) -> bool:
        """Return ``True`` once an async raster thumbnail has been applied."""
        return self._has_thumbnail

    def set_thumbnail_image(self, image: QImage | None) -> None:
        """Convert ``image`` to a rounded ``QPixmap`` on the GUI thread and display it."""
        if image is None or image.isNull():
            return
        size = 38
        src = QPixmap.fromImage(image).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        rounded = QPixmap(size, size)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.0, 0.0, float(size), float(size)), 7.0, 7.0)
        painter.setClipPath(clip)
        sx = max(0, (src.width() - size) // 2)
        sy = max(0, (src.height() - size) // 2)
        painter.drawPixmap(0, 0, src, sx, sy, size, size)
        painter.end()

        self._has_thumbnail = True
        self.setText("")
        self.setIcon(QIcon(rounded))
        self.setIconSize(QSize(size, size))
        self.setStyleSheet(
            f"QPushButton#timelineThumbnailBadge {{ background-color: #1b1f25; "
            f"border: 1px solid {BORDER}; border-radius: 7px; padding: 0px; }}"
            "QPushButton#timelineThumbnailBadge:hover { border-color: #7d8fb3; }"
        )
