import logging
import os
import subprocess
from pathlib import Path

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


def run_tray_script(
    app: WebApp,
    profile: BrowserProfile,
    script_path: Path,
    action: str,
    pid: int | None = None,
) -> bool:
    if not script_path.exists():
        logger.warning("Tray script not found: %s", script_path)
        return False

    env = build_tray_env(app, profile, action, pid)
    logger.debug("Running tray script %s for %s (action=%s)", script_path, app.name, action)

    if os.access(script_path, os.X_OK):
        command = [str(script_path)]
    elif script_path.suffix == ".sh":
        command = ["bash", str(script_path)]
    else:
        logger.warning("Tray script is not executable: %s", script_path)
        return False

    try:
        subprocess.Popen(
            command,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError as exc:
        logger.error("Failed to run tray script %s: %s", script_path, exc)
        return False
