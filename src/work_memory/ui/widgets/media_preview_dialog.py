"""Calm dark click-to-enlarge MediaPreviewDialog for images, 3D models, and video."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from work_memory.media.thumbnail_service import (
    MediaKind,
    MediaPreviewData,
    ThumbnailService,
    get_media_kind,
)
from work_memory.ui.file_actions import open_file_default, reveal_in_folder
from work_memory.ui.theme import get_palette
from work_memory.ui.widgets.video_player_panel import VideoPlayerPanel


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class MediaPreviewDialog(QDialog):
    """Resizable dark dialog for inspecting images, 3D renders, and videos read-only."""

    info_toast = Signal(str, str)

    def __init__(
        self,
        abs_path: Path,
        *,
        thumbnail_service: ThumbnailService | None = None,
        root_bound: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._abs_path = abs_path
        self._root_bound = root_bound
        self._thumb_service = thumbnail_service
        self._kind: MediaKind = get_media_kind(abs_path) or "image"
        self._source_pixmap: QPixmap | None = None

        pal = get_palette()
        self._pal = pal
        self.setWindowTitle(abs_path.name)
        self.resize(760, 580)
        self.setMinimumSize(520, 420)
        self.setStyleSheet(
            f"QDialog {{ background-color: {pal.bg}; color: {pal.text}; }}"
            f"QFrame#previewHeader, QFrame#previewBody {{ background-color: {pal.panel}; "
            f"border: 1px solid {pal.border}; border-radius: 10px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)
        root.addLayout(self._build_footer())

        self._load_media()

    def _build_header(self) -> QFrame:
        pal = self._pal
        card = QFrame()
        card.setObjectName("previewHeader")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)

        kind_labels = {
            "image": ("Image", pal.accent),
            "video": ("Video", pal.purple),
            "model_3d": ("3D Model", pal.green),
        }
        label_txt, color_hex = kind_labels[self._kind]
        badge = QLabel(label_txt)
        badge.setStyleSheet(
            f"background-color: {pal.panel_alt}; color: {color_hex}; border: 1px solid {pal.border}; "
            "border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
        )
        name_lbl = QLabel(self._abs_path.name)
        name_lbl.setObjectName("previewTitleLabel")
        name_lbl.setStyleSheet(f"color: {pal.text}; font-size: 14px; font-weight: 600; border: none;")

        size_txt = _format_bytes(self._abs_path.stat().st_size) if self._abs_path.is_file() else "Missing"
        self._info_lbl = QLabel(size_txt)
        self._info_lbl.setObjectName("previewInfoLabel")
        self._info_lbl.setStyleSheet(f"color: {pal.muted}; font-size: 12px; border: none;")

        row.addWidget(badge, 0)
        row.addWidget(name_lbl, 1)
        row.addWidget(self._info_lbl, 0)
        return card

    def _build_body(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewBody")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 14, 14, 14)

        self._stack = QStackedWidget()
        self._image_lbl = QLabel("Loading preview...")
        self._image_lbl.setObjectName("previewImageLabel")
        self._image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_lbl.setMinimumSize(320, 240)
        self._image_lbl.setStyleSheet(f"color: {self._pal.muted}; font-size: 13px; border: none;")

        self._video_panel = VideoPlayerPanel()
        self._stack.addWidget(self._image_lbl)
        self._stack.addWidget(self._video_panel)
        lay.addWidget(self._stack, 1)
        return frame

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        open_btn = QPushButton("Open in default app")
        open_btn.setObjectName("previewOpenDefaultButton")
        open_btn.setProperty("secondary", True)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(lambda: open_file_default(self._abs_path))

        reveal_btn = QPushButton("Open containing folder")
        reveal_btn.setObjectName("previewRevealFolderButton")
        reveal_btn.setProperty("secondary", True)
        reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reveal_btn.clicked.connect(self._on_reveal_folder)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("previewCloseButton")
        close_btn.setProperty("primary", True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)

        row.addWidget(open_btn)
        row.addWidget(reveal_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        return row

    @property
    def video_panel(self) -> VideoPlayerPanel:
        """Expose embedded ``VideoPlayerPanel`` for handle-release verification."""
        return self._video_panel

    def _load_media(self) -> None:
        if self._kind == "video":
            self._stack.setCurrentIndex(1)
            fallback: QImage | None = None
            if self._thumb_service is not None:
                fallback = self._thumb_service.generate_thumbnail(self._abs_path, size_px=640)
            self._video_panel.load_video(self._abs_path, fallback_image=fallback)
            return

        self._stack.setCurrentIndex(0)
        if self._kind == "model_3d":
            self._image_lbl.setText("Rendering 3D preview...")
        if self._thumb_service is not None:
            self._thumb_service.request_preview(self._abs_path, size_px=640, callback=self._on_preview_ready)
            return
        img = QImage(str(self._abs_path))
        self._apply_image(None if img.isNull() else img, "Image" if not img.isNull() else "Unable to load image")

    def _on_preview_ready(self, data: object) -> None:
        if not isinstance(data, MediaPreviewData):
            return
        size_txt = _format_bytes(data.file_size) if data.file_size > 0 else "Missing"
        self._info_lbl.setText(f"{size_txt} \u00b7 {data.info_label}" if data.info_label else size_txt)
        self._apply_image(data.image, data.info_label or "Preview unavailable")

    def _apply_image(self, image: QImage | None, fallback_text: str) -> None:
        if image is None or image.isNull():
            self._source_pixmap = None
            self._image_lbl.setPixmap(QPixmap())
            self._image_lbl.setText(fallback_text)
            return
        self._source_pixmap = QPixmap.fromImage(image)
        self._rescale_pixmap()

    def _rescale_pixmap(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        target = self._image_lbl.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        self._image_lbl.setPixmap(
            self._source_pixmap.scaled(
                target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )

    def _on_reveal_folder(self) -> None:
        ok, status = reveal_in_folder(self._abs_path, root_bound=self._root_bound)
        if status == "parent_opened":
            self.info_toast.emit("File moved or deleted", "File no longer exists \u2014 opened containing folder")
        elif not ok:
            self.info_toast.emit("Folder unavailable", "Folder not found on disk")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rescale_pixmap()

    def hideEvent(self, event: QHideEvent) -> None:
        self._video_panel.release_media()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._video_panel.release_media()
        super().closeEvent(event)

    def accept(self) -> None:
        self._video_panel.release_media()
        super().accept()

    def reject(self) -> None:
        self._video_panel.release_media()
        super().reject()
