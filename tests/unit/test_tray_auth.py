from web_app_launcher.constants import TRAY_SESSION_FILE
from web_app_launcher.tray.tray_auth import (
    create_session_token,
    read_session_token,
    validate_session_token,
)


def test_create_and_validate_session_token(tmp_path):
    token = create_session_token(tmp_path)
    session_path = tmp_path / TRAY_SESSION_FILE

    assert session_path.exists()
    assert session_path.read_text(encoding="utf-8") == token
    assert validate_session_token(tmp_path, token) is True


def test_validate_session_token_rejects_wrong_token(tmp_path):
    create_session_token(tmp_path)
    assert validate_session_token(tmp_path, "wrong-token") is False


def test_validate_session_token_without_file_returns_false(tmp_path):
    assert validate_session_token(tmp_path, "anything") is False


def test_read_session_token_returns_none_when_missing(tmp_path):
    assert read_session_token(tmp_path) is None
