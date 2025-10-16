from unittest.mock import MagicMock, patch

import pytest

from web_app_launcher.utils.url_safety import fetch_public_http_response, validate_public_http_url


def _mock_addrinfo(ip: str) -> list[tuple]:
    return [(2, 1, 6, "", (ip, 0))]


@patch("web_app_launcher.utils.url_safety.socket.getaddrinfo")
def test_validate_public_http_url_accepts_public_host(mock_getaddrinfo):
    mock_getaddrinfo.return_value = _mock_addrinfo("93.184.216.34")
    validate_public_http_url("https://example.com")


@patch("web_app_launcher.utils.url_safety.socket.getaddrinfo")
def test_validate_public_http_url_rejects_private_ip(mock_getaddrinfo):
    mock_getaddrinfo.return_value = _mock_addrinfo("127.0.0.1")
    with pytest.raises(ValueError, match="non-public address"):
        validate_public_http_url("https://example.com")


def test_validate_public_http_url_rejects_localhost():
    with pytest.raises(ValueError, match="Localhost"):
        validate_public_http_url("http://localhost/test")


def test_validate_public_http_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="Only http and https"):
        validate_public_http_url("file:///etc/passwd")


@patch("web_app_launcher.utils.url_safety.requests.get")
@patch("web_app_launcher.utils.url_safety.socket.getaddrinfo")
def test_fetch_public_http_response_returns_success(mock_getaddrinfo, mock_get):
    mock_getaddrinfo.return_value = _mock_addrinfo("93.184.216.34")
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    mock_get.return_value = response

    result, final_url = fetch_public_http_response(
        "https://example.com",
        headers={"User-Agent": "test"},
    )

    assert result is response
    assert final_url == "https://example.com"
    mock_get.assert_called_once()


@patch("web_app_launcher.utils.url_safety.requests.get")
@patch("web_app_launcher.utils.url_safety.socket.getaddrinfo")
def test_fetch_public_http_response_rejects_redirect_to_private_ip(mock_getaddrinfo, mock_get):
    mock_getaddrinfo.side_effect = [
        _mock_addrinfo("93.184.216.34"),
        _mock_addrinfo("10.0.0.1"),
    ]

    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {"Location": "http://internal.example/"}
    mock_get.return_value = redirect_response

    with pytest.raises(ValueError, match="non-public address"):
        fetch_public_http_response(
            "https://example.com",
            headers={"User-Agent": "test"},
        )


@patch("web_app_launcher.utils.url_safety.requests.get")
@patch("web_app_launcher.utils.url_safety.socket.getaddrinfo")
def test_fetch_public_http_response_follows_safe_redirect(mock_getaddrinfo, mock_get):
    mock_getaddrinfo.return_value = _mock_addrinfo("93.184.216.34")

    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {"Location": "/final"}

    final_response = MagicMock()
    final_response.status_code = 200
    final_response.raise_for_status = MagicMock()

    mock_get.side_effect = [redirect_response, final_response]

    result, final_url = fetch_public_http_response(
        "https://example.com/start",
        headers={"User-Agent": "test"},
    )

    assert result is final_response
    assert final_url == "https://example.com/final"
    assert mock_get.call_count == 2
