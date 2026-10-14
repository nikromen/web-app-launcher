import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QLockFile

HELPER = """
import os
import sys
import time
from pathlib import Path

session, root = map(Path, sys.argv[1:])
try:
    assert (session / "prefs.js").read_text() == "template"
    (session / "browser-state").write_text("session only")
    (root / "helper-ready").write_text(str(os.getpid()))
    deadline = time.monotonic() + 10
    while not (root / "release").exists():
        assert time.monotonic() < deadline, "Browser helper was not released"
        time.sleep(0.01)
    assert session.is_dir(), "Profile was removed while the browser was running"
finally:
    (root / "helper-done").touch()
"""

WORKER = """
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import click
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from web_app_launcher import main
from web_app_launcher.constants import APP_NAME
from web_app_launcher.controllers.main_controller import MainController
from web_app_launcher.models import Browser, BrowserProfile, ProfileMode, WebApp
from web_app_launcher.tray import tray_manager
from web_app_launcher.tray.tray_service import TrayService
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.path_manager import PathManager
from web_app_launcher.utils.profile_fork import create_ephemeral_profile

mode, root, helper = sys.argv[1:]
root = Path(root)
qt_app = QApplication([])
qt_app.setApplicationName(APP_NAME)
paths = PathManager()
browser = Browser(key="test", name="Test", executable=sys.executable,
                  command_template="{executable}")
template = root / "template"
template.mkdir()
(template / "prefs.js").write_text("template")
profile = BrowserProfile(profile_uuid="template", name="Template",
                         browser=browser, path=template)
app = WebApp(app_uuid="app", name="Test", url="https://example.invalid",
             profile_uuid=profile.profile_uuid, profile_mode=ProfileMode.EPHEMERAL,
             tray_enabled=mode in {"unavailable", "registration_error", "registered"})
config = ConfigManager(paths)
config.save_profiles({profile.profile_uuid: profile})
config.save_apps({app.app_uuid: app})
sibling = create_ephemeral_profile(paths.ephemeral_profiles_dir, app.app_uuid)
(sibling / "keep").write_text("other session")
browsers = BrowserManager()
browsers.installed_browsers = {browser.key: browser}

def build_command(profile, **kwargs):
    (root / "session").write_text(str(profile.path))
    return [sys.executable, "-c", helper, str(profile.path), str(root)]

browsers.build_launch_command = build_command
services = []

def create_service(*args):
    service = TrayService(*args)
    if mode == "registration_error":
        service.tray_manager.register = MagicMock(side_effect=RuntimeError("tray failed"))
    if mode == "registered":
        service.tray_manager._icon_for_app = MagicMock(return_value=None)
        service.tray_manager._build_menu = MagicMock(return_value=None)
    services.append(service)
    return service

main.TrayService = create_service
if mode == "registered":
    tray_manager.QSystemTrayIcon = MagicMock()
    tray_manager.QSystemTrayIcon.isSystemTrayAvailable.return_value = True
else:
    tray_manager.QSystemTrayIcon.isSystemTrayAvailable = lambda: False

if mode in {"gui_close", "registered"}:
    service = create_service(paths, browsers, config)
    service.launcher.launch_app(app.app_uuid)
    if mode == "gui_close":
        controller = MainController(config, service.launcher, paths, browsers,
                                    service.tray_manager)
        qt_app.setQuitOnLastWindowClosed(False)
        QTimer.singleShot(0, controller.handle_window_closing)
        result = qt_app.exec()
    else:
        assert service.tray_manager.has_running_apps()
        service.tray_manager._unregister(app.app_uuid)
        service.close()
        result = 0
else:
    context = click.Context(main.run_app, obj=main.Context(paths, browsers, config))
    with context:
        result = main.run_app.callback(app.app_uuid)

print(json.dumps({"result": result, "session": (root / "session").read_text(),
                  "template": str(template), "sibling": str(sibling),
                  "socket": str(paths.tray_socket_file), "lock": str(paths.tray_lock_file),
                  "is_server": services[0].is_server}), flush=True)
# Returning from the script must still allow the watcher to finish its cleanup.
"""


def _wait_for_file(path):
    deadline = time.monotonic() + 3
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), f"Helper did not create {path}"


@pytest.fixture
def launcher_worker(tmp_path):
    processes = []

    def start(mode):
        runtime = tmp_path / "r"
        runtime.mkdir(mode=0o700)
        env = dict(os.environ)
        env.update(
            XDG_RUNTIME_DIR=str(runtime),
            XDG_CONFIG_HOME=str(tmp_path / "config"),
            XDG_DATA_HOME=str(tmp_path / "data"),
        )
        process = subprocess.Popen(
            [sys.executable, "-X", "faulthandler", "-c", WORKER, mode, str(tmp_path), HELPER],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        processes.append(process)
        readable, _, _ = select.select([process.stdout], [], [], 5)
        assert readable, "Launcher did not return"
        line = process.stdout.readline()
        if not line:
            _, errors = process.communicate(timeout=3)
            pytest.fail(f"Launcher worker exited with {process.returncode}:\n{errors}")
        return process, json.loads(line)

    yield start
    (tmp_path / "release").touch()
    for process in processes:
        try:
            process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)
    if (tmp_path / "helper-ready").exists():
        _wait_for_file(tmp_path / "helper-done")


@pytest.mark.parametrize(
    "mode", ["no_tray", "unavailable", "registration_error", "gui_close", "registered"]
)
def test_cleanup_survives_main_return_and_gui_shutdown(mode, launcher_worker, tmp_path):
    process, state = launcher_worker(mode)
    assert state["result"] == (1 if mode == "registration_error" else 0)
    _wait_for_file(tmp_path / "helper-ready")
    session = Path(state["session"])
    template = Path(state["template"])
    sibling = Path(state["sibling"])
    assert (session / "browser-state").read_text(encoding="utf-8") == "session only"
    assert (template / "prefs.js").read_text(encoding="utf-8") == "template"
    assert (sibling / "keep").read_text(encoding="utf-8") == "other session"
    with pytest.raises(subprocess.TimeoutExpired):
        process.wait(timeout=0.15)

    # The watcher may keep Python alive, but no dormant tray server may remain.
    assert not state["is_server"]
    assert not Path(state["socket"]).exists()
    assert not Path(state["lock"]).exists()
    lock = QLockFile(state["lock"])
    assert lock.tryLock(0)
    lock.unlock()

    (tmp_path / "release").touch()
    _, errors = process.communicate(timeout=5)
    assert process.returncode == 0, errors
    assert (tmp_path / "helper-done").exists()
    assert not session.exists()
    assert (template / "prefs.js").read_text(encoding="utf-8") == "template"
    assert not (template / "browser-state").exists()
    assert (sibling / "keep").read_text(encoding="utf-8") == "other session"
