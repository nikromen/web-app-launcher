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
from web_app_launcher.tray.tray_protocol import TrayCommand
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
print(json.dumps({"host": service.is_server,
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
    client.write(json.dumps({"cmd": "ping", "uuid": "", "token": token}).encode("utf-8") + b"\n")
    client.flush()
    response = bytearray()
    deadline = time.monotonic() + 2
    while b"\n" not in response and time.monotonic() < deadline:
        qt_app.processEvents()
        response.extend(bytes(client.readAll()))
    client.abort()
    assert response.endswith(b"\n")
    assert json.loads(response) == {"ok": True}


def _assert_unlocked(paths):
    lock = QLockFile(str(paths.tray_lock_file))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    lock.unlock()


def test_second_instance_preserves_live_socket_and_token(tray_paths, qt_app, service_factory):
    host = service_factory()
    assert host.is_server
    token = read_session_token(tray_paths.config_dir)
    socket_inode = tray_paths.tray_socket_file.stat().st_ino
    old_time = time.time() - 86400
    os.utime(tray_paths.tray_lock_file, (old_time, old_time))

    client = service_factory()
    assert not client.is_server
    assert read_session_token(tray_paths.config_dir) == token
    assert tray_paths.tray_socket_file.stat().st_ino == socket_inode
    client.close()
    _ping(tray_paths, qt_app, token)


def test_socket_and_runtime_directory_are_private(tray_paths, service_factory):
    service = service_factory()
    assert service.is_server
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
    assert not host.is_server
    assert not tray_paths.tray_socket_file.exists()
    assert not tray_paths.tray_lock_file.exists()
    replacement = service_factory()
    assert replacement.is_server
    assert read_session_token(tray_paths.config_dir) != token
    _ping(tray_paths, qt_app, read_session_token(tray_paths.config_dir))


def test_qobject_destruction_releases_socket_and_lock(tray_paths, service_factory, qt_app):
    host = service_factory()
    assert host.is_server
    host.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not tray_paths.tray_socket_file.exists()
    assert service_factory().is_server


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
        assert not service_factory().is_server
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
    assert not service_factory().is_server
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
    assert not service_factory().is_server
    remove.assert_not_called()
    assert tray_paths.tray_socket_file.stat().st_ino == inode
    assert read_session_token(tray_paths.config_dir) == token
    _assert_unlocked(tray_paths)


def test_non_socket_file_is_not_removed(tray_paths, service_factory):
    tray_paths.tray_socket_file.write_text("keep me", encoding="utf-8")
    assert not service_factory().is_server
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
    assert not service_factory().is_server
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
    assert send_tray_command(TrayCommand.PING, tray_paths.config_dir, timeout_ms=1000)


def test_process_shutdown_allows_restart(tray_paths, workers, qt_app, service_factory):
    process = workers()
    _start(process)
    result = json.loads(_read_line(process))
    assert result["host"]
    _stop(process)
    assert not tray_paths.tray_socket_file.exists()
    assert not tray_paths.tray_lock_file.exists()
    assert service_factory().is_server
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
    assert service_factory().is_server
    token = read_session_token(tray_paths.config_dir)
    assert token != result["token"]
    _ping(tray_paths, qt_app, token)


# IPC tests use the same isolated runtime/configuration as the host regressions.
@pytest.fixture
def ipc_host(service_factory, monkeypatch):
    host = service_factory()
    monkeypatch.setattr(host._config, "load_apps", MagicMock(return_value={"known": object()}))
    monkeypatch.setattr(host.launcher, "launch_app", MagicMock(return_value=123))
    monkeypatch.setattr(host.tray_manager, "show_app", MagicMock())
    monkeypatch.setattr(host.tray_manager, "stop_app", MagicMock())
    return host


@pytest.fixture
def ipc_client(tray_paths):
    clients = []

    def connect():
        client = QLocalSocket()
        client.connectToServer(str(tray_paths.tray_socket_file))
        assert client.waitForConnected(1000)
        clients.append(client)
        return client

    yield connect
    for client in clients:
        client.abort()


def _wait(qt_app, predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.001)
    assert predicate(), "Timed out waiting for IPC state"


def _request(paths, **fields):
    payload = {"cmd": "launch", "uuid": "known", "token": read_session_token(paths.config_dir)}
    payload.update(fields)
    return json.dumps(payload).encode("utf-8") + b"\n"


def _response(client, qt_app):
    buffer = bytearray()

    def complete():
        if client.bytesAvailable():
            buffer.extend(bytes(client.read(tray_service.MAX_MESSAGE_BYTES)))
        return b"\n" in buffer

    _wait(qt_app, complete)
    assert buffer.endswith(b"\n")
    return json.loads(buffer)


def test_fragmented_request_waits_for_newline_and_confirms_launch(
    ipc_host, ipc_client, tray_paths, qt_app
):
    client = ipc_client()
    request = _request(tray_paths)
    for fragment in (request[:20], request[20:-1]):
        client.write(fragment)
        client.flush()
        qt_app.processEvents()
        ipc_host.launcher.launch_app.assert_not_called()
        assert not client.bytesAvailable()
    client.write(request[-1:])
    client.flush()
    assert _response(client, qt_app) == {"ok": True}
    ipc_host.launcher.launch_app.assert_called_once_with("known")
    _wait(qt_app, lambda: not ipc_host._connections)


@pytest.mark.parametrize("oversized", [False, True])
def test_request_already_buffered_when_connection_is_adopted(
    oversized, ipc_host, ipc_client, tray_paths, qt_app
):
    ipc_host._server.newConnection.disconnect(ipc_host._on_connection)
    client = ipc_client()
    request = _request(tray_paths)
    if oversized:
        request = request[:-1] + b" " * tray_service.MAX_MESSAGE_BYTES + b"\n"
    client.write(request)
    client.flush()
    _wait(qt_app, ipc_host._server.hasPendingConnections)
    pending = ipc_host._server.findChildren(QLocalSocket)[0]
    _wait(qt_app, lambda: pending.bytesAvailable() == len(request))
    assert not ipc_host._connections
    ipc_host._on_connection()
    if oversized:
        assert _response(client, qt_app) == {"ok": False, "error": "Request exceeds 16 KiB"}
        ipc_host.launcher.launch_app.assert_not_called()
    else:
        assert _response(client, qt_app) == {"ok": True}
        ipc_host.launcher.launch_app.assert_called_once_with("known")


@pytest.mark.parametrize(
    "frame",
    [
        b"{\n",
        b"\xff\n",
        b"null\n",
        b"[]\n",
        b'"text"\n',
        b"42\n",
        b"[" * 1200 + b"]" * 1200 + b"\n",
    ],
)
def test_invalid_json_or_nonobject_is_rejected(frame, ipc_host, ipc_client, qt_app):
    client = ipc_client()
    client.write(frame)
    client.flush()
    response = _response(client, qt_app)
    assert response["ok"] is False
    assert isinstance(response["error"], str)
    ipc_host.launcher.launch_app.assert_not_called()
    _wait(qt_app, lambda: not ipc_host._connections)


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"cmd": []}, "Unknown or invalid command"),
        ({"cmd": None}, "Unknown or invalid command"),
        ({"cmd": 42}, "Unknown or invalid command"),
        ({"cmd": "unknown"}, "Unknown or invalid command"),
        ({"token": None}, "Invalid session token"),
        ({"token": 42}, "Invalid session token"),
        ({"token": []}, "Invalid session token"),
        ({"token": {}}, "Invalid session token"),
        ({"token": "é" * 64}, "Invalid session token"),
        ({"token": "g" * 64}, "Invalid session token"),
        ({"token": "f" * 64}, "Invalid session token"),
        ({"token": "0" * 63}, "Invalid session token"),
        ({"token": "0" * 64 + "\n"}, "Invalid session token"),
        ({"uuid": None}, "Invalid application UUID"),
        ({"uuid": []}, "Invalid application UUID"),
        ({"uuid": 42}, "Invalid application UUID"),
        ({"uuid": ""}, "Invalid application UUID"),
        ({"uuid": " "}, "Invalid application UUID"),
        ({"uuid": "missing"}, "Unknown application"),
    ],
)
def test_invalid_fields_do_not_run_actions(fields, error, ipc_host, ipc_client, tray_paths, qt_app):
    client = ipc_client()
    client.write(_request(tray_paths, **fields))
    client.flush()
    assert _response(client, qt_app) == {"ok": False, "error": error}
    ipc_host.launcher.launch_app.assert_not_called()
    ipc_host.tray_manager.show_app.assert_not_called()
    ipc_host.tray_manager.stop_app.assert_not_called()


@pytest.mark.parametrize(
    "field, error",
    [
        ("cmd", "Unknown or invalid command"),
        ("token", "Invalid session token"),
        ("uuid", "Invalid application UUID"),
    ],
)
def test_missing_request_field_is_rejected(field, error, ipc_host, ipc_client, tray_paths, qt_app):
    payload = json.loads(_request(tray_paths))
    del payload[field]
    client = ipc_client()
    client.write(json.dumps(payload).encode("utf-8") + b"\n")
    client.flush()
    assert _response(client, qt_app) == {"ok": False, "error": error}
    ipc_host.launcher.launch_app.assert_not_called()


def test_ping_does_not_require_uuid(ipc_host, ipc_client, tray_paths, qt_app):
    payload = json.loads(_request(tray_paths, cmd="ping"))
    del payload["uuid"]
    client = ipc_client()
    client.write(json.dumps(payload).encode("utf-8") + b"\n")
    client.flush()
    assert _response(client, qt_app) == {"ok": True}
    ipc_host.launcher.launch_app.assert_not_called()


@pytest.mark.parametrize("command", ["launch", "show", "stop", "ping"])
def test_success_is_confirmed_for_existing_handlers(
    command, ipc_host, ipc_client, tray_paths, qt_app
):
    client = ipc_client()
    client.write(_request(tray_paths, cmd=command))
    client.flush()
    assert _response(client, qt_app) == {"ok": True}
    if command != "ping":
        handler = {
            "launch": ipc_host.launcher.launch_app,
            "show": ipc_host.tray_manager.show_app,
            "stop": ipc_host.tray_manager.stop_app,
        }[command]
        handler.assert_called_once_with("known")
    else:
        ipc_host.launcher.launch_app.assert_not_called()


@pytest.mark.parametrize("command", ["launch", "stop"])
def test_command_exception_returns_failure_without_details(
    command, ipc_host, ipc_client, tray_paths, qt_app
):
    token = read_session_token(tray_paths.config_dir)
    handler = (
        ipc_host.launcher.launch_app if command == "launch" else ipc_host.tray_manager.stop_app
    )
    handler.side_effect = RuntimeError(f"private exception {token}")
    client = ipc_client()
    client.write(_request(tray_paths, cmd=command))
    client.flush()
    response = _response(client, qt_app)
    assert response == {"ok": False, "error": "Command failed"}
    assert token not in json.dumps(response)
    handler.assert_called_once()


def test_one_connection_executes_only_one_command(ipc_host, ipc_client, tray_paths, qt_app):
    client = ipc_client()
    client.write(_request(tray_paths) * 2)
    client.flush()
    assert _response(client, qt_app) == {"ok": True}
    ipc_host.launcher.launch_app.assert_called_once_with("known")
    _wait(qt_app, lambda: not ipc_host._connections)


@pytest.mark.parametrize("extra", [0, 1])
def test_request_size_boundary(extra, ipc_host, ipc_client, tray_paths, qt_app):
    request = _request(tray_paths, cmd="ping")
    request = request[:-1] + b" " * (tray_service.MAX_MESSAGE_BYTES - len(request) + extra) + b"\n"
    client = ipc_client()
    client.write(request)
    client.flush()
    expected = {"ok": False, "error": "Request exceeds 16 KiB"} if extra else {"ok": True}
    assert _response(client, qt_app) == expected
    _wait(qt_app, lambda: not ipc_host._connections)


def test_incomplete_request_timeout_is_fixed_and_cleans_objects(
    ipc_host, ipc_client, qt_app, monkeypatch
):
    import shiboken6

    monkeypatch.setattr(tray_service, "REQUEST_TIMEOUT_MS", 180)
    client = ipc_client()
    _wait(qt_app, lambda: bool(ipc_host._connections))
    server_socket, state = next(iter(ipc_host._connections.items()))
    timer = state.timer
    assert server_socket.readBufferSize() == tray_service.MAX_MESSAGE_BYTES
    start = time.monotonic()
    while ipc_host._connections and time.monotonic() - start < 0.6:
        if client.state() == QLocalSocket.LocalSocketState.ConnectedState:
            client.write(b" ")
            client.flush()
        qt_app.processEvents()
        time.sleep(0.02)
    assert time.monotonic() - start < 0.4
    assert not ipc_host._connections
    ipc_host.launcher.launch_app.assert_not_called()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(server_socket)
    assert not shiboken6.isValid(timer)


@pytest.mark.parametrize("shutdown", ["disconnect", "close"])
def test_unfinished_connection_cleanup(shutdown, ipc_host, ipc_client, qt_app):
    client = ipc_client()
    client.write(b"{")
    client.flush()
    _wait(qt_app, lambda: bool(ipc_host._connections))
    if shutdown == "disconnect":
        client.abort()
    else:
        ipc_host.close()
    _wait(qt_app, lambda: not ipc_host._connections)
    ipc_host.launcher.launch_app.assert_not_called()


REPLY_WORKER = """
import json
import socket
import sys
import time

path, fragments, delay, hold = sys.argv[1:]
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
    listener.bind(path)
    listener.listen(1)
    listener.settimeout(2)
    print("ready", flush=True)
    with listener.accept()[0] as peer:
        peer.settimeout(2)
        request = bytearray()
        while b"\\n" not in request:
            data = peer.recv(16384 - len(request))
            assert data, "Client disconnected before sending its command"
            request.extend(data)
        print(json.dumps(json.loads(request)), flush=True)
        try:
            for fragment in json.loads(fragments):
                peer.sendall(bytes.fromhex(fragment))
                time.sleep(float(delay))
            time.sleep(float(hold))
        except (BrokenPipeError, ConnectionResetError):
            pass
"""


@pytest.fixture
def reply_server(tray_paths):
    """A real peer in another process, independent of blocking Qt calls and the GIL."""
    peers = []

    def start(fragments, delay=0, hold=0):
        create_session_token(tray_paths.config_dir)
        peer = subprocess.Popen(
            [
                sys.executable,
                "-c",
                REPLY_WORKER,
                str(tray_paths.tray_socket_file),
                json.dumps([fragment.hex() for fragment in fragments]),
                str(delay),
                str(hold),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        peers.append(peer)
        assert _read_line(peer) == "ready"
        return peer

    yield start
    for peer in peers:
        try:
            _, errors = peer.communicate(timeout=3)
            assert peer.returncode == 0, errors
        finally:
            if peer.poll() is None:
                peer.kill()
                peer.communicate(timeout=3)


def test_client_waits_for_fragmented_confirmation(reply_server, tray_paths, qt_app):
    peer = reply_server([b'{"ok"', b": true}", b"\n"], delay=0.03)
    assert send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known", timeout_ms=500)
    assert json.loads(_read_line(peer))["cmd"] == "launch"


@pytest.mark.parametrize(
    "response",
    [
        b"ok\n",
        b"\xff\n",
        b"null\n",
        b"[]\n",
        b"{}\n",
        b'{"ok": 1}\n',
        b'{"ok": 0, "error": "failed"}\n',
        b'{"ok": "true"}\n',
        b'{"ok": "false", "error": "failed"}\n',
        b'{"ok": true, "error": "contradiction"}\n',
        b'{"ok": true, "error": null}\n',
        b'{"ok": false}\n',
        b'{"ok": false, "error": null}\n',
        b'{"ok": false, "error": 42}\n',
        b'{"ok": false, "error": ""}\n',
        b'{"ok": true, "extra": 42}\n',
        b"[" * 1200 + b"]" * 1200 + b"\n",
    ],
)
def test_client_rejects_invalid_confirmation(response, reply_server, tray_paths, qt_app):
    reply_server([response])
    with pytest.raises(tray_service.TrayCommandError, match="Invalid tray response"):
        send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known", timeout_ms=500)


def test_client_reports_server_rejection(reply_server, tray_paths, qt_app):
    reply_server([b'{"ok": false, "error": "Unknown application"}\n'])
    with pytest.raises(tray_service.TrayCommandError, match="Unknown application"):
        send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "missing", timeout_ms=500)


@pytest.mark.parametrize("extra", [0, 1])
def test_client_response_size_boundary(extra, reply_server, tray_paths, qt_app):
    response = b'{"ok": true}'
    response += b" " * (tray_service.MAX_MESSAGE_BYTES - len(response) - 1 + extra) + b"\n"
    reply_server([response])
    if extra:
        with pytest.raises(tray_service.TrayCommandError, match="exceeds 16 KiB"):
            send_tray_command(TrayCommand.PING, tray_paths.config_dir, timeout_ms=500)
    else:
        assert send_tray_command(TrayCommand.PING, tray_paths.config_dir, timeout_ms=500)


@pytest.mark.parametrize("mode", ["timeout", "disconnect", "partial"])
def test_sent_command_without_confirmation_is_uncertain(mode, reply_server, tray_paths, qt_app):
    peer = reply_server(
        [b'{"ok": true}'] if mode == "partial" else [],
        hold=0 if mode == "disconnect" else 0.25,
    )
    start = time.monotonic()
    with pytest.raises(tray_service.TrayCommandError, match="may have been executed"):
        send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known", timeout_ms=100)
    assert time.monotonic() - start < 0.2
    assert json.loads(_read_line(peer))["cmd"] == "launch"


def test_unavailable_service_allows_local_fallback(tray_paths, qt_app):
    assert send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known") is False
    create_session_token(tray_paths.config_dir)
    assert (
        send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known", timeout_ms=100)
        is False
    )


@pytest.mark.parametrize("second_attempt", [False, True])
def test_cli_does_not_retry_uncertain_launch(second_attempt, tray_paths, qt_app, monkeypatch):
    import click

    from web_app_launcher import main

    error = tray_service.TrayCommandError("The command may have been executed")
    remote = MagicMock(side_effect=[False, error] if second_attempt else error)
    factory = MagicMock()
    factory.return_value.is_server = False
    monkeypatch.setattr(main, "try_remote_launch", remote)
    monkeypatch.setattr(main, "TrayService", factory)
    monkeypatch.setattr(main, "_ensure_qt_app", lambda: qt_app)
    context = click.Context(main.run_app, obj=main.Context(tray_paths, None, None))
    with context, pytest.raises(click.ClickException, match="may have been executed"):
        main.run_app.callback("known")
    assert remote.call_count == (2 if second_attempt else 1)
    assert factory.call_count == (1 if second_attempt else 0)
    factory.return_value.launcher.launch_app.assert_not_called()


def test_router_propagates_uncertain_launch_without_local_retry(ipc_host, monkeypatch):
    ipc_host._is_server = False
    remote = MagicMock(
        side_effect=tray_service.TrayCommandError("The command may have been executed")
    )
    monkeypatch.setattr(tray_service, "try_remote_launch", remote)
    with pytest.raises(tray_service.TrayCommandError, match="may have been executed"):
        tray_service.LaunchRouter(ipc_host).launch_app("known")
    remote.assert_called_once()
    ipc_host.launcher.launch_app.assert_not_called()


@pytest.fixture
def mock_client(tray_paths, qt_app, monkeypatch):
    create_session_token(tray_paths.config_dir)
    client = MagicMock(spec=QLocalSocket)
    client.waitForConnected.return_value = True
    client.write.side_effect = len
    client.bytesToWrite.return_value = 0
    client.canReadLine.return_value = True
    client.readLine.return_value = b'{"ok": true}\n'
    client.bytesAvailable.return_value = len(client.readLine.return_value)
    client.state.return_value = QLocalSocket.LocalSocketState.ConnectedState
    factory = MagicMock(return_value=client)
    factory.LocalSocketState = QLocalSocket.LocalSocketState
    monkeypatch.setattr(tray_service, "QLocalSocket", factory)
    return client


def test_client_handles_partial_writes_and_waits_until_queue_is_empty(mock_client, tray_paths):
    first = True

    def write(data):
        nonlocal first
        if first:
            first = False
            return 7
        return len(data)

    mock_client.write.side_effect = write
    mock_client.bytesToWrite.side_effect = [10, 5, 0]
    mock_client.waitForBytesWritten.return_value = True
    assert send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known")
    assert mock_client.write.call_count == 2
    first_data = mock_client.write.call_args_list[0].args[0]
    assert mock_client.write.call_args_list[1].args[0] == first_data[7:]
    assert mock_client.waitForBytesWritten.call_count == 2
    mock_client.waitForReadyRead.assert_not_called()  # Response was already buffered.
    mock_client.setReadBufferSize.assert_called_once_with(tray_service.MAX_MESSAGE_BYTES)
    mock_client.abort.assert_called_once()


def test_client_does_not_wait_for_bytes_already_flushed(mock_client, tray_paths):
    assert send_tray_command(TrayCommand.PING, tray_paths.config_dir)
    mock_client.waitForBytesWritten.assert_not_called()
    mock_client.waitForReadyRead.assert_not_called()


@pytest.mark.parametrize("timeout_ms", [0, -1])
def test_expired_timeout_does_not_send_command(timeout_ms, mock_client, tray_paths):
    assert (
        send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known", timeout_ms=timeout_ms)
        is False
    )
    mock_client.connectToServer.assert_not_called()
    mock_client.write.assert_not_called()


def test_client_checks_pending_bytes_after_failed_wait(mock_client, tray_paths):
    mock_client.bytesToWrite.side_effect = [10, 0, 0]
    mock_client.waitForBytesWritten.return_value = False
    assert send_tray_command(TrayCommand.PING, tray_paths.config_dir)


def test_client_uses_one_deadline_for_connect_write_and_response(
    mock_client, tray_paths, monkeypatch
):
    clock = [0.0]
    deadline = MagicMock()
    deadline.remainingTime.side_effect = lambda: max(0, round(100 - clock[0] * 1000))
    monkeypatch.setattr(tray_service, "QDeadlineTimer", lambda *args: deadline)

    def connect(timeout):
        clock[0] += 0.04
        return True

    def write(timeout):
        clock[0] += 0.03
        return True

    def read(timeout):
        clock[0] += timeout / 1000
        return False

    mock_client.waitForConnected.side_effect = connect
    mock_client.bytesToWrite.side_effect = [10, 0]
    mock_client.waitForBytesWritten.side_effect = write
    mock_client.canReadLine.return_value = False
    mock_client.bytesAvailable.return_value = 0
    mock_client.waitForReadyRead.side_effect = read
    with pytest.raises(tray_service.TrayCommandError, match="may have been executed"):
        send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known", timeout_ms=100)
    assert mock_client.waitForConnected.call_args.args[0] == 100
    assert 59 <= mock_client.waitForBytesWritten.call_args.args[0] <= 61
    assert 29 <= mock_client.waitForReadyRead.call_args.args[0] <= 31
    assert clock[0] <= 0.101


@pytest.mark.parametrize("written, uncertain", [([-1], False), ([7, -1], True)])
def test_failed_write_only_allows_fallback_before_any_bytes(
    written, uncertain, mock_client, tray_paths
):
    mock_client.write.side_effect = written
    if uncertain:
        with pytest.raises(tray_service.TrayCommandError, match="may have been executed"):
            send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known")
    else:
        assert send_tray_command(TrayCommand.LAUNCH, tray_paths.config_dir, "known") is False
    mock_client.abort.assert_called_once()


def test_client_rejects_oversized_request_before_sending(mock_client, tray_paths):
    with pytest.raises(tray_service.TrayCommandError, match="request exceeds 16 KiB"):
        send_tray_command(
            TrayCommand.LAUNCH, tray_paths.config_dir, "x" * tray_service.MAX_MESSAGE_BYTES
        )
    mock_client.write.assert_not_called()


def test_invalid_json_constant_does_not_launch(ipc_host, ipc_client, tray_paths, qt_app):
    request = _request(tray_paths)[:-2] + b', "extra": NaN}\n'
    client = ipc_client()
    client.write(request)
    client.flush()
    assert _response(client, qt_app) == {"ok": False, "error": "Invalid JSON request"}
    ipc_host.launcher.launch_app.assert_not_called()


def test_cli_lost_confirmation_does_not_repeat_sent_launch(
    reply_server, tray_paths, qt_app, monkeypatch
):
    import click

    from web_app_launcher import main

    peer = reply_server([], hold=0.25)
    remote = MagicMock(
        side_effect=lambda uuid, config: send_tray_command(
            TrayCommand.LAUNCH, config, uuid, timeout_ms=100
        )
    )
    factory = MagicMock()
    monkeypatch.setattr(main, "try_remote_launch", remote)
    monkeypatch.setattr(main, "TrayService", factory)
    context = click.Context(main.run_app, obj=main.Context(tray_paths, MagicMock(), MagicMock()))
    with context, pytest.raises(click.ClickException, match="may have been executed"):
        main.run_app.callback("known")
    assert json.loads(_read_line(peer))["uuid"] == "known"
    remote.assert_called_once_with("known", tray_paths.config_dir)
    factory.assert_not_called()
