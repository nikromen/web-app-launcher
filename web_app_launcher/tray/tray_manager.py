import logging
import os
import signal
import subprocess
from dataclasses import dataclass

from PySide6.QtCore import QDeadlineTimer, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from web_app_launcher.constants import DEFAULT_ICON_PATH
from web_app_launcher.models import BrowserProfile, WebApp
from web_app_launcher.utils.process_group import process_group_is_running
from web_app_launcher.utils.tray_script_runner import run_tray_command
from web_app_launcher.utils.window_activator import try_activate_pid

logger = logging.getLogger(__name__)


@dataclass
class _RunningEntry:
    app: WebApp
    profile: BrowserProfile
    process: subprocess.Popen
    pgid: int
    tray_icon: QSystemTrayIcon
    stop_deadline: QDeadlineTimer | None = None
    kill_sent: bool = False


class TrayManager(QObject):
    """Manages per-app system tray icons for running web applications."""

    running_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running: dict[str, _RunningEntry] = {}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.setTimerType(Qt.TimerType.PreciseTimer)
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
        pgid: int,
    ) -> None:
        existing = self._running.get(app.app_uuid)
        if existing is not None:
            if process_group_is_running(existing.process, existing.pgid) is not False:
                raise RuntimeError(f"Application {app.name} is still tracked; refusing replacement")

            self._unregister(app.app_uuid)

        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning(
                "System tray is not available. Tray icon for %s will not be shown.",
                app.name,
            )
            return

        tray_icon = QSystemTrayIcon(self._icon_for_app(app))
        tray_icon.setToolTip(app.name)
        tray_icon.setContextMenu(self._build_menu(app))
        tray_icon.show()

        self._running[app.app_uuid] = _RunningEntry(
            app=app,
            profile=profile,
            process=process,
            pgid=pgid,
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

        if app.show_script and run_tray_command(app, profile, app.show_script, "show", pid):
            return

        if try_activate_pid(pid):
            return

        logger.info(
            "Show failed for %s (PID %s). Configure a show command in app settings for Wayland.",
            app.name,
            pid,
        )

    def stop_all(self) -> None:
        failures = []
        for app_uuid in list(self._running.keys()):
            try:
                self.stop_app(app_uuid)
            except RuntimeError as exc:
                failures.append(str(exc))

        if failures:
            raise RuntimeError("Could not stop all applications: " + "; ".join(failures))

    def stop_app(self, app_uuid: str) -> None:
        """A successful IPC Stop acknowledges initiation, not group termination."""
        entry = self._running.get(app_uuid)
        if not entry or entry.stop_deadline is not None:
            return

        running = process_group_is_running(entry.process, entry.pgid)
        if running is False:
            self._unregister(app_uuid)
            return

        if running is None:
            message = f"Cannot stop {entry.app.name}: process group state is unknown"
            logger.error("%s", message)
            raise RuntimeError(message)

        if self._signal_group(entry, signal.SIGTERM):
            entry.stop_deadline = QDeadlineTimer(5000, Qt.TimerType.PreciseTimer)
            self._poll_timer.setInterval(100)

    def _signal_group(self, entry: _RunningEntry, sig: signal.Signals) -> bool:
        try:
            if entry.pgid <= 1 or entry.pgid == os.getpgrp() or entry.pgid != entry.process.pid:
                raise ValueError(f"Refusing unsafe process group {entry.pgid}")

            try:
                os.killpg(entry.pgid, sig)
            except ProcessLookupError:
                if process_group_is_running(entry.process, entry.pgid) is False:
                    self._unregister(entry.app.app_uuid)
                    return False

                raise
        except (OSError, ValueError) as exc:
            message = f"Cannot send {sig.name} to {entry.app.name} (PGID {entry.pgid}): {exc}"
            logger.error("%s", message)
            raise RuntimeError(message) from exc

        return True

    def _unregister(self, app_uuid: str) -> None:
        entry = self._running.pop(app_uuid, None)
        if not entry:
            return

        entry.tray_icon.hide()
        entry.tray_icon.deleteLater()

        if not self._running:
            self._poll_timer.stop()
        elif not any(entry.stop_deadline is not None for entry in self._running.values()):
            self._poll_timer.setInterval(2000)

        logger.info("Tray icon removed for %s", entry.app.name)
        self.running_count_changed.emit(len(self._running))

    def _poll_processes(self) -> None:
        for app_uuid, entry in list(self._running.items()):
            running = process_group_is_running(entry.process, entry.pgid)
            if running is False:
                self._unregister(app_uuid)
            elif (
                running is True
                and entry.stop_deadline is not None
                and entry.stop_deadline.hasExpired()
                and not entry.kill_sent
            ):
                # Attempt escalation once; keep tracking until termination is confirmed.
                entry.kill_sent = True
                try:
                    self._signal_group(entry, signal.SIGKILL)
                except RuntimeError:
                    pass  # Already logged; a failed signal does not prove termination.

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
                if not script.command.strip():
                    continue

                action = QAction(script.name, menu)
                action.triggered.connect(
                    lambda checked=False, cmd=script.command: self._run_user_script(app, cmd),
                )
                menu.addAction(action)

        return menu

    def _run_user_script(self, app: WebApp, command: str) -> None:
        entry = self._running.get(app.app_uuid)
        if not entry:
            return

        pid = entry.process.pid
        run_tray_command(app, entry.profile, command, "script", pid)

    def _icon_for_app(self, app: WebApp) -> QIcon:
        if app.icon_path and app.icon_path.exists():
            return QIcon(str(app.icon_path))

        return QIcon(str(DEFAULT_ICON_PATH))
