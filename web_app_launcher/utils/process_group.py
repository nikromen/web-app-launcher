import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def process_group_is_running(process: subprocess.Popen, pgid: int) -> bool | None:
    """Check our session's group; None means cleanup cannot be proven safe."""
    try:
        # Reap the direct child before checking descendants, including zombies.
        if process.poll() is None:
            return True

        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue

            try:
                stat = (entry / "stat").read_text(encoding="utf-8")
            except (FileNotFoundError, ProcessLookupError):
                continue  # A process may exit during enumeration.

            # comm is parenthesized and can itself contain spaces and ')'.
            fields = stat.rsplit(")", 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in {"Z", "X", "x"}:
                return True

        return False
    except (OSError, ValueError, IndexError) as exc:
        logger.warning("Cannot determine process group %s state; preserving profile: %s", pgid, exc)
        return None
