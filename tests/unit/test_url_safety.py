import gzip
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
import requests
from urllib3.response import HTTPResponse

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


@pytest.fixture
def http_get():
    with (
        patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns,
        patch("web_app_launcher.utils.url_safety._NoRedirectSession.get") as get,
    ):
        dns.return_value = _mock_addrinfo("93.184.216.34")

        yield get


def _response(chunks=(), headers=None, status=200):
    response = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    response.iter_content.return_value = iter(chunks)
    return response


def _fetch(destination, max_bytes=8):
    return fetch_public_http_response(
        "https://example.com/start", headers={}, destination=destination, max_bytes=max_bytes
    )


def test_bounded_response_success(http_get):
    response = _response([b"1234", b"5678"], {"Content-Type": "text/html"})
    http_get.return_value = response
    destination = BytesIO()

    assert _fetch(destination) == ("text/html", "https://example.com/start")
    assert destination.getvalue() == b"12345678"

    response.close.assert_called_once()
    http_get.assert_called_once_with(
        "https://example.com/start", headers={}, timeout=10, allow_redirects=False, stream=True
    )


@pytest.mark.parametrize("length", [None, "9", "1", "invalid", "-1"])
def test_response_size_limit_with_untrusted_content_length(http_get, length):
    headers = {} if length is None else {"Content-Length": length}
    response = _response([b"1234", b"56789", b"unread"], headers)
    http_get.return_value = response
    destination = BytesIO()

    with pytest.raises(ValueError, match="size limit"):
        _fetch(destination)

    assert len(destination.getvalue()) <= 8
    if length == "9":
        response.iter_content.assert_not_called()

    response.close.assert_called_once()


def test_limit_counts_decompressed_bytes(http_get):
    compressed = gzip.compress(b"a" * 100)
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Length"] = str(len(compressed))
    response.raw = HTTPResponse(
        body=BytesIO(compressed), headers={"Content-Encoding": "gzip"}, preload_content=False
    )
    http_get.return_value = response

    with patch.object(response, "close", wraps=response.close) as close:
        with pytest.raises(ValueError, match="size limit"):
            _fetch(BytesIO(), max_bytes=50)
        close.assert_called_once()


@pytest.mark.parametrize("error", [requests.HTTPError(), requests.ConnectionError(), OSError()])
def test_response_closed_on_status_read_or_write_error(http_get, error):
    response = _response([b"body"])
    destination = BytesIO()
    if isinstance(error, requests.HTTPError):
        response.raise_for_status.side_effect = error
    elif isinstance(error, requests.ConnectionError):
        response.iter_content.side_effect = error
    else:
        destination = MagicMock()
        destination.write.side_effect = error
    http_get.return_value = response

    with pytest.raises(type(error)):
        _fetch(destination)

    response.close.assert_called_once()


def test_follows_redirect_without_reading_body(http_get):
    redirect = _response(headers={"Location": "/final", "Content-Length": "99999"}, status=302)
    final = _response([b"ok"])
    http_get.side_effect = [redirect, final]

    assert _fetch(BytesIO()) == ("", "https://example.com/final")

    redirect.iter_content.assert_not_called()
    redirect.close.assert_called_once()
    final.close.assert_called_once()


def test_rejected_redirect_is_closed(http_get):
    redirect = _response(headers={"Location": "http://localhost/"}, status=302)
    http_get.return_value = redirect

    with pytest.raises(ValueError, match="Localhost"):
        _fetch(BytesIO())

    redirect.iter_content.assert_not_called()
    redirect.close.assert_called_once()


def test_redirect_to_private_ip_is_closed(http_get):
    redirect = _response(headers={"Location": "https://internal.example/"}, status=302)
    http_get.return_value = redirect

    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        dns.side_effect = [_mock_addrinfo("93.184.216.34"), _mock_addrinfo("10.0.0.1")]
        with pytest.raises(ValueError, match="non-public address"):
            _fetch(BytesIO())

    redirect.iter_content.assert_not_called()
    redirect.close.assert_called_once()


def test_redirect_limit_closes_every_response(http_get):
    redirects = [_response(headers={"Location": "/again"}, status=302) for _ in range(10)]
    http_get.side_effect = redirects

    with pytest.raises(ValueError, match="Too many redirects"):
        _fetch(BytesIO())

    for response in redirects:
        response.close.assert_called_once()
        response.iter_content.assert_not_called()


def test_requests_does_not_consume_redirect_body_implicitly():
    response = requests.Response()
    response.status_code = 302
    response.url = "https://example.com/start"
    response.headers["Location"] = "http://localhost/"
    response.raw = MagicMock()
    response.raw.stream.side_effect = AssertionError("Redirect body must not be read")
    response.raw.read.side_effect = AssertionError("Redirect body must not be read")

    with (
        patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns,
        patch("requests.adapters.HTTPAdapter.send", return_value=response),
    ):
        dns.return_value = _mock_addrinfo("93.184.216.34")
        with pytest.raises(ValueError, match="Localhost"):
            _fetch(BytesIO())

    response.raw.close.assert_called_once()
    response.raw.stream.assert_not_called()
    response.raw.read.assert_not_called()
