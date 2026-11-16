import logging
import re
import secrets
import stat
from pathlib import Path
from typing import TypeGuard

from web_app_launcher.constants import (
    TRAY_SESSION_FILE,
    TRAY_SESSION_TOKEN_BYTES,
    TRAY_SESSION_TOKEN_HEX_LENGTH,
)

logger = logging.getLogger(__name__)


def create_session_token(config_dir: Path) -> str:
    token = secrets.token_hex(TRAY_SESSION_TOKEN_BYTES)
    session_path = config_dir / TRAY_SESSION_FILE
    session_path.write_text(token, encoding="utf-8")
    session_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token


def read_session_token(config_dir: Path) -> str | None:
    session_path = config_dir / TRAY_SESSION_FILE
    if not session_path.exists():
        return None
    return session_path.read_text(encoding="utf-8").strip()


def validate_session_token(config_dir: Path, token: object) -> bool:
    if not _valid_token_format(token):
        return False

    expected = read_session_token(config_dir)
    if not _valid_token_format(expected):
        return False

    return secrets.compare_digest(expected, token)


def _valid_token_format(token: object) -> TypeGuard[str]:
    return (
        isinstance(token, str)
        and re.fullmatch(rf"[0-9a-f]{{{TRAY_SESSION_TOKEN_HEX_LENGTH}}}", token) is not None
    )
