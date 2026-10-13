import errno
import json
import logging
import os
import socket as local_socket
import stat
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from web_app_launcher.launcher import AppLauncher
from web_app_launcher.tray.tray_auth import (
    create_session_token,
    read_session_token,
    validate_session_token,
)
from web_app_launcher.tray.tray_manager import TrayManager
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


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
        self.tray_manager = TrayManager(paths.ephemeral_profiles_dir, self)
        self.launcher = AppLauncher(paths, browsers, config, self.tray_manager)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._is_host = False
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
            self._is_host = True
        finally:
            if not self._is_host:
                self.close()

    @property
    def is_host(self) -> bool:
        return self._is_host

    def close(self) -> None:
        """Release our socket before allowing another process to become host."""
        self._server.close()
        self._is_host = False
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
        socket = self._server.nextPendingConnection()
        if not socket:
            return

        socket.readyRead.connect(lambda s=socket: self._handle_client(s))

    def _handle_client(self, socket: QLocalSocket) -> None:
        try:
            payload = json.loads(bytes(socket.readAll()).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid tray service command")
            socket.disconnectFromServer()
            return

        token = payload.get("token", "")
        if not validate_session_token(self._paths.config_dir, token):
            logger.warning("Rejected tray service command: invalid session token")
            socket.disconnectFromServer()
            return

        command = payload.get("cmd")
        app_uuid = payload.get("uuid", "")

        try:
            if command in {"launch", "show", "stop"} and app_uuid:
                if app_uuid not in self._config.load_apps():
                    logger.warning("Rejected tray service command: unknown app %s", app_uuid)
                elif command == "launch":
                    self.launcher.launch_app(app_uuid)
                elif command == "show":
                    self.tray_manager.show_app(app_uuid)
                elif command == "stop":
                    self.tray_manager.stop_app(app_uuid)
            elif command == "ping":
                pass
            else:
                logger.warning("Unknown tray service command: %s", command)
        except Exception as exc:
            logger.error("Tray service command failed: %s", exc)

        socket.write(b"ok")
        socket.flush()
        socket.disconnectFromServer()


def send_tray_command(
    command: str,
    config_dir: Path,
    app_uuid: str = "",
    timeout_ms: int = 2000,
) -> bool:
    token = read_session_token(config_dir)
    if not token:
        return False

    socket = QLocalSocket()
    socket.connectToServer(str(PathManager().tray_socket_file))
    if not socket.waitForConnected(timeout_ms):
        return False

    payload = json.dumps({"cmd": command, "uuid": app_uuid, "token": token}).encode("utf-8")
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.waitForReadyRead(timeout_ms)
    socket.disconnectFromServer()
    return True


def try_remote_launch(app_uuid: str, config_dir: Path) -> bool:
    return send_tray_command("launch", config_dir, app_uuid=app_uuid)


class LaunchRouter:
    """Routes launches to the local tray host or an existing remote daemon."""

    def __init__(self, tray_service: TrayService):
        self._tray_service = tray_service

    def launch_app(self, app_uuid: str) -> int:
        if self._tray_service.is_host:
            return self._tray_service.launcher.launch_app(app_uuid)
        if try_remote_launch(app_uuid, self._tray_service._paths.config_dir):
            return 0
        raise RuntimeError("Tray service is not available")
