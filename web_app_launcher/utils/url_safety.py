import ipaddress
import re
import socket
import ssl
import unicodedata
from dataclasses import dataclass
from http import HTTPStatus
from http.client import HTTP_PORT, HTTPS_PORT
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

import urllib3
from urllib3.util import parse_url

DEFAULT_HTTP_TIMEOUT_SECONDS = 10
MAX_HTTP_REDIRECTS = 10
HTTP_READ_CHUNK_BYTES = 64 * 1024
MAX_TCP_PORT = 65535
MAX_DNS_NAME_LENGTH = 253
MAX_DNS_LABEL_LENGTH = 63
_REDIRECT_STATUS_CODES = {
    HTTPStatus.MOVED_PERMANENTLY,
    HTTPStatus.FOUND,
    HTTPStatus.SEE_OTHER,
    HTTPStatus.TEMPORARY_REDIRECT,
    HTTPStatus.PERMANENT_REDIRECT,
}
# A label has one leading and one trailing alphanumeric character.
_HOST_LABEL = re.compile(
    rf"[a-z0-9](?:[a-z0-9-]{{0,{MAX_DNS_LABEL_LENGTH - 2}}}[a-z0-9])?",
    re.I,
)


@dataclass(frozen=True)
class _PublicHttpTarget:
    scheme: str
    hostname: str
    port: int
    request_uri: str
    addresses: tuple[str, ...]

    @property
    def host_header(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        default_port = HTTPS_PORT if self.scheme == "https" else HTTP_PORT
        return host if self.port == default_port else f"{host}:{self.port}"


def _public_ip(value: str) -> str:
    if "%" in value:
        raise ValueError("IPv6 zone identifiers are not allowed")

    address = ipaddress.ip_address(value)
    checked = address
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        checked = address.ipv4_mapped
    if not checked.is_global or checked.is_multicast:
        raise ValueError(f"URL resolves to a non-public address: {address}")

    return str(address)


def _validate_url_characters(url: str) -> None:
    if any(unicodedata.category(character) == "Cc" for character in url):
        raise ValueError("Control characters are not allowed in URLs")


def validate_public_http_url(url: str) -> _PublicHttpTarget:
    """Resolve and validate a downloader target, retaining only approved numeric IPs."""
    _validate_url_characters(url)

    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    if "%" in parsed.hostname:
        raise ValueError("IPv6 zone identifiers and escaped hostnames are not allowed")
    if parsed.netloc.startswith("[") and not re.fullmatch(r"\[[^\]]+\](?::[0-9]+)?", parsed.netloc):
        raise ValueError("Invalid IPv6 authority")
    if parsed.netloc.endswith(":"):
        raise ValueError("URL must include a valid port")

    port = (
        parsed.port
        if parsed.port is not None
        else (HTTPS_PORT if parsed.scheme == "https" else HTTP_PORT)
    )
    if not 1 <= port <= MAX_TCP_PORT:
        raise ValueError("URL must include a valid port")

    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        if parsed.netloc.startswith("["):
            raise ValueError("Bracketed hostname must be an IPv6 address") from None

        domain = hostname.removesuffix(".")
        if len(domain) > MAX_DNS_NAME_LENGTH or not all(
            _HOST_LABEL.fullmatch(label) for label in domain.split(".")
        ):
            raise ValueError("URL must include a valid hostname") from None

        try:
            addr_infos = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve hostname: {hostname}") from exc

        resolved = []
        for _family, _socket_type, _protocol, _canonical_name, socket_address in addr_infos:
            address = socket_address[0]
            if not isinstance(address, str):
                raise ValueError("Invalid DNS address") from None
            resolved.append(_public_ip(address))

        addresses = tuple(dict.fromkeys(resolved))
        if not addresses:
            raise ValueError(f"No addresses for hostname: {hostname}") from None
    else:
        addresses = (_public_ip(str(literal)),)

    return _PublicHttpTarget(parsed.scheme, hostname, port, parse_url(url).request_uri, addresses)


def _connection_pool(target: _PublicHttpTarget, timeout: int) -> urllib3.HTTPConnectionPool:
    # A numeric pool host binds the connection to validation's result. The original
    # hostname is used only for HTTP routing and TLS identity, never for connection DNS.
    address = target.addresses[0]
    socket_timeout = urllib3.Timeout(connect=timeout, read=timeout)
    if target.scheme == "https":
        return urllib3.HTTPSConnectionPool(
            address,
            port=target.port,
            timeout=socket_timeout,
            server_hostname=target.hostname,
            assert_hostname=target.hostname,
            cert_reqs=ssl.CERT_REQUIRED,
        )

    return urllib3.HTTPConnectionPool(address, port=target.port, timeout=socket_timeout)


def fetch_public_http_response(
    url: str,
    *,
    headers: dict[str, str],
    destination: BinaryIO,
    max_bytes: int,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_redirects: int = MAX_HTTP_REDIRECTS,
) -> tuple[str, str]:
    """Write a bounded, decompressed body and return its content type and final URL."""
    current_url = url

    for _ in range(max_redirects):
        target = validate_public_http_url(current_url)
        request_headers = {key: value for key, value in headers.items() if key.lower() != "host"}
        request_headers["Host"] = target.host_header

        # Direct pools do not consult environment proxy settings.
        with _connection_pool(target, timeout) as pool:
            response = pool.urlopen(
                "GET",
                target.request_uri,
                headers=request_headers,
                redirect=False,
                retries=False,
                assert_same_host=False,
                preload_content=False,
                decode_content=True,
            )

            try:
                location = response.headers.get("Location")
                if response.status in _REDIRECT_STATUS_CODES and location:
                    _validate_url_characters(location)
                    current_url = urljoin(current_url, location)
                    continue

                if response.status >= HTTPStatus.BAD_REQUEST:
                    raise urllib3.exceptions.HTTPError(f"HTTP status {response.status}")

                try:
                    content_length = int(response.headers.get("Content-Length", ""))
                except ValueError:
                    content_length = 0
                if content_length > max_bytes:
                    raise ValueError("HTTP response exceeds size limit")

                size = 0
                for chunk in response.stream(amt=HTTP_READ_CHUNK_BYTES, decode_content=True):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("HTTP response exceeds size limit")
                    destination.write(chunk)

                return response.headers.get("Content-Type", ""), current_url
            finally:
                # Discard unread bodies, including redirects, instead of draining them.
                response.close()
                response.release_conn()

    raise ValueError(f"Too many redirects while fetching {url}")
