"""Win32 idle-time and fullscreen/presentation-mode detection for quiet notifications."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

_QUNS_BUSY = 2
_QUNS_RUNNING_D3D_FULL_SCREEN = 3
_QUNS_PRESENTATION_MODE = 4
# Exclude _QUNS_BUSY (2): multi-monitor setups report BUSY whenever any window is maximized.
_SUPPRESSED_QUNS = frozenset({_QUNS_RUNNING_D3D_FULL_SCREEN, _QUNS_PRESENTATION_MODE})


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def get_idle_seconds() -> float:
    """Return seconds since the last keyboard/mouse input via Win32 ``GetLastInputInfo``."""
    if sys.platform != "win32":
        return 0.0
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.GetTickCount64.restype = ctypes.c_uint64
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        now_tick_32 = int(kernel32.GetTickCount64()) & 0xFFFFFFFF
        elapsed_ms = (now_tick_32 - int(lii.dwTime)) & 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except (OSError, AttributeError) as exc:
        logger.debug("Win32 idle check unavailable: %s", exc)
        return 0.0


def is_fullscreen_or_busy() -> bool:
    """Return ``True`` when Windows reports exclusive D3D fullscreen or presentation mode."""
    if sys.platform != "win32":
        return False
    try:
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        state = ctypes.c_int(0)
        hr = int(shell32.SHQueryUserNotificationState(ctypes.byref(state)))
        if hr != 0:
            return False
        return int(state.value) in _SUPPRESSED_QUNS
    except (OSError, AttributeError) as exc:
        logger.debug("Win32 user notification state check unavailable: %s", exc)
        return False


def should_suppress_notification(idle_threshold_sec: float = 120.0) -> bool:
    """Return ``True`` when the user is idle beyond ``idle_threshold_sec`` or in fullscreen/busy mode."""
    return is_fullscreen_or_busy() or get_idle_seconds() >= idle_threshold_sec
