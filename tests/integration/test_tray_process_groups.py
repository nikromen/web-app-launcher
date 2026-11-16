import os
import subprocess
import sys

import pytest

SCENARIO_TIMEOUT_SECONDS = 20


CHILD = """
import os
import signal
import sys
import time
from pathlib import Path

POLL_INTERVAL_SECONDS = 0.01


root, name, ignore = sys.argv[1:]
root = Path(root)
if ignore == "yes":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
(root / (name + "-ready")).write_text(str(os.getpid()))
while True:
    time.sleep(POLL_INTERVAL_SECONDS)
"""

WRAPPER = """
import subprocess
import sys
import time
from pathlib import Path

POLL_INTERVAL_SECONDS = 0.01
STARTUP_TIMEOUT_SECONDS = 3


root, name, ignore, child = sys.argv[1:]
subprocess.Popen([sys.executable, "-c", child, root, name, ignore])
deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
while not (Path(root) / (name + "-ready")).exists():
    assert time.monotonic() < deadline, "Child did not start"
    time.sleep(POLL_INTERVAL_SECONDS)
"""

WORKER = """
import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtCore import QTimer, QEvent
from PySide6.QtWidgets import QApplication
from web_app_launcher.controllers.main_controller import MainController
from web_app_launcher.models import Browser, BrowserProfile, WebApp
from web_app_launcher.tray import tray_manager

CLEANUP_TIMEOUT_SECONDS = 3
HEARTBEAT_INTERVAL_MS = 10
INITIAL_STOP_DELAY_MS = 100
MAX_KILL_DELAY_SECONDS = 7
MAX_STOP_REQUEST_SECONDS = 0.5
MIN_HEARTBEATS_DURING_STOP = 10
MIN_KILL_DELAY_SECONDS = 4.9
PROCESS_TIMEOUT_SECONDS = 5
PR_SET_CHILD_SUBREAPER = 36
REPEATED_STOP_DELAY_MS = 1000
STOP_WATCHDOG_TIMEOUT_MS = 10000


mode, root, wrapper, child = sys.argv[1:]
root = Path(root)
# Keep orphaned descendants here so every test child can be reaped explicitly.
assert ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
qt = QApplication([])
qt.setQuitOnLastWindowClosed(False)
manager = tray_manager.TrayManager()
tray_manager.QSystemTrayIcon = MagicMock()
manager._icon_for_app = MagicMock(return_value=None)
manager._build_menu = MagicMock(return_value=None)
browser = Browser(key="test", name="Test", executable=sys.executable,
                  command_template="{executable}")
profile = BrowserProfile(profile_uuid="template", name="Template",
                         browser=browser, path=root / "template")
profile.path.mkdir()
(profile.path / "keep").write_text("template")
processes = []
child_pids = []
real_killpg = os.killpg
signals = []

def record_signal(pgid, sig):
    signals.append((pgid, sig, time.monotonic()))
    real_killpg(pgid, sig)

tray_manager.os.killpg = record_signal
heartbeats = []
heartbeat = QTimer()
heartbeat.setInterval(HEARTBEAT_INTERVAL_MS)
heartbeat.timeout.connect(lambda: heartbeats.append(time.monotonic()))
timeout = QTimer()
timeout.setSingleShot(True)
timeout.timeout.connect(qt.quit)
controller = None
try:
    unrelated = subprocess.Popen([sys.executable, "-c", child, str(root), "other", "yes"],
                                 start_new_session=True)
    processes.append(unrelated)
    count = 2 if mode == "stop_all" else 1
    for index in range(count):
        name = str(index)
        process = subprocess.Popen(
            [sys.executable, "-c", wrapper, str(root), name,
             "no" if mode == "term" else "yes", child],
            start_new_session=True,
        )
        processes.append(process)
        pgid = process.pid
        process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        assert process.returncode == 0
        child_pid = int((root / (name + "-ready")).read_text())
        child_pids.append(child_pid)
        assert os.getpgid(child_pid) == pgid
        app = WebApp(app_uuid=name, name=name, url="https://example.invalid",
                     profile_uuid=profile.profile_uuid, tray_enabled=True)
        manager.register(app, profile, process, pgid)
        manager._poll_processes()
        assert manager.is_running(name), "Wrapper exit discarded its live group"

    if mode == "quit":
        config = MagicMock()
        config.load_apps.return_value = {}
        config.load_profiles.return_value = {}
        controller = MainController(config, MagicMock(), MagicMock(), MagicMock(), manager)
        manager.running_count_changed.connect(controller.maybe_quit)
        QTimer.singleShot(0, controller.quit_application)
    else:
        manager.running_count_changed.connect(lambda count: qt.quit() if count == 0 else None)
        started = time.monotonic()
        manager.stop_all()
        assert time.monotonic() - started < MAX_STOP_REQUEST_SECONDS, "Stop blocked the Qt thread"
        assert manager.running_count() == count, "Stop discarded unconfirmed groups"

    # Repeated requests while stopping must preserve the first deadline.
    QTimer.singleShot(INITIAL_STOP_DELAY_MS, manager.stop_all)
    QTimer.singleShot(REPEATED_STOP_DELAY_MS, manager.stop_all)
    heartbeat.start()
    timeout.start(STOP_WATCHDOG_TIMEOUT_MS)
    qt.exec()
    assert timeout.isActive(), "Stop did not complete before watchdog timeout"
    assert not manager.has_running_apps()
    assert not manager._poll_timer.isActive()
    assert heartbeats, "Qt event loop was blocked"
    assert unrelated.poll() is None, "Stop signalled an unrelated process group"
    assert (profile.path / "keep").read_text() == "template"

    for process in processes[1:]:
        sent = [(sig, when) for pgid, sig, when in signals if pgid == process.pid]
        expected = [signal.SIGTERM] if mode == "term" else [signal.SIGTERM, signal.SIGKILL]
        assert [sig for sig, _ in sent] == expected, sent
        if mode != "term":
            assert MIN_KILL_DELAY_SECONDS <= sent[1][1] - sent[0][1] < MAX_KILL_DELAY_SECONDS, sent
            during_wait = [when for when in heartbeats if sent[0][1] < when < sent[1][1]]
            assert len(during_wait) > MIN_HEARTBEATS_DURING_STOP, (
                "Qt did not run while waiting to escalate"
            )
    if mode == "stop_all":
        term_times = [when for _, sig, when in signals if sig == signal.SIGTERM]
        assert max(term_times) - min(term_times) < MAX_STOP_REQUEST_SECONDS
    for pid in child_pids:
        assert Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
finally:
    heartbeat.stop()
    timeout.stop()
    manager._poll_timer.stop()
    for process in processes:
        try:
            real_killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=CLEANUP_TIMEOUT_SECONDS)
    # The wrapper might fail before reporting its child; still reap all adoptees.
    while True:
        try:
            os.waitpid(-1, 0)
        except ChildProcessError:
            break
    for app_uuid in list(manager._running):
        manager._unregister(app_uuid)
    if controller is not None:
        controller.deleteLater()
    manager.deleteLater()
    qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
"""


@pytest.mark.parametrize("mode", ["term", "kill", "stop_all", "quit"])
def test_tray_stops_wrapper_groups_without_blocking_qt(mode, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    env = dict(os.environ)
    env.update(
        XDG_RUNTIME_DIR=str(runtime),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_DATA_HOME=str(tmp_path / "data"),
    )
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", WORKER, mode, str(tmp_path), WRAPPER, CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=SCENARIO_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stdout + result.stderr
