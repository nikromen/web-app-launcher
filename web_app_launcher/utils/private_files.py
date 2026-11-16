import os
import stat
import tempfile
from pathlib import Path

PRIVATE_DIRECTORY_MODE = stat.S_IRWXU
PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR


def ensure_private_directory(path: Path) -> Path:
    """Protect this owned directory, without resolving or chmodding its parents."""
    path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid():
            raise PermissionError(f"Directory is not owned by the current user: {path}")

        if stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
            os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != PRIVATE_DIRECTORY_MODE:
            raise PermissionError(f"Could not secure directory: {path}")
    finally:
        os.close(descriptor)

    return path


def _protect_file(descriptor: int, path: Path) -> None:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise PermissionError(f"Not an owned regular file: {path}")

    if stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE:
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
    if stat.S_IMODE(os.fstat(descriptor).st_mode) != PRIVATE_FILE_MODE:
        raise PermissionError(f"Could not secure file: {path}")


def _open_private_file(path: Path) -> int:
    # O_NONBLOCK permits rejecting a FIFO without blocking on an untrusted file type.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        _protect_file(descriptor, path)
    except BaseException:
        os.close(descriptor)
        raise

    return descriptor


def read_private_text(path: Path) -> str | None:
    ensure_private_directory(path.parent)
    try:
        descriptor = _open_private_file(path)
    except FileNotFoundError:
        return None

    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as source:
            return source.read()
    finally:
        os.close(descriptor)


def atomic_write_private_text(path: Path, content: str) -> None:
    ensure_private_directory(path.parent)
    try:
        existing = _open_private_file(path)
    except FileNotFoundError:
        pass
    else:
        os.close(existing)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        _protect_file(descriptor, temporary_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as destination:
            destination.write(content)

        # rename replaces a directory entry; it never follows a destination symlink.
        temporary_path.replace(path)
    finally:
        os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
