"""Single-instance guard using Qt local IPC to focus an existing window."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

DEFAULT_SERVER_NAME = "WorkMemory_SingleInstance_v1"
_SHOW_COMMAND = b"SHOW\n"


class SingleInstanceGuard(QObject):
    """Ensures only one Work Memory desktop instance runs per user session."""

    activate_requested = Signal()

    def __init__(
        self,
        server_name: str = DEFAULT_SERVER_NAME,
        parent: QObject | None = None,
        *,
        connect_timeout_ms: int = 250,
    ) -> None:
        super().__init__(parent)
        self._server_name = server_name
        self._connect_timeout_ms = connect_timeout_ms
        self._server: QLocalServer | None = None
        self._is_primary = False
        self._buffers: dict[QLocalSocket, bytearray] = {}

    @property
    def server_name(self) -> str:
        """Return the local IPC server name used by this guard."""
        return self._server_name

    @property
    def is_primary(self) -> bool:
        """Return ``True`` when this process owns the active local IPC server."""
        return self._is_primary

    def acquire(self) -> bool:
        """Claim primary ownership or signal the existing instance and return ``False``."""
        if self._is_primary:
            return True

        if self._notify_existing_instance():
            self._is_primary = False
            return False

        server = QLocalServer(self)
        server.newConnection.connect(self._on_new_connection)
        if not server.listen(self._server_name):
            logger.info(
                "Removing stale single-instance socket '%s' after listen failure (%s).",
                self._server_name,
                server.errorString(),
            )
            QLocalServer.removeServer(self._server_name)
            if not server.listen(self._server_name):
                logger.warning(
                    "Unable to bind single-instance server '%s': %s",
                    self._server_name,
                    server.errorString(),
                )
                server.deleteLater()
                return True

        self._server = server
        self._is_primary = True
        return True

    def close(self) -> None:
        """Release the local IPC server and clean up active client sockets."""
        for sock in list(self._buffers):
            self._buffers.pop(sock, None)
            sock.close()
            sock.deleteLater()

        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        if self._is_primary:
            QLocalServer.removeServer(self._server_name)
            self._is_primary = False

    def _notify_existing_instance(self) -> bool:
        socket = QLocalSocket(self)
        try:
            socket.connectToServer(self._server_name)
            if not socket.waitForConnected(self._connect_timeout_ms):
                return False
            socket.write(_SHOW_COMMAND)
            socket.flush()
            socket.waitForBytesWritten(self._connect_timeout_ms)
            socket.disconnectFromServer()
            return True
        except (OSError, RuntimeError) as exc:
            logger.debug("Single-instance probe error for '%s': %s", self._server_name, exc)
            return False
        finally:
            socket.deleteLater()

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                continue
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_socket_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._cleanup_socket(s))
            if sock.bytesAvailable() > 0:
                self._on_socket_ready_read(sock)

    def _on_socket_ready_read(self, sock: QLocalSocket) -> None:
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf.extend(bytes(sock.readAll()))
        if b"\n" not in buf and buf.strip().upper() != b"SHOW":
            return
        text = bytes(buf).decode("utf-8", errors="ignore")
        buf.clear()
        if any(line.strip().upper() == "SHOW" for line in text.splitlines()):
            self.activate_requested.emit()

    def _cleanup_socket(self, sock: QLocalSocket) -> None:
        buf = self._buffers.pop(sock, None)
        if buf:
            text = bytes(buf).decode("utf-8", errors="ignore")
            if any(line.strip().upper() == "SHOW" for line in text.splitlines()):
                self.activate_requested.emit()
        sock.deleteLater()
