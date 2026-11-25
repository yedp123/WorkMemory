"""Aspect-ratio-preserved thumbnail attachment cards for Quick Capture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from work_memory.ui.theme import BG, BORDER, MUTED, PANEL_ALT, SOFT


@dataclass(frozen=True, slots=True)
class QueuedScreenshot:
    """Captured screenshot retaining both original and optional annotated PNG bytes."""

    label: str
    original_bytes: bytes
    annotated_bytes: bytes | None = None
    preview_pixmap: QPixmap | None = None


class AttachmentStrip(QWidget):
    """Displays calm aspect-ratio-preserved thumbnail cards with Discard (×) buttons."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("captureAttachmentStrip")
        self._screenshots: list[QueuedScreenshot] = []
        self._external_images: list[Path] = []
        self._shot_counter = 0

        self._rows_layout = QVBoxLayout(self)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self.setVisible(False)

    def add_screenshot(
        self,
        original_bytes: bytes,
        annotated_bytes: bytes | None = None,
        *,
        preview_pixmap: QPixmap | None = None,
    ) -> QueuedScreenshot:
        """Add a confirmed screenshot (with optional annotated version) as a thumbnail card."""
        self._shot_counter += 1
        suffix = " \u00b7 annotated" if annotated_bytes else ""
        pm = preview_pixmap
        if pm is None or pm.isNull():
            pm = QPixmap()
            pm.loadFromData(annotated_bytes or original_bytes, "PNG")
        item = QueuedScreenshot(
            label=f"Screenshot {self._shot_counter}{suffix}",
            original_bytes=original_bytes,
            annotated_bytes=annotated_bytes,
            preview_pixmap=pm if not pm.isNull() else None,
        )
        self._screenshots.append(item)
        self._rebuild_cards()
        self.changed.emit()
        return item

    def add_external_image(self, path: Path) -> None:
        """Queue an existing external image file path as a thumbnail card."""
        self._external_images.append(Path(path))
        self._rebuild_cards()
        self.changed.emit()

    def queued_screenshots(self) -> list[QueuedScreenshot]:
        """Return queued screenshots in insertion order."""
        return list(self._screenshots)

    def external_images(self) -> list[Path]:
        """Return queued external image paths in insertion order."""
        return list(self._external_images)

    def is_empty(self) -> bool:
        """Return ``True`` when no screenshots or external images are queued."""
        return not self._screenshots and not self._external_images

    def count(self) -> int:
        """Return total number of queued attachment cards."""
        return len(self._screenshots) + len(self._external_images)

    def clear(self) -> None:
        """Remove all queued screenshots and external images."""
        self._screenshots.clear()
        self._external_images.clear()
        self._shot_counter = 0
        self._rebuild_cards()
        self.changed.emit()

    def _remove_screenshot(self, index: int) -> None:
        if 0 <= index < len(self._screenshots):
            self._screenshots.pop(index)
            self._rebuild_cards()
            self.changed.emit()

    def _remove_external(self, index: int) -> None:
        if 0 <= index < len(self._external_images):
            self._external_images.pop(index)
            self._rebuild_cards()
            self.changed.emit()

    def _rebuild_cards(self) -> None:
        while self._rows_layout.count():
            if (item := self._rows_layout.takeAt(0)) is not None and (w := item.widget()) is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        cards: list[QFrame] = []
        for idx, shot in enumerate(self._screenshots):
            cards.append(
                self._make_card(
                    shot.label,
                    shot.preview_pixmap,
                    obj_name="screenshotThumbnailCard",
                    tooltip="Original + annotated copy kept separately" if shot.annotated_bytes else "Captured screenshot",
                    on_discard=lambda _c=False, i=idx: self._remove_screenshot(i),
                )
            )
        for idx, img_path in enumerate(self._external_images):
            pm = QPixmap(str(img_path))
            cards.append(
                self._make_card(
                    img_path.name,
                    pm if not pm.isNull() else None,
                    obj_name="imageThumbnailCard",
                    tooltip=str(img_path),
                    on_discard=lambda _c=False, i=idx: self._remove_external(i),
                )
            )

        for start in range(0, len(cards), 3):
            row_wrap = QWidget()
            row = QHBoxLayout(row_wrap)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            for card in cards[start : start + 3]:
                row.addWidget(card)
            row.addStretch(1)
            self._rows_layout.addWidget(row_wrap)

        self.setVisible(bool(cards))

    @staticmethod
    def _make_card(
        label: str,
        pixmap: QPixmap | None,
        *,
        obj_name: str,
        tooltip: str,
        on_discard: object,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName(obj_name)
        card.setFixedWidth(188)
        card.setToolTip(tooltip)
        card.setStyleSheet(
            f"QFrame#{obj_name} {{ background-color: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(8, 8, 8, 7)
        col.setSpacing(6)

        thumb = QLabel()
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setFixedSize(170, 96)
        thumb.setStyleSheet(f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 6px;")
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                166,
                92,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            thumb.setPixmap(scaled)
        else:
            thumb.setText("Image")
            thumb.setStyleSheet(
                f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 6px; color: {MUTED}; font-size: 11px;"
            )
        col.addWidget(thumb)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(4)
        cap = QLabel(label)
        cap.setStyleSheet(f"color: {SOFT}; font-size: 11px; border: none;")
        cap.setMaximumWidth(140)
        discard = QPushButton("\u00d7")
        discard.setObjectName("discardAttachmentButton")
        discard.setToolTip("Discard attachment")
        discard.setCursor(Qt.CursorShape.PointingHandCursor)
        discard.setFixedSize(20, 20)
        discard.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {MUTED}; font-size: 14px; font-weight: 700; }}"
            "QPushButton:hover { color: #e07a7a; }"
        )
        discard.clicked.connect(on_discard)  # type: ignore[arg-type]
        meta.addWidget(cap, 1)
        meta.addWidget(discard)
        col.addLayout(meta)
        return card
