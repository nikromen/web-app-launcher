import logging
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from web_app_launcher.constants import DEFAULT_ICON_PATH
from web_app_launcher.models import BrowserProfile, WebApp
from web_app_launcher.utils.tray_script_runner import run_tray_script
from web_app_launcher.utils.window_activator import try_activate_pid

logger = logging.getLogger(__name__)


@dataclass
class _RunningEntry:
    app: WebApp
    profile: BrowserProfile
    process: subprocess.Popen
    tray_icon: QSystemTrayIcon


class TrayManager(QObject):
    """Manages per-app system tray icons for running web applications."""

    running_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running: dict[str, _RunningEntry] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_processes)

    def has_running_apps(self) -> bool:
        return bool(self._running)

    def running_count(self) -> int:
        return len(self._running)

    def is_running(self, app_uuid: str) -> bool:
        return app_uuid in self._running

    def get_pid(self, app_uuid: str) -> int | None:
        entry = self._running.get(app_uuid)
        return entry.process.pid if entry else None

    def register(
        self,
        app: WebApp,
        profile: BrowserProfile,
        process: subprocess.Popen,
    ) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning(
                "System tray is not available. Tray icon for %s will not be shown.",
                app.name,
            )
            return

        if app.app_uuid in self._running:
            self.stop_app(app.app_uuid)

        tray_icon = QSystemTrayIcon(self._icon_for_app(app))
        tray_icon.setToolTip(app.name)
        tray_icon.setContextMenu(self._build_menu(app))
        tray_icon.show()

        self._running[app.app_uuid] = _RunningEntry(
            app=app,
            profile=profile,
            process=process,
            tray_icon=tray_icon,
        )
        if not self._poll_timer.isActive():
            self._poll_timer.start()

        logger.info("Tray icon created for %s (PID %s)", app.name, process.pid)
        self.running_count_changed.emit(len(self._running))

    def show_app(self, app_uuid: str) -> None:
        entry = self._running.get(app_uuid)
        if not entry:
            return

        app = entry.app
        profile = entry.profile
        pid = entry.process.pid

        if app.show_script and app.show_script.exists():
            if run_tray_script(app, profile, app.show_script, "show", pid):
                return

        if try_activate_pid(pid):
            return

        logger.info(
            "Show failed for %s (PID %s). Configure a show script in app settings for Wayland.",
            app.name,
            pid,
        )

    def stop_all(self) -> None:
        for app_uuid in list(self._running.keys()):
            self.stop_app(app_uuid)

    def stop_app(self, app_uuid: str) -> None:
        entry = self._running.get(app_uuid)
        if not entry:
            return

        process = entry.process
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    process.kill()

        self._unregister(app_uuid)

    def _unregister(self, app_uuid: str) -> None:
        entry = self._running.pop(app_uuid, None)
        if not entry:
            return

        entry.tray_icon.hide()
        entry.tray_icon.deleteLater()

        if not self._running:
            self._poll_timer.stop()

        logger.info("Tray icon removed for %s", entry.app.name)
        self.running_count_changed.emit(len(self._running))

    def _poll_processes(self) -> None:
        for app_uuid, entry in list(self._running.items()):
            if entry.process.poll() is not None:
                self._unregister(app_uuid)

    def _build_menu(self, app: WebApp) -> QMenu:
        menu = QMenu()

        show_action = QAction("Show", menu)
        show_action.triggered.connect(lambda: self.show_app(app.app_uuid))
        menu.addAction(show_action)

        stop_action = QAction("Stop", menu)
        stop_action.triggered.connect(lambda: self.stop_app(app.app_uuid))
        menu.addAction(stop_action)

        if app.tray_scripts:
            menu.addSeparator()
            for script in app.tray_scripts:
                if not script.path.exists():
                    continue

                action = QAction(script.name, menu)
                action.triggered.connect(
                    lambda checked=False, s=script.path: self._run_user_script(app, s),
                )
                menu.addAction(action)

        return menu

    def _run_user_script(self, app: WebApp, script_path: Path) -> None:
        entry = self._running.get(app.app_uuid)
        if not entry:
            return

        pid = entry.process.pid
        run_tray_script(app, entry.profile, script_path, "script", pid)

    def _icon_for_app(self, app: WebApp) -> QIcon:
        if app.icon_path and app.icon_path.exists():
            return QIcon(str(app.icon_path))

        return QIcon(str(DEFAULT_ICON_PATH))
