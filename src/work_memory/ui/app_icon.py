"""Unified programmatic Work Memory icon and Windows DWM title-bar theme helper."""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from work_memory.config.settings import normalize_theme_mode

logger = logging.getLogger(__name__)
_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def build_brand_pixmap(size: int = 32, *, border: bool = True) -> QPixmap:
    """Render the crisp dark rounded ``W`` brand badge at ``size x size`` pixels."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    margin = max(1, round(size * 0.06))
    radius = max(3.0, size * 0.25)
    painter.setBrush(QColor("#24282e"))
    if border:
        pen_w = max(1.0, round(size * 0.0625, 1))
        painter.setPen(QPen(QColor("#a9b8df"), pen_w))
    else:
        painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(
        margin, margin, size - 2 * margin, size - 2 * margin, radius, radius
    )
    painter.setPen(QColor("#edf0f3"))
    font = QFont("Segoe UI", max(7, round(size * 0.42)), QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "W")
    painter.end()
    return pm


def build_app_icon() -> QIcon:
    """Build a multi-resolution ``QIcon`` shared by tray, taskbar, and all windows."""
    icon = QIcon()
    for sz in _ICON_SIZES:
        icon.addPixmap(build_brand_pixmap(sz))
    return icon


def set_windows_app_id(app_id: str = "WorkMemory.DesktopApp") -> None:
    """Assign an explicit Windows AppUserModelID so the taskbar uses our icon."""
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)  # type: ignore[attr-defined]
    except (OSError, AttributeError) as exc:
        logger.debug("AppUserModelID registration skipped: %s", exc)


def _hex_to_colorref(hex_color: str) -> int:
    clean = hex_color.lstrip("#")
    if len(clean) != 6:
        return 0
    r = int(clean[0:2], 16)
    g = int(clean[2:4], 16)
    b = int(clean[4:6], 16)
    return (b << 16) | (g << 8) | r


def _set_dwm_int(hwnd: int, attr: int, val: int) -> bool:
    try:
        c_val = ctypes.c_int(val)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(attr),
            ctypes.byref(c_val),
            ctypes.sizeof(c_val),
        )
        return int(hr) == 0
    except (OSError, AttributeError):
        return False


def apply_windows_titlebar_theme(widget: QWidget, theme_mode: str = "dark") -> None:
    """Tint a top-level native Windows title bar to match ``theme_mode``."""
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    if not widget.isWindow() or bool(widget.windowFlags() & Qt.WindowType.FramelessWindowHint):
        return
    hwnd = int(widget.winId())
    if not hwnd:
        return
    mode = normalize_theme_mode(theme_mode)
    dark_flag = 1 if mode == "dark" else 0
    if not _set_dwm_int(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, dark_flag):
        _set_dwm_int(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, dark_flag)
    caption_hex = "#17191d" if mode == "dark" else "#e8e4dc"
    text_hex = "#edf0f3" if mode == "dark" else "#23272e"
    _set_dwm_int(hwnd, _DWMWA_CAPTION_COLOR, _hex_to_colorref(caption_hex))
    _set_dwm_int(hwnd, _DWMWA_TEXT_COLOR, _hex_to_colorref(text_hex))


class TitleBarThemeFilter(QObject):
    """Application event filter keeping native Windows title bars and icons consistent."""

    def __init__(self, theme_mode: str = "dark", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._theme_mode = normalize_theme_mode(theme_mode)
        self._icon = build_app_icon()

    def set_theme_mode(self, theme_mode: str) -> None:
        """Update active theme and re-apply native title-bar colors to open windows."""
        self._theme_mode = normalize_theme_mode(theme_mode)
        for widget in QApplication.topLevelWidgets():
            if widget.isWindow() and not bool(
                widget.windowFlags() & Qt.WindowType.FramelessWindowHint
            ):
                if widget.windowIcon().isNull():
                    widget.setWindowIcon(self._icon)
                apply_windows_titlebar_theme(widget, self._theme_mode)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange)
            and isinstance(watched, QWidget)
            and watched.isWindow()
            and not bool(watched.windowFlags() & Qt.WindowType.FramelessWindowHint)
        ):
            if watched.windowIcon().isNull():
                watched.setWindowIcon(self._icon)
            apply_windows_titlebar_theme(watched, self._theme_mode)
        return False
