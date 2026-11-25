"""Collapsible style sub-bar with size dot presets and color swatches."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from work_memory.ui.capture.annotation_engine import SizePreset
from work_memory.ui.theme import ACCENT, BORDER, PANEL

SWATCH_HEXES: tuple[tuple[str, str], ...] = (
    ("red", "#ef5350"),
    ("yellow", "#f0c05a"),
    ("green", "#6ec494"),
    ("blue", "#5aa9f0"),
    ("white", "#edf0f3"),
    ("dark", "#17191d"),
)

_SIZE_PRESETS: tuple[tuple[SizePreset, str, int], ...] = (
    ("small", "Small", 5),
    ("medium", "Medium", 8),
    ("large", "Large", 12),
)


def _dot_icon(diameter: int, color: QColor) -> QIcon:
    dpr = 2.0
    pm = QPixmap(round(18 * dpr), round(18 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    r = diameter / 2.0
    painter.drawEllipse(9.0 - r, 9.0 - r, float(diameter), float(diameter))
    painter.end()
    return QIcon(pm)


def _swatch_icon(hex_color: str, *, active: bool) -> QIcon:
    dpr = 2.0
    pm = QPixmap(round(20 * dpr), round(20 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if active:
        painter.setPen(QPen(QColor(ACCENT), 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(2.0, 2.0, 16.0, 16.0)
    painter.setPen(QPen(QColor("#484f5a"), 1.0))
    painter.setBrush(QColor(hex_color))
    painter.drawEllipse(4.2, 4.2, 11.6, 11.6)
    painter.end()
    return QIcon(pm)


class StyleSubBar(QFrame):
    """Compact dark sub-bar for size presets (Small/Medium/Large) and 6 color swatches."""

    size_preset_changed = Signal(str)
    color_changed = Signal(QColor)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("captureStyleSubBar")
        self.setStyleSheet(
            f"QFrame#captureStyleSubBar {{ background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        self._size_buttons: dict[SizePreset, QPushButton] = {}
        self._swatch_buttons: dict[str, QPushButton] = {}
        self._active_size: SizePreset = "medium"
        self._active_color_key = "red"

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(4)

        dot_css = (
            "QPushButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 2px; }"
            "QPushButton:hover { background-color: #272b33; }"
            f"QPushButton:checked {{ background-color: #2a3242; border-color: {ACCENT}; }}"
        )
        for preset, tip, diam in _SIZE_PRESETS:
            btn = QPushButton()
            btn.setObjectName(f"toolbarSize_{preset}")
            btn.setCheckable(True)
            btn.setChecked(preset == self._active_size)
            btn.setToolTip(tip)
            btn.setFixedSize(24, 24)
            btn.setIconSize(QSize(18, 18))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(dot_css)
            btn.setIcon(_dot_icon(diam, QColor("#dfe4ea")))
            btn.clicked.connect(lambda _c=False, p=preset: self._select_size(p))
            self._size_buttons[preset] = btn
            row.addWidget(btn)

        sep = QFrame()
        sep.setFixedSize(1, 16)
        sep.setStyleSheet(f"background-color: {BORDER}; border: none;")
        row.addSpacing(2)
        row.addWidget(sep)
        row.addSpacing(2)

        swatch_css = (
            "QPushButton { background: transparent; border: none; border-radius: 10px; padding: 0px; }"
            "QPushButton:hover { background-color: #272b33; }"
        )
        for key, hex_code in SWATCH_HEXES:
            btn = QPushButton()
            btn.setObjectName(f"toolbarColor_{key}")
            btn.setCheckable(True)
            btn.setChecked(key == self._active_color_key)
            btn.setToolTip(key.capitalize())
            btn.setFixedSize(22, 22)
            btn.setIconSize(QSize(20, 20))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(swatch_css)
            btn.setIcon(_swatch_icon(hex_code, active=(key == self._active_color_key)))
            btn.clicked.connect(lambda _c=False, k=key, h=hex_code: self._select_color(k, h))
            self._swatch_buttons[key] = btn
            row.addWidget(btn)

    def _select_size(self, preset: SizePreset) -> None:
        self._active_size = preset
        for key, btn in self._size_buttons.items():
            btn.setChecked(key == preset)
        self.size_preset_changed.emit(preset)

    def _select_color(self, key: str, hex_code: str) -> None:
        self._active_color_key = key
        for k, h in SWATCH_HEXES:
            btn = self._swatch_buttons[k]
            active = k == key
            btn.setChecked(active)
            btn.setIcon(_swatch_icon(h, active=active))
        self.color_changed.emit(QColor(hex_code))
