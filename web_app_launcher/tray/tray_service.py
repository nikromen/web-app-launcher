import errno
import logging
import os
import socket as local_socket
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QLockFile, QObject, Qt, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from web_app_launcher.launcher import AppLauncher
from web_app_launcher.tray.tray_auth import (
    create_session_token,
    read_session_token,
    validate_session_token,
)
from web_app_launcher.tray.tray_manager import TrayManager
from web_app_launcher.tray.tray_protocol import TrayCommand, TrayRequest, TrayResponse
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.path_manager import PathManager

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 16 * 1024  # Including the terminating newline.
REQUEST_TIMEOUT_MS = 2000


class TrayCommandError(RuntimeError):
    """The remote command failed or its outcome cannot safely be retried."""


@dataclass
class _Connection:
    timer: QTimer
    done: bool = False


def _read_frame(socket: QLocalSocket) -> bytes | None:
    """Leave incomplete lines in Qt's buffer and read at most one bounded frame."""
    if not socket.canReadLine():
        if socket.bytesAvailable() >= MAX_MESSAGE_BYTES:
            raise ValueError("Message exceeds 16 KiB")
        return None

    # Qt reserves one byte of readLine's limit for the terminating NUL.
    frame = bytes(socket.readLine(MAX_MESSAGE_BYTES + 1))
    if len(frame) > MAX_MESSAGE_BYTES or not frame.endswith(b"\n"):
        raise ValueError("Message exceeds 16 KiB")

    return frame[:-1]


class TrayService(QObject):
    """Single tray daemon per user session. Owns TrayManager and AppLauncher."""

    def __init__(
        self,
        paths: PathManager,
        browsers: BrowserManager,
        config: ConfigManager,
        parent=None,
    ):
        super().__init__(parent)
        self._paths = paths
        self._config = config
        self.tray_manager = TrayManager(self)
        self.launcher = AppLauncher(paths, browsers, config, self.tray_manager)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._connections: dict[QLocalSocket, _Connection] = {}
        self._is_server = False
        self._server.newConnection.connect(self._on_connection)
        self._socket_path = paths.tray_socket_file
        self._lock = QLockFile(str(paths.tray_lock_file))
        self._lock.setStaleLockTime(0)

        # QLocalServer closes its socket before emitting destroyed. Release the
        # non-QObject lock afterwards, including when the service is deleted.
        lock = self._lock
        self._server.destroyed.connect(lambda _object=None: lock.unlock())
        if not self._lock.tryLock(0):
            return

        try:
            if not self._prepare_socket():
                return
            if not self._server.listen(str(self._socket_path)):
                logger.error("Could not listen on tray socket: %s", self._server.errorString())
                return

            application = QCoreApplication.instance()
            if application is not None:
                application.aboutToQuit.connect(self.close)

            create_session_token(self._paths.config_dir)
            self._is_server = True
        finally:
            if not self._is_server:
                self.close()

    @property
    def is_server(self) -> bool:
        """Whether this instance holds the lock and serves the tray socket."""
        return self._is_server

    def close(self) -> None:
        """Release our socket before allowing another process to become host."""
        for socket in list(self._connections):
            self._dispose_connection(socket)

        self._server.close()
        self._is_server = False
        self._lock.unlock()

    def _prepare_socket(self) -> bool:
        """Remove only an unchanged, refused socket while holding the host lock."""
        try:
            info = self._socket_path.lstat()
        except FileNotFoundError:
            return True

        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            logger.warning("Refusing to replace unsafe tray socket: %s", self._socket_path)
            return False

        # Qt's ConnectionRefusedError can also mean a timeout. Only the native
        # ECONNREFUSED result is sufficient evidence of an abandoned socket.
        try:
            with local_socket.socket(local_socket.AF_UNIX, local_socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                probe.connect(str(self._socket_path))
        except OSError as exc:
            if exc.errno != errno.ECONNREFUSED:
                logger.warning("Could not verify stale tray socket: %s", exc)
                return False
        else:
            return False

        try:
            current = self._socket_path.lstat()
        except FileNotFoundError:
            return True

        if (
            not stat.S_ISSOCK(current.st_mode)
            or current.st_uid != os.geteuid()
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            return False

        return bool(QLocalServer.removeServer(str(self._socket_path)))

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setReadBufferSize(MAX_MESSAGE_BYTES)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._connections[socket] = _Connection(timer)
            socket.readyRead.connect(lambda s=socket: self._handle_client(s))
            socket.disconnected.connect(lambda s=socket: self._dispose_connection(s))
            timer.timeout.connect(lambda s=socket: self._expire_connection(s))

            timer.start(REQUEST_TIMEOUT_MS)
            self._handle_client(socket)
            if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                self._dispose_connection(socket)

    def _handle_client(self, socket: QLocalSocket) -> None:
        connection = self._connections.get(socket)
        if connection is None or connection.done:
            return

        try:
            frame = _read_frame(socket)
        except ValueError:
            self._respond(socket, TrayResponse(ok=False, error="Request exceeds 16 KiB"))
            return

        if frame is None:
            return

        # Claim the command before parsing or invoking potentially reentrant handlers.
        connection.done = True
        self._respond(socket, self._execute_command(frame))

    def _execute_command(self, frame: bytes) -> TrayResponse:
        try:
            request = TrayRequest.from_frame(frame)
        except ValidationError as exc:
            location = exc.errors(include_input=False)[0]["loc"]
            error = {
                ("cmd",): "Unknown or invalid command",
                ("token",): "Invalid session token",
                ("uuid",): "Invalid application UUID",
            }.get(location, "Request must be an object")
            return TrayResponse(ok=False, error=error)
        except (ValueError, RecursionError):
            return TrayResponse(ok=False, error="Invalid JSON request")

        try:
            if not validate_session_token(self._paths.config_dir, request.token):
                return TrayResponse(ok=False, error="Invalid session token")

            if request.cmd != TrayCommand.PING:
                if request.uuid not in self._config.load_apps():
                    return TrayResponse(ok=False, error="Unknown application")

                if request.cmd == TrayCommand.LAUNCH:
                    self.launcher.launch_app(request.uuid)
                elif request.cmd == TrayCommand.SHOW:
                    self.tray_manager.show_app(request.uuid)
                elif request.cmd == TrayCommand.STOP:
                    self.tray_manager.stop_app(request.uuid)
        except Exception:
            logger.exception("Tray service command failed")
            return TrayResponse(ok=False, error="Command failed")

        return TrayResponse(ok=True)

    def _respond(self, socket: QLocalSocket, response: TrayResponse) -> None:
        connection = self._connections.get(socket)
        if connection is None:
            return

        connection.done = True
        data = response.to_frame()
        if len(data) > MAX_MESSAGE_BYTES or socket.write(data) != len(data):
            self._dispose_connection(socket)
            return

        socket.flush()
        socket.disconnectFromServer()
        # Keep the original timer until disconnect, bounding queued writes too.

    def _expire_connection(self, socket: QLocalSocket) -> None:
        connection = self._connections.get(socket)
        if connection is not None and not connection.done:
            self._respond(socket, TrayResponse(ok=False, error="Request timed out"))

        self._dispose_connection(socket)

    def _dispose_connection(self, socket: QLocalSocket) -> None:
        connection = self._connections.pop(socket, None)
        if connection is None:
            return

        socket.readyRead.disconnect()
        socket.disconnected.disconnect()
        connection.timer.stop()
        connection.timer.timeout.disconnect()
        connection.timer.deleteLater()
        socket.abort()
        socket.deleteLater()


def send_tray_command(
    command: TrayCommand,
    config_dir: Path,
    app_uuid: str = "",
    timeout_ms: int = 2000,
) -> bool:
    """Return False before sending; raise on rejection or an unconfirmed outcome."""
    deadline = QDeadlineTimer(max(0, timeout_ms), Qt.TimerType.PreciseTimer)
    token = read_session_token(config_dir)
    if not token:
        return False

    try:
        request = TrayRequest(cmd=command, uuid=app_uuid, token=token)
    except ValueError as exc:
        raise TrayCommandError("Invalid tray request") from exc

    if deadline.remainingTime() == 0:
        return False

    response = _send_tray_request(request, PathManager().tray_socket_file, deadline)
    if response is None:
        return False

    if not response.ok:
        raise TrayCommandError(f"Tray service rejected the command: {response.error}")

    return True


def _send_tray_request(
    request: TrayRequest,
    socket_path: Path,
    deadline: QDeadlineTimer,
) -> TrayResponse | None:
    """Exchange typed messages; None means no request bytes were queued."""
    payload = request.to_frame()
    if len(payload) > MAX_MESSAGE_BYTES:
        raise TrayCommandError("Tray request exceeds 16 KiB")

    socket = QLocalSocket()
    socket.setReadBufferSize(MAX_MESSAGE_BYTES)
    uncertain = "Tray service did not confirm the command; it may have been executed"
    try:
        if deadline.remainingTime() == 0:
            return None

        socket.connectToServer(str(socket_path))
        if not socket.waitForConnected(deadline.remainingTime()):
            return None

        sent = 0
        while sent < len(payload):
            if deadline.remainingTime() == 0:
                if sent:
                    raise TrayCommandError(uncertain)
                return None

            written = socket.write(payload[sent:])
            if written <= 0:
                if sent:
                    raise TrayCommandError(uncertain)
                return None

            sent += written

        socket.flush()
        while socket.bytesToWrite() > 0:
            remaining = deadline.remainingTime()
            if remaining == 0:
                raise TrayCommandError(uncertain)

            if not socket.waitForBytesWritten(remaining) and socket.bytesToWrite() > 0:
                raise TrayCommandError(uncertain)

        while True:
            try:
                frame = _read_frame(socket)
            except ValueError as exc:
                raise TrayCommandError("Tray response exceeds 16 KiB") from exc

            if frame is not None:
                try:
                    return TrayResponse.from_frame(frame)
                except (ValueError, RecursionError) as exc:
                    raise TrayCommandError("Invalid tray response") from exc

            remaining = deadline.remainingTime()
            if remaining == 0 or socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                raise TrayCommandError(uncertain)

            if not socket.waitForReadyRead(remaining) and socket.bytesAvailable() == 0:
                raise TrayCommandError(uncertain)
    finally:
        socket.abort()


def try_remote_launch(app_uuid: str, config_dir: Path) -> bool:
    return send_tray_command(TrayCommand.LAUNCH, config_dir, app_uuid=app_uuid)


class LaunchRouter:
    """Routes launches to the local tray host or an existing remote daemon."""

    def __init__(self, tray_service: TrayService):
        self._tray_service = tray_service

    def launch_app(self, app_uuid: str) -> int:
        if self._tray_service.is_server:
            return self._tray_service.launcher.launch_app(app_uuid)
        if try_remote_launch(app_uuid, self._tray_service._paths.config_dir):
            return 0
        raise RuntimeError("Tray service is not available")
