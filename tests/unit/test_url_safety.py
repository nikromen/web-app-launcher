import gzip
import socket
import ssl
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
import urllib3
from urllib3.response import HTTPResponse

from web_app_launcher.utils.url_safety import fetch_public_http_response, validate_public_http_url


def _mock_addrinfo(*addresses: str) -> list[tuple]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 443),
        )
        for address in addresses
    ]


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_literals_do_not_require_dns(address):
    host = f"[{address}]" if ":" in address else address

    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        target = validate_public_http_url(f"https://{host}/")

    assert target.addresses
    dns.assert_not_called()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fd00::1",
        "ff0e::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
        "::ffff:100.64.0.1",
        "::ffff:224.0.0.1",
    ],
)
def test_non_public_literals_are_rejected(address):
    host = f"[{address}]" if ":" in address else address

    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        with pytest.raises(ValueError, match="non-public address"):
            validate_public_http_url(f"http://{host}/")

    dns.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "https:///path",
        "https://",
        "https://user:password@example.com",
        "https://@example.com",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:bad",
        "https://example.com:",
        "https://[fe80::1%eth0]/",
        "https://[fe80::1%25eth0]/",
        "https://bad host/",
        "https://bad_host/",
        "https://-host.example/",
        "https://a..example/",
        "https://example.com/\npath",
        "https://example.com\t/",
        "\x00https://example.com/",
        "https://example.com/\x7f",
        "https://[invalid]/",
        "https://[v1.example]/",
        "https://[2606:4700:4700::1111]suffix/",
    ],
)
def test_invalid_urls_rejected_before_dns(url):
    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        with pytest.raises(ValueError):
            validate_public_http_url(url)

    dns.assert_not_called()


@pytest.mark.parametrize(
    "addresses", [("8.8.8.8",), ("2606:4700:4700::1111",), ("8.8.8.8", "2606:4700:4700::1111")]
)
def test_dns_accepts_public_tcp_addresses(addresses):
    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        dns.return_value = _mock_addrinfo(*addresses)
        target = validate_public_http_url("https://example.com:8443/path")

    assert target.addresses == addresses
    dns.assert_called_once_with(
        "example.com",
        8443,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )


@pytest.mark.parametrize("addresses", [(), ("8.8.8.8", "10.0.0.1"), ("::1", "8.8.8.8")])
def test_dns_rejects_empty_or_mixed_answers(addresses):
    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        dns.return_value = _mock_addrinfo(*addresses)

        with pytest.raises(ValueError):
            validate_public_http_url("https://example.com")


def test_dns_failure_is_rejected():
    with patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns:
        dns.side_effect = socket.gaierror("No answer")

        with pytest.raises(ValueError, match="Could not resolve"):
            validate_public_http_url("https://example.com")


@pytest.fixture
def transport():
    with (
        patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns,
        patch("urllib3.connectionpool.HTTPConnectionPool.urlopen", autospec=True) as send,
    ):
        dns.return_value = _mock_addrinfo("93.184.216.34")
        send.return_value = _response([b"ok"])

        yield SimpleNamespace(dns=dns, send=send)


def _response(chunks=(), headers=None, status=200):
    response = MagicMock()
    response.status = status
    response.headers = headers or {}
    response.stream.return_value = iter(chunks)
    return response


def _fetch(destination, max_bytes=8, url="https://example.com/start", headers=None):
    return fetch_public_http_response(
        url, headers=headers or {}, destination=destination, max_bytes=max_bytes
    )


def _assert_closed(transport, response):
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
    for call in transport.send.call_args_list:
        assert call.args[0].pool is None


def test_bounded_response_success(transport):
    response = _response([b"1234", b"5678"], {"Content-Type": "text/html"})
    transport.send.return_value = response
    destination = BytesIO()

    assert _fetch(destination) == ("text/html", "https://example.com/start")
    assert destination.getvalue() == b"12345678"
    response.stream.assert_called_once_with(amt=64 * 1024, decode_content=True)
    _assert_closed(transport, response)


@pytest.mark.parametrize("length", [None, "9", "1", "invalid", "-1"])
def test_response_size_limit_with_untrusted_content_length(transport, length):
    headers = {} if length is None else {"Content-Length": length}
    response = _response([b"1234", b"56789", b"unread"], headers)
    transport.send.return_value = response
    destination = BytesIO()

    with pytest.raises(ValueError, match="size limit"):
        _fetch(destination)

    assert len(destination.getvalue()) <= 8
    if length == "9":
        response.stream.assert_not_called()
    _assert_closed(transport, response)


def test_limit_counts_decompressed_bytes(transport):
    compressed = gzip.compress(b"a" * 100)
    response = HTTPResponse(
        body=BytesIO(compressed),
        headers={"Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
        preload_content=False,
    )
    transport.send.return_value = response

    with patch.object(response, "close", wraps=response.close) as close:
        with pytest.raises(ValueError, match="size limit"):
            _fetch(BytesIO(), max_bytes=50)

        close.assert_called_once()

    assert transport.send.call_args.args[0].pool is None


@pytest.mark.parametrize("failure", ["status", "read", "write"])
def test_response_closed_on_status_read_or_write_error(transport, failure):
    response = _response([b"body"], status=500 if failure == "status" else 200)
    destination = BytesIO()
    if failure == "read":
        response.stream.side_effect = urllib3.exceptions.ProtocolError("Read failed")
    elif failure == "write":
        destination = MagicMock()
        destination.write.side_effect = OSError("Write failed")
    transport.send.return_value = response

    with pytest.raises((urllib3.exceptions.HTTPError, OSError)):
        _fetch(destination)

    _assert_closed(transport, response)


def test_failed_connection_closes_pool_without_retry(transport):
    transport.send.side_effect = urllib3.exceptions.SSLError("Certificate mismatch")

    with pytest.raises(urllib3.exceptions.SSLError):
        _fetch(BytesIO())

    transport.send.assert_called_once()
    assert transport.send.call_args.args[0].pool is None
    assert transport.send.call_args.kwargs["retries"] is False


@pytest.mark.parametrize("location", ["/final", "https://other.example/final"])
def test_follows_redirect_with_fresh_validation_without_reading_body(transport, location):
    redirect = _response(headers={"Location": location, "Content-Length": "99999"}, status=302)
    final = _response([b"ok"])
    transport.send.side_effect = [redirect, final]
    transport.dns.side_effect = [_mock_addrinfo("8.8.8.8"), _mock_addrinfo("1.1.1.1")]

    expected_url = (
        "https://example.com/final" if location == "/final" else "https://other.example/final"
    )
    assert _fetch(BytesIO()) == ("", expected_url)

    assert [call.args[0].host for call in transport.send.call_args_list] == ["8.8.8.8", "1.1.1.1"]
    assert transport.dns.call_count == 2
    redirect.stream.assert_not_called()
    _assert_closed(transport, redirect)
    _assert_closed(transport, final)


@pytest.mark.parametrize("location", ["http://10.0.0.1/", "https://internal.example/"])
def test_redirect_to_internal_network_is_rejected_before_connection(transport, location):
    redirect = _response(headers={"Location": location}, status=302)
    transport.send.return_value = redirect
    transport.dns.side_effect = [_mock_addrinfo("93.184.216.34"), _mock_addrinfo("10.0.0.1")]

    with pytest.raises(ValueError, match="non-public address"):
        _fetch(BytesIO())

    transport.send.assert_called_once()
    redirect.stream.assert_not_called()
    _assert_closed(transport, redirect)


def test_redirect_limit_closes_every_response(transport):
    redirects = [_response(headers={"Location": "/again"}, status=302) for _ in range(10)]
    transport.send.side_effect = redirects

    with pytest.raises(ValueError, match="Too many redirects"):
        _fetch(BytesIO())

    assert transport.send.call_count == 10
    for response in redirects:
        response.stream.assert_not_called()
        _assert_closed(transport, response)


@pytest.mark.parametrize(
    "url, host, sni, port",
    [
        ("https://example.com/path?q=1#fragment", "example.com", "example.com", 443),
        ("https://example.com:8443/path?q=1#fragment", "example.com:8443", "example.com", 8443),
        ("https://bücher.example/path?q=1", "xn--bcher-kva.example", "xn--bcher-kva.example", 443),
        (
            "https://[2606:4700:4700::1111]:8443/path?q=1",
            "[2606:4700:4700::1111]:8443",
            "2606:4700:4700::1111",
            8443,
        ),
    ],
)
def test_https_uses_original_identity_and_verified_ip(transport, url, host, sni, port):
    _fetch(BytesIO(), url=url, headers={"host": "untrusted.example", "User-Agent": "test"})

    call = transport.send.call_args
    pool = call.args[0]
    assert isinstance(pool, urllib3.HTTPSConnectionPool)
    assert pool.host == (sni if ":" in sni else "93.184.216.34")
    assert pool.port == port
    assert pool.conn_kw["server_hostname"] == sni
    assert pool.assert_hostname == sni
    assert pool.cert_reqs == ssl.CERT_REQUIRED
    assert pool.timeout.connect_timeout == 10
    assert pool.timeout.read_timeout == 10
    assert call.args[1:] == ("GET", "/path?q=1")
    assert call.kwargs == {
        "headers": {"Host": host, "User-Agent": "test"},
        "redirect": False,
        "retries": False,
        "assert_same_host": False,
        "preload_content": False,
        "decode_content": True,
    }


@pytest.mark.parametrize(
    "url, expected_host",
    [
        ("http://example.com:8080/start", "example.com:8080"),
        ("http://[2606:4700:4700::1111]/start", "[2606:4700:4700::1111]"),
    ],
)
def test_http_host_header(transport, url, expected_host):
    _fetch(BytesIO(), url=url)

    call = transport.send.call_args
    assert not isinstance(call.args[0], urllib3.HTTPSConnectionPool)
    assert call.kwargs["headers"]["Host"] == expected_host


def test_rebinding_cannot_change_connection_address():
    connection = MagicMock()
    connection.makefile.return_value = BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with (
        patch("web_app_launcher.utils.url_safety.socket.getaddrinfo") as dns,
        patch("urllib3.util.connection.create_connection", return_value=connection) as connect,
    ):
        dns.side_effect = [_mock_addrinfo("93.184.216.34"), _mock_addrinfo("127.0.0.1")]
        destination = BytesIO()

        assert _fetch(destination, url="http://example.com:8080/start") == (
            "",
            "http://example.com:8080/start",
        )

    assert destination.getvalue() == b"ok"
    dns.assert_called_once()
    assert connect.call_args.args[0] == ("93.184.216.34", 8080)
    connection.close.assert_called_once()


def test_proxy_environment_is_ignored_only_by_downloader(transport, monkeypatch):
    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(variable, "http://proxy.example:8123")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")

    _fetch(BytesIO())

    pool = transport.send.call_args.args[0]
    assert pool.proxy is None
    assert pool.host == "93.184.216.34"
    with requests.Session() as session:
        settings = session.merge_environment_settings("https://example.com", {}, True, True, None)

    assert settings["proxies"]["https"] == "http://proxy.example:8123"


@pytest.mark.parametrize("location", ["/pa\nth", "https://other.example/\tpath", "/\x85path"])
def test_redirect_controls_are_rejected_before_urljoin_can_strip_them(transport, location):
    redirect = _response(headers={"Location": location}, status=302)
    transport.send.return_value = redirect

    with pytest.raises(ValueError, match="Control characters"):
        _fetch(BytesIO())

    transport.send.assert_called_once()
    transport.dns.assert_called_once()
    redirect.stream.assert_not_called()
    _assert_closed(transport, redirect)


@pytest.mark.parametrize("addresses", [(), ("8.8.8.8", "100.64.0.1")])
def test_rejected_dns_result_never_opens_a_connection(transport, addresses):
    transport.dns.return_value = _mock_addrinfo(*addresses)

    with pytest.raises(ValueError):
        _fetch(BytesIO())

    transport.send.assert_not_called()
