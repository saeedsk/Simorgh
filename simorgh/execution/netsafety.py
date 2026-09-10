"""The SSRF guard shared by every tool that opens an outbound URL
(`web_fetch`, `render_page`): http(s) only, and unless explicitly
allowed, the resolved address must not land in a private/loopback/
link-local/reserved/multicast/unspecified range. Split out from
`tools.py` so a second URL-opening tool doesn't have to import from it
and risk a circular import.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class FetchRefused(Exception):
    """No request was made (or its result is discarded): a disallowed
    scheme, a hostname that resolves to a private/internal address, a
    DNS failure, or an exhausted rate limit."""


def validate_public_http_url(url: str, *, allow_private: bool, resolver=None) -> None:
    """Raises `FetchRefused`, never returns a boolean, so a caller can't
    accidentally ignore a refusal."""
    resolver = resolver or socket.getaddrinfo
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchRefused(f"refusing {url!r}: only http/https URLs are allowed")
    if not parsed.hostname:
        raise FetchRefused(f"refusing {url!r}: no hostname")
    if allow_private:
        return
    try:
        addrinfo = resolver(parsed.hostname, None)
    except socket.gaierror as exc:
        raise FetchRefused(f"refusing {url!r}: could not resolve host: {exc!r}") from exc
    for entry in addrinfo:
        ip = ipaddress.ip_address(entry[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise FetchRefused(f"refusing {url!r}: resolves to a private/internal address ({ip}) -- SSRF protection")


def wait_note(seconds: float) -> str:
    """How long until a rate-limited call is allowed again.

    Shared by `web_fetch` and `web_search` because they had separate
    copies and the copies disagreed: the search one counted whole
    minutes, so a ten-second wait printed "the next one is allowed in
    about 0 minutes" -- a refusal that contradicts itself and invites
    the immediate retry the note exists to prevent (observer,
    2026-09-10, the day the note was added).
    """
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"The next one is allowed in about {seconds:.0f}s."
    return f"The next one is allowed in about {seconds / 60:.0f} minutes."
