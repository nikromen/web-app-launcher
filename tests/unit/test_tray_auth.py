import pytest

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
    assert validate_session_token(tmp_path, "0" * 64) is False


@pytest.mark.parametrize("token", [b"0" * 64, False, [], "é" * 64])
def test_validate_session_token_rejects_malformed_received_token(tmp_path, token):
    create_session_token(tmp_path)
    assert validate_session_token(tmp_path, token) is False


@pytest.mark.parametrize("stored_token", ["", "wrong-token", "A" * 64, "é" * 64])
def test_validate_session_token_rejects_malformed_stored_token(tmp_path, stored_token):
    (tmp_path / TRAY_SESSION_FILE).write_text(stored_token, encoding="utf-8")
    assert validate_session_token(tmp_path, "0" * 64) is False


def test_read_session_token_returns_none_when_missing(tmp_path):
    assert read_session_token(tmp_path) is None
