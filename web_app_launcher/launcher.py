import json
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING

from web_app_launcher.models import resolve_app_profile
from web_app_launcher.utils.browser_manager import BrowserManager
from web_app_launcher.utils.config_manager import ConfigManager
from web_app_launcher.utils.firefox_chrome import ensure_profile_chrome_for_app
from web_app_launcher.utils.path_manager import PathManager

if TYPE_CHECKING:
    from web_app_launcher.tray.tray_manager import TrayManager

logger = logging.getLogger(__name__)


class AppLauncher:
    def __init__(
        self,
        path_manager: PathManager,
        browser_manager: BrowserManager,
        config_manager: ConfigManager,
        tray_manager: "TrayManager | None" = None,
    ) -> None:
        self.path_manager = path_manager
        self.browser_manager = browser_manager
        self.config_manager = config_manager
        self.tray_manager = tray_manager

    def launch_app(self, app_uuid: str) -> int:
        logger.info("Launching app: %s", app_uuid)

        apps = self.config_manager.load_apps()
        logger.debug("Loaded apps: %s", list(apps.keys()))

        profiles = self.config_manager.load_profiles()
        logger.debug("Loaded profiles: %s", list(profiles.keys()))

        if app_uuid not in apps:
            raise ValueError(f"Application with ID {app_uuid} not found")

        app = apps[app_uuid]

        if app.tray_enabled and self.tray_manager and self.tray_manager.is_running(app_uuid):
            logger.info("App %s is already running, showing existing window", app_uuid)
            self.tray_manager.show_app(app_uuid)
            pid = self.tray_manager.get_pid(app_uuid)
            return pid if pid is not None else 0
        profile = resolve_app_profile(app, profiles)
        logger.info("Found app: %s", app.name)
        logger.debug(
            "Full app configuration: %s",
            json.dumps(app.model_dump(mode="json"), indent=4, default=str),
        )

        if not self.browser_manager.installed_browsers:
            raise RuntimeError("No browsers installed or detected")

        logger.debug(
            "Installed browsers: %s",
            list(self.browser_manager.installed_browsers.keys()),
        )

        logger.info("Using profile: %s -> %s", profile.name, profile.path)
        logger.debug("Profile exists on disk: %s", profile.path.exists())

        if not profile.path.exists():
            logger.info("Creating profile directory: %s", profile.path)
            profile.path.mkdir(parents=True, exist_ok=True)

        ensure_profile_chrome_for_app(
            profile.path,
            profile.browser.key,
            app.show_navigation_bar,
        )

        browser = profile.browser
        logger.info("Browser: %s (%s)", browser.name, browser.executable)

        if not shutil.which(browser.executable):
            raise RuntimeError(
                f"Browser '{browser.name}' (executable: '{browser.executable}') "
                f"is not installed or not found in PATH. "
                f"Please install the browser or update the application configuration.",
            )

        logger.debug(
            "Browser executable found at: %s",
            shutil.which(browser.executable),
        )

        command = self.browser_manager.build_launch_command(
            profile=profile,
            url=app.url,
            incognito=app.incognito_mode,
            show_navigation_bar=app.show_navigation_bar,
            extra_args=app.extra_args,
        )

        logger.debug("Launch command: %s", " ".join(command))

        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        logger.debug("Process started with PID: %s", process.pid)
        if process.poll() is not None:
            raise RuntimeError(f"Process exited immediately with code {process.returncode}.")

        logger.info("Process started successfully with PID: %s", process.pid)

        if app.tray_enabled and self.tray_manager:
            self.tray_manager.register(app, profile, process)

        return process.pid
