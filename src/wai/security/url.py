"""URL validation helpers for SSRF prevention."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def is_private_host(host: str) -> bool:
    """Return True when host resolves to a private, loopback, or link-local address."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return host.lower() in ("localhost", "127.0.0.1", "::1")


def validate_http_url(url: str, *, allow_private: bool = False) -> str:
    """Validate an HTTP(S) URL. Returns normalized URL or raises ValueError."""
    if not url or not url.strip():
        raise ValueError("url is required")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url must use http or https")
    if not parsed.hostname:
        raise ValueError("url must include a host")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1") and not allow_private:
        raise ValueError("url must use https (http is only allowed for localhost)")
    if not allow_private and is_private_host(parsed.hostname):
        raise ValueError("url must not point to a private address")
    return url.strip()
