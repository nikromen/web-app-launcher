import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def try_activate_pid(pid: int) -> bool:
    """Best-effort attempt to raise a window on Linux X11 via xdotool."""
    if pid <= 0:
        return False

    if _try_xdotool(pid):
        return True

    logger.debug("Could not activate window for PID %s", pid)
    return False


def _try_xdotool(pid: int) -> bool:
    if not shutil.which("xdotool"):
        return False

    try:
        result = subprocess.run(
            ["xdotool", "search", "--pid", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        window_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not window_ids:
            return False

        activate = subprocess.run(
            ["xdotool", "windowactivate", window_ids[-1]],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return activate.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("xdotool activation failed for PID %s: %s", pid, exc)
        return False
