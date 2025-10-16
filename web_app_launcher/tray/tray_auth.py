import logging
import secrets
from pathlib import Path

from web_app_launcher.constants import TRAY_SESSION_FILE

logger = logging.getLogger(__name__)


def create_session_token(config_dir: Path) -> str:
    token = secrets.token_hex(32)
    session_path = config_dir / TRAY_SESSION_FILE
    session_path.write_text(token, encoding="utf-8")
    session_path.chmod(0o600)
    return token


def read_session_token(config_dir: Path) -> str | None:
    session_path = config_dir / TRAY_SESSION_FILE
    if not session_path.exists():
        return None
    return session_path.read_text(encoding="utf-8").strip()


def validate_session_token(config_dir: Path, token: str) -> bool:
    expected = read_session_token(config_dir)
    if not expected or not token:
        return False
    return secrets.compare_digest(expected, token)
