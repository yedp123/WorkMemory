"""Shared QThreadPool task runner for keeping SQLite and disk scans off the GUI thread."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _PoolRunnable(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _WorkerSignals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            logger.exception("Background UI task failed.")
            self._signals.failed.emit(str(exc))
        else:
            self._signals.finished.emit(result)


def run_in_pool(
    owner: QObject,
    active_set: set[QObject],
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Execute ``fn`` on ``QThreadPool`` and deliver results via Qt signals to ``owner``."""
    signals = _WorkerSignals(owner)
    active_set.add(signals)

    def _done(value: Any) -> None:
        active_set.discard(signals)
        on_done(value)

    def _err(msg: str) -> None:
        active_set.discard(signals)
        if on_error is not None:
            on_error(msg)

    signals.finished.connect(_done)
    signals.failed.connect(_err)
    QThreadPool.globalInstance().start(_PoolRunnable(fn, signals))
