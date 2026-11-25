"""Native Windows global hotkey manager (Ctrl+Shift+M) without keylogger hooks."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_WM_HOTKEY = 0x0312
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_NOREPEAT = 0x4000
_VK_M = 0x4D
_DEFAULT_HOTKEY_ID = 0x574D  # 'WM'


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, on_triggered: object) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._on_triggered = on_triggered

    def nativeEventFilter(self, event_type: object, message: object) -> tuple[bool, int]:
        if sys.platform != "win32" or message is None:
            return False, 0
        try:
            raw_type = bytes(event_type)  # type: ignore[arg-type]
        except TypeError:
            return False, 0
        if raw_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))  # type: ignore[arg-type]
            if msg.message == _WM_HOTKEY and msg.wParam == self._hotkey_id:
                self._on_triggered()  # type: ignore[operator]
                return True, 0
        except (ValueError, TypeError, OSError):
            return False, 0
        return False, 0


class GlobalHotkeyManager(QObject):
    """Registers ``Ctrl+Shift+M`` via Win32 ``RegisterHotKey`` for background Quick Capture."""

    quick_capture_triggered = Signal()

    def __init__(self, app: QApplication, *, hotkey_id: int = _DEFAULT_HOTKEY_ID) -> None:
        super().__init__(app)
        self._app = app
        self._hotkey_id = hotkey_id
        self._registered = False
        self._filter = _HotkeyEventFilter(hotkey_id, self.quick_capture_triggered.emit)

    @property
    def is_registered(self) -> bool:
        """Return ``True`` when the Win32 global hotkey is actively registered."""
        return self._registered

    def set_enabled(self, enabled: bool) -> None:
        """Register or unregister the global hotkey based on ``enabled``."""
        if enabled:
            self.register()
        else:
            self.unregister()

    def register(self) -> bool:
        """Register ``Ctrl+Shift+M`` via ``user32.RegisterHotKey``."""
        if self._registered or sys.platform != "win32":
            return self._registered
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            mods = _MOD_CONTROL | _MOD_SHIFT | _MOD_NOREPEAT
            if not user32.RegisterHotKey(None, self._hotkey_id, mods, _VK_M):
                logger.warning("Failed to register global hotkey Ctrl+Shift+M (already in use?).")
                return False
            self._app.installNativeEventFilter(self._filter)
            self._registered = True
            logger.info("Registered global hotkey Ctrl+Shift+M.")
            return True
        except (OSError, AttributeError) as exc:
            logger.warning("Global hotkey registration unavailable: %s", exc)
            return False

    def unregister(self) -> None:
        """Unregister the global hotkey and remove the native event filter."""
        if not self._registered:
            return
        self._app.removeNativeEventFilter(self._filter)
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)  # type: ignore[attr-defined]
            except (OSError, AttributeError) as exc:
                logger.debug("UnregisterHotKey cleanup warning: %s", exc)
        self._registered = False
        logger.info("Unregistered global hotkey Ctrl+Shift+M.")
