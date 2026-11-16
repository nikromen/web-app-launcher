import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from web_app_launcher.utils.private_files import ensure_private_directory
from web_app_launcher.utils.process_group import process_group_is_running

logger = logging.getLogger(__name__)

EPHEMERAL_SESSION_PATH_DEPTH = 2  # Application UUID followed by session UUID.
PROCESS_POLL_INTERVAL_SECONDS = 0.1


def copy_profile_tree(source: Path, dest: Path) -> None:
    existed = dest.exists()
    ensure_private_directory(dest)
    if not source.exists():
        return

    if existed:
        shutil.rmtree(dest)
        ensure_private_directory(dest)

    try:
        shutil.copytree(source, dest, symlinks=True, dirs_exist_ok=True)
    finally:
        # copytree copies root metadata as well, even when the destination exists.
        ensure_private_directory(dest)

    logger.debug("Copied profile tree from %s to %s", source, dest)


def create_empty_profile(path: Path) -> None:
    ensure_private_directory(path)
    logger.debug("Created empty profile at %s", path)


def ensure_managed_profile_directory(path: Path, profiles_dir: Path) -> bool:
    """Secure only paths inside our profile tree, checking each component before use."""
    base = Path(os.path.abspath(profiles_dir))
    target = Path(os.path.abspath(path))
    if not target.is_relative_to(base) or target == base:
        return False
    if ".." in path.parts or ".." in profiles_dir.parts:
        raise ValueError(f"Ambiguous managed profile path: {path}")

    current = ensure_private_directory(base)
    for part in target.relative_to(base).parts:
        current = ensure_private_directory(current / part)

    return True


def create_ephemeral_profile(ephemeral_base_dir: Path, app_uuid: str) -> Path:
    if not app_uuid or "/" in app_uuid or ".." in app_uuid:
        raise ValueError(f"Invalid app UUID for ephemeral profile: {app_uuid!r}")

    base = ensure_private_directory(ephemeral_base_dir)
    app_dir = ensure_private_directory(base / app_uuid)
    path = ensure_private_directory(app_dir / str(uuid.uuid4()))
    logger.debug("Created ephemeral profile at %s", path)
    return path


def validate_ephemeral_session_path(path: Path, ephemeral_base_dir: Path) -> Path:
    base = ephemeral_base_dir.resolve()
    target = path.resolve()

    if not target.is_relative_to(base):
        raise ValueError(f"Refusing ephemeral path outside base directory: {path}")

    relative = target.relative_to(base)
    if len(relative.parts) != EPHEMERAL_SESSION_PATH_DEPTH:
        raise ValueError(f"Refusing unexpected ephemeral path shape: {path}")

    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"Refusing unsafe ephemeral path components: {path}")

    return target


def cleanup_ephemeral_profile(path: Path, ephemeral_base_dir: Path) -> None:
    try:
        target = validate_ephemeral_session_path(path, ephemeral_base_dir)
    except ValueError as exc:
        logger.error("%s", exc)
        return

    if not target.is_dir():
        return

    shutil.rmtree(target)
    logger.debug("Removed ephemeral profile at %s", target)

    app_dir = target.parent
    base = ephemeral_base_dir.resolve()
    if app_dir == base:
        return

    try:
        app_dir.relative_to(base)
        app_dir.rmdir()
    except (ValueError, OSError):
        pass


def _wait_and_cleanup(
    process: subprocess.Popen,
    pgid: int,
    ephemeral_path: Path,
    ephemeral_base_dir: Path,
) -> None:
    try:
        process.wait()
    except OSError:
        logger.exception("Cannot wait for process group %s; preserving profile", pgid)
        return

    while True:
        running = process_group_is_running(process, pgid)
        if running is None:
            return

        if not running:
            cleanup_ephemeral_profile(ephemeral_path, ephemeral_base_dir)
            return

        time.sleep(PROCESS_POLL_INTERVAL_SECONDS)


def watch_process_and_cleanup(
    process: subprocess.Popen,
    pgid: int,
    ephemeral_path: Path,
    ephemeral_base_dir: Path,
) -> threading.Thread:
    """Take ownership of cleanup only after starting the non-daemon watcher."""
    watcher = threading.Thread(
        target=_wait_and_cleanup,
        args=(process, pgid, ephemeral_path, ephemeral_base_dir),
        daemon=False,
    )
    watcher.start()
    return watcher
