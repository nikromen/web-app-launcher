import errno
import json
import os
import select
import socket
import stat
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QLockFile, QStandardPaths
from PySide6.QtNetwork import QAbstractSocket, QLocalServer, QLocalSocket

from web_app_launcher.constants import APP_NAME
from web_app_launcher.tray import tray_service
from web_app_launcher.tray.tray_auth import create_session_token, read_session_token
from web_app_launcher.tray.tray_service import TrayService, send_tray_command
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.path_manager import PathManager

WORKER = """
import json
import sys
from PySide6.QtCore import QCoreApplication, QSocketNotifier, QTimer
from web_app_launcher.tray.tray_auth import read_session_token
from web_app_launcher.tray.tray_service import TrayService
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.path_manager import PathManager

app = QCoreApplication([])
app.setApplicationName(sys.argv[1])
app.setOrganizationName("nikromen" if sys.argv[1] == "gui" else "")
print("ready", flush=True)
assert sys.stdin.readline().strip() == "start"
paths = PathManager()
service = TrayService(paths, BrowserManager(), ConfigManager(paths))
print(json.dumps({"host": service.is_host,
                  "token": read_session_token(paths.config_dir),
                  "socket": str(paths.tray_socket_file)}), flush=True)
notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read, app)
notifier.activated.connect(lambda *args: app.quit())
QTimer.singleShot(15000, app.quit)
app.exec()
"""


@pytest.fixture
def tray_paths(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return PathManager()


@pytest.fixture
def qt_app(tray_paths):
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def service_factory(tray_paths, qt_app):
    services = []

    def create():
        service = TrayService(tray_paths, BrowserManager(), ConfigManager(tray_paths))
        services.append(service)
        return service

    yield create
    for service in services:
        # A lifecycle test deliberately destroys its QObject before teardown.
        with suppress(RuntimeError):
            service.close()


@pytest.fixture
def workers(tray_paths):
    processes = []

    def spawn(name="cli"):
        process = subprocess.Popen(
            [sys.executable, "-c", WORKER, name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(process)
        assert _read_line(process) == "ready"
        return process

    yield spawn
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def _read_line(process):
    readable, _, _ = select.select([process.stdout], [], [], 5)
    assert readable, "Tray worker did not respond"
    line = process.stdout.readline().strip()
    assert line, f"Tray worker exited: {process.poll()}"
    return line


def _start(process):
    process.stdin.write("start\n")
    process.stdin.flush()


def _stop(process):
    _, errors = process.communicate(input="stop\n", timeout=5)
    assert process.returncode == 0, errors


def _ping(paths, qt_app, token):
    client = QLocalSocket()
    client.connectToServer(str(paths.tray_socket_file))
    assert client.waitForConnected(1000), client.errorString()
    client.write(json.dumps({"cmd": "ping", "uuid": "", "token": token}).encode("utf-8"))
    client.flush()
    response = bytearray()
    deadline = time.monotonic() + 2
    while not response and time.monotonic() < deadline:
        qt_app.processEvents()
        response.extend(bytes(client.readAll()))
    client.abort()
    assert response == b"ok"


def _assert_unlocked(paths):
    lock = QLockFile(str(paths.tray_lock_file))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    lock.unlock()


def test_second_instance_preserves_live_socket_and_token(tray_paths, qt_app, service_factory):
    host = service_factory()
    assert host.is_host
    token = read_session_token(tray_paths.config_dir)
    socket_inode = tray_paths.tray_socket_file.stat().st_ino
    old_time = time.time() - 86400
    os.utime(tray_paths.tray_lock_file, (old_time, old_time))

    client = service_factory()
    assert not client.is_host
    assert read_session_token(tray_paths.config_dir) == token
    assert tray_paths.tray_socket_file.stat().st_ino == socket_inode
    client.close()
    _ping(tray_paths, qt_app, token)


def test_socket_and_runtime_directory_are_private(tray_paths, service_factory):
    service = service_factory()
    assert service.is_host
    assert stat.S_IMODE(tray_paths.runtime_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(tray_paths.tray_socket_file.stat().st_mode) & 0o077 == 0
    assert service._server.socketOptions() == QLocalServer.SocketOption.UserAccessOption


def test_runtime_paths_are_independent_of_application_metadata(tray_paths, qt_app):
    name = qt_app.applicationName()
    organization = qt_app.organizationName()
    try:
        qt_app.setApplicationName("cli")
        qt_app.setOrganizationName("")
        cli_paths = PathManager()
        cli_socket = cli_paths.tray_socket_file
        cli_lock = cli_paths.tray_lock_file
        qt_app.setApplicationName("gui")
        qt_app.setOrganizationName("nikromen")
        assert PathManager().tray_socket_file == cli_socket
        assert PathManager().tray_lock_file == cli_lock
    finally:
        qt_app.setApplicationName(name)
        qt_app.setOrganizationName(organization)


def test_existing_runtime_directory_permissions_are_restricted(tray_paths):
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    directory = Path(location) / APP_NAME
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    assert stat.S_IMODE(tray_paths.runtime_dir.stat().st_mode) == 0o700


def test_runtime_directory_symlink_is_rejected(tray_paths, tmp_path):
    target = tmp_path / "other"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    runtime = tmp_path / "runtime" / APP_NAME
    runtime.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError, match="Unsafe application runtime directory"):
        _ = tray_paths.runtime_dir
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_missing_runtime_location_does_not_fall_back_to_shared_tmp(tray_paths, monkeypatch):
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda location: "")
    with pytest.raises(RuntimeError, match="No user runtime directory"):
        _ = tray_paths.runtime_dir


def test_close_allows_restart(tray_paths, qt_app, service_factory):
    host = service_factory()
    token = read_session_token(tray_paths.config_dir)
    host.close()
    assert not host.is_host
    assert not tray_paths.tray_socket_file.exists()
    assert not tray_paths.tray_lock_file.exists()
    replacement = service_factory()
    assert replacement.is_host
    assert read_session_token(tray_paths.config_dir) != token
    _ping(tray_paths, qt_app, read_session_token(tray_paths.config_dir))


def test_qobject_destruction_releases_socket_and_lock(tray_paths, service_factory, qt_app):
    host = service_factory()
    assert host.is_host
    host.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not tray_paths.tray_socket_file.exists()
    assert service_factory().is_host


def test_token_creation_failure_releases_socket_and_lock(tray_paths, qt_app, monkeypatch):
    def fail(_config_dir):
        raise OSError("token write failed")

    monkeypatch.setattr(tray_service, "create_session_token", fail)
    with pytest.raises(OSError, match="token write failed"):
        TrayService(tray_paths, BrowserManager(), ConfigManager(tray_paths))
    assert not tray_paths.tray_socket_file.exists()
    _assert_unlocked(tray_paths)


def test_unlocked_live_server_is_not_replaced(tray_paths, service_factory):
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    assert server.listen(str(tray_paths.tray_socket_file))
    try:
        token = create_session_token(tray_paths.config_dir)
        inode = tray_paths.tray_socket_file.stat().st_ino
        assert not service_factory().is_host
        assert read_session_token(tray_paths.config_dir) == token
        assert tray_paths.tray_socket_file.stat().st_ino == inode
        client = QLocalSocket()
        client.connectToServer(str(tray_paths.tray_socket_file))
        assert client.waitForConnected(1000)
        client.abort()
        _assert_unlocked(tray_paths)
    finally:
        server.close()


@pytest.mark.parametrize(
    "error",
    [
        QAbstractSocket.SocketError.SocketAccessError,
        QAbstractSocket.SocketError.SocketResourceError,
        QAbstractSocket.SocketError.UnknownSocketError,
    ],
)
def test_listen_failure_does_not_remove_socket_or_replace_token(
    error,
    tray_paths,
    service_factory,
    monkeypatch,
):
    token = create_session_token(tray_paths.config_dir)
    remove = MagicMock()
    monkeypatch.setattr(QLocalServer, "listen", lambda self, name: False)
    monkeypatch.setattr(QLocalServer, "serverError", lambda self: error)
    monkeypatch.setattr(QLocalServer, "errorString", lambda self: error.name)
    monkeypatch.setattr(QLocalServer, "removeServer", remove)
    assert not service_factory().is_host
    remove.assert_not_called()
    assert read_session_token(tray_paths.config_dir) == token
    _assert_unlocked(tray_paths)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("probe timed out"),
        PermissionError(errno.EACCES, "permission denied"),
        OSError(errno.ETIMEDOUT, "connection timed out"),
        OSError(errno.ECONNRESET, "connection reset"),
    ],
)
def test_inconclusive_probe_does_not_remove_socket(
    error,
    tray_paths,
    service_factory,
    monkeypatch,
):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
        stale.bind(str(tray_paths.tray_socket_file))
    inode = tray_paths.tray_socket_file.stat().st_ino
    token = create_session_token(tray_paths.config_dir)
    probe = MagicMock()
    probe.__enter__.return_value.connect.side_effect = error
    monkeypatch.setattr(tray_service.local_socket, "socket", lambda *args: probe)
    remove = MagicMock()
    monkeypatch.setattr(QLocalServer, "removeServer", remove)
    assert not service_factory().is_host
    remove.assert_not_called()
    assert tray_paths.tray_socket_file.stat().st_ino == inode
    assert read_session_token(tray_paths.config_dir) == token
    _assert_unlocked(tray_paths)


def test_non_socket_file_is_not_removed(tray_paths, service_factory):
    tray_paths.tray_socket_file.write_text("keep me", encoding="utf-8")
    assert not service_factory().is_host
    assert tray_paths.tray_socket_file.read_text(encoding="utf-8") == "keep me"
    assert read_session_token(tray_paths.config_dir) is None
    _assert_unlocked(tray_paths)


def test_socket_replaced_during_probe_is_not_removed(tray_paths, service_factory, monkeypatch):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
        stale.bind(str(tray_paths.tray_socket_file))

    def replace(_path):
        tray_paths.tray_socket_file.unlink()
        tray_paths.tray_socket_file.write_text("replacement", encoding="utf-8")
        raise ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")

    probe = MagicMock()
    probe.__enter__.return_value.connect.side_effect = replace
    monkeypatch.setattr(tray_service.local_socket, "socket", lambda *args: probe)
    assert not service_factory().is_host
    assert tray_paths.tray_socket_file.read_text(encoding="utf-8") == "replacement"


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_process_start_has_one_host(attempt, tray_paths, workers, qt_app):
    first = workers("gui")
    second = workers("cli")
    _start(first)
    _start(second)
    results = [json.loads(_read_line(process)) for process in (first, second)]
    assert sorted(result["host"] for result in results) == [False, True]
    assert {result["socket"] for result in results} == {str(tray_paths.tray_socket_file)}
    winner = next(result for result in results if result["host"])
    assert read_session_token(tray_paths.config_dir) == winner["token"]
    _ping(tray_paths, qt_app, winner["token"])
    assert send_tray_command("ping", tray_paths.config_dir, timeout_ms=1000)


def test_process_shutdown_allows_restart(tray_paths, workers, qt_app, service_factory):
    process = workers()
    _start(process)
    result = json.loads(_read_line(process))
    assert result["host"]
    _stop(process)
    assert not tray_paths.tray_socket_file.exists()
    assert not tray_paths.tray_lock_file.exists()
    assert service_factory().is_host
    _ping(tray_paths, qt_app, read_session_token(tray_paths.config_dir))


def test_crashed_host_recovers_stale_lock_and_socket(tray_paths, workers, qt_app, service_factory):
    process = workers()
    _start(process)
    result = json.loads(_read_line(process))
    assert result["host"]
    process.kill()
    process.wait(timeout=5)
    assert tray_paths.tray_socket_file.exists()
    assert tray_paths.tray_lock_file.exists()
    assert service_factory().is_host
    token = read_session_token(tray_paths.config_dir)
    assert token != result["token"]
    _ping(tray_paths, qt_app, token)
