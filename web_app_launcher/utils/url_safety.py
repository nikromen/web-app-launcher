import ipaddress
import socket
from typing import BinaryIO
from urllib.parse import urljoin, urlparse

import requests

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class _NoRedirectSession(requests.Session):
    def get_redirect_target(self, resp: requests.Response) -> None:
        # Requests otherwise consumes redirect bodies while preparing Response.next,
        # even with allow_redirects=False and stream=True. We handle redirects below.
        return None


def validate_public_http_url(url: str) -> None:
    """Reject non-HTTP(S) URLs and hosts that resolve to private/loopback addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")

    hostname = parsed.hostname
    if hostname == "localhost":
        raise ValueError("Localhost URLs are not allowed")

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname: {hostname}") from exc

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"URL resolves to a non-public address: {ip}")


def fetch_public_http_response(
    url: str,
    *,
    headers: dict[str, str],
    destination: BinaryIO,
    max_bytes: int,
    timeout: int = 10,
    max_redirects: int = 10,
) -> tuple[str, str]:
    """Write a bounded, decompressed body and return its content type and final URL."""
    validate_public_http_url(url)
    current_url = url

    for _ in range(max_redirects):
        with _NoRedirectSession() as session:
            response = session.get(
                current_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )

            try:
                location = response.headers.get("Location")
                if response.status_code in _REDIRECT_STATUS_CODES and location:
                    current_url = urljoin(current_url, location)
                    validate_public_http_url(current_url)
                    continue

                response.raise_for_status()

                try:
                    content_length = int(response.headers.get("Content-Length", ""))
                except ValueError:
                    content_length = 0
                if content_length > max_bytes:
                    raise ValueError("HTTP response exceeds size limit")

                size = 0
                # iter_content decodes Content-Encoding, so compressed bodies obey the same limit.
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("HTTP response exceeds size limit")
                    destination.write(chunk)

                return response.headers.get("Content-Type", ""), current_url
            finally:
                response.close()

    raise ValueError(f"Too many redirects while fetching {url}")
