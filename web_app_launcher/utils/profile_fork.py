import logging
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def copy_profile_tree(source: Path, dest: Path) -> None:
    if not source.exists():
        dest.mkdir(parents=True, exist_ok=True)
        return

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(source, dest, symlinks=True)
    logger.debug("Copied profile tree from %s to %s", source, dest)


def create_empty_profile(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    logger.debug("Created empty profile at %s", path)


def create_ephemeral_profile(ephemeral_base_dir: Path, app_uuid: str) -> Path:
    if not app_uuid or "/" in app_uuid or ".." in app_uuid:
        raise ValueError(f"Invalid app UUID for ephemeral profile: {app_uuid!r}")

    base = ephemeral_base_dir.resolve()
    path = base / app_uuid / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    logger.debug("Created ephemeral profile at %s", path)
    return path


def validate_ephemeral_session_path(path: Path, ephemeral_base_dir: Path) -> Path:
    base = ephemeral_base_dir.resolve()
    target = path.resolve()

    if not target.is_relative_to(base):
        raise ValueError(f"Refusing ephemeral path outside base directory: {path}")

    relative = target.relative_to(base)
    if len(relative.parts) != 2:
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


def watch_process_and_cleanup(
    process: subprocess.Popen,
    ephemeral_path: Path,
    ephemeral_base_dir: Path,
) -> None:
    def _wait_and_cleanup() -> None:
        process.wait()
        cleanup_ephemeral_profile(ephemeral_path, ephemeral_base_dir)

    threading.Thread(target=_wait_and_cleanup, daemon=True).start()
