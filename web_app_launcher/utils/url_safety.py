import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


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
    timeout: int = 10,
    max_redirects: int = 10,
) -> tuple[requests.Response, str]:
    """Fetch a public HTTP(S) URL, validating each redirect target against SSRF rules."""
    validate_public_http_url(url)
    current_url = url

    for _ in range(max_redirects):
        response = requests.get(
            current_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
        if response.status_code not in _REDIRECT_STATUS_CODES:
            response.raise_for_status()
            return response, current_url

        location = response.headers.get("Location")
        if not location:
            response.raise_for_status()
            return response, current_url

        current_url = urljoin(current_url, location)
        validate_public_http_url(current_url)

    raise ValueError(f"Too many redirects while fetching {url}")
