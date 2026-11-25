"""Windows per-user startup registry integration without administrator privileges."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

STARTUP_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_STARTUP_VALUE_NAME = "WorkMemory"


class RegistryBackend(Protocol):
    """Protocol abstracting per-user registry access for isolated unit testing."""

    def get_value(self, subkey: str, name: str) -> str | None:
        """Return the string value under HKCU\\``subkey``\\``name``, or ``None`` if absent."""

    def set_value(self, subkey: str, name: str, value: str) -> None:
        """Write a string value under HKCU\\``subkey``\\``name``."""

    def delete_value(self, subkey: str, name: str) -> None:
        """Delete ``name`` under HKCU\\``subkey`` if present."""


class WinRegBackend:
    """Real Windows ``winreg`` implementation operating strictly on ``HKEY_CURRENT_USER``."""

    def get_value(self, subkey: str, name: str) -> str | None:
        if sys.platform != "win32":
            return None
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
                value, _reg_type = winreg.QueryValueEx(key, name)
                return str(value) if value is not None else None
        except FileNotFoundError:
            return None

    def set_value(self, subkey: str, name: str, value: str) -> None:
        if sys.platform != "win32":
            raise OSError("Windows Registry is only available on Windows.")
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, subkey: str, name: str) -> None:
        if sys.platform != "win32":
            return
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


def build_startup_command(
    executable: Path | None = None,
    is_frozen: bool | None = None,
) -> str:
    """Build the ``--minimized`` startup command for frozen or ``.venv`` launches.

    Uses ``os.path.abspath`` rather than ``Path.resolve()`` so symlinked ``.venv``
    Python binaries stay inside the virtual environment's ``Scripts`` folder.
    """
    raw_exe = executable if executable is not None else Path(sys.executable)
    exe_abs = Path(os.path.abspath(os.fspath(raw_exe)))
    frozen = bool(getattr(sys, "frozen", False)) if is_frozen is None else bool(is_frozen)
    if frozen:
        return f'"{exe_abs}" --minimized'

    pythonw = exe_abs.parent / "pythonw.exe"
    launch_exe = pythonw if pythonw.is_file() else exe_abs
    return f'"{launch_exe}" -m work_memory.main --minimized'


class StartupService:
    """Manages launching Work Memory silently at Windows user login."""

    def __init__(
        self,
        registry: RegistryBackend | None = None,
        *,
        subkey: str = STARTUP_RUN_KEY,
        value_name: str = DEFAULT_STARTUP_VALUE_NAME,
        command_builder: Callable[[], str] | None = None,
    ) -> None:
        self._registry: RegistryBackend = registry or WinRegBackend()
        self._subkey = subkey
        self._value_name = value_name
        self._command_builder = command_builder or build_startup_command

    def is_startup_enabled(self) -> bool:
        """Return ``True`` when the HKCU Run entry for Work Memory is present."""
        try:
            value = self._registry.get_value(self._subkey, self._value_name)
        except OSError as exc:
            logger.warning("Unable to read Windows startup registry entry: %s", exc)
            return False
        return bool(value and value.strip())

    def set_startup_enabled(self, enabled: bool) -> bool:
        """Enable or disable the HKCU Run entry; return ``True`` on success."""
        if enabled:
            cmd = self._command_builder()
            try:
                self._registry.set_value(self._subkey, self._value_name, cmd)
                logger.info("Enabled Windows startup entry: %s", cmd)
                return True
            except OSError as exc:
                logger.warning("Failed to enable Windows startup entry: %s", exc)
                return False

        try:
            self._registry.delete_value(self._subkey, self._value_name)
            logger.info("Disabled Windows startup entry.")
            return True
        except OSError as exc:
            logger.warning("Failed to disable Windows startup entry: %s", exc)
            return False
