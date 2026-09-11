import logging
import os
import subprocess

from web_app_launcher.models import BrowserProfile, WebApp

logger = logging.getLogger(__name__)


def build_tray_env(
    app: WebApp,
    profile: BrowserProfile,
    action: str,
    pid: int | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["WEBAPP_UUID"] = app.app_uuid
    env["WEBAPP_NAME"] = app.name
    env["WEBAPP_URL"] = app.url
    env["WEBAPP_PROFILE_PATH"] = str(profile.path)
    env["WEBAPP_ACTION"] = action
    if pid is not None:
        env["WEBAPP_PID"] = str(pid)
    return env


def run_tray_command(
    app: WebApp,
    profile: BrowserProfile,
    command: str,
    action: str,
    pid: int | None = None,
) -> bool:
    command = command.strip()
    if not command:
        return False

    env = build_tray_env(app, profile, action, pid)
    logger.debug("Running tray command for %s (action=%s): %s", app.name, action, command)

    try:
        subprocess.Popen(
            ["bash", "-c", command],
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError as exc:
        logger.error("Failed to run tray command for %s: %s", app.name, exc)
        return False
