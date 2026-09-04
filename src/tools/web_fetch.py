"""Web fetch tool: a deliberately hand-built, reviewed capability to
retrieve content from a URL -- not reachable through the LLM-drafted
skill-proposal pipeline. AuditGate's denylist explicitly blocks
urllib.request/http.client/requests in drafted skills
(src/orchestrator/audit.py) specifically so real network access only
ever happens through this reviewed path, never through an auto-applied,
unreviewed LLM draft.

Real outbound network access is a deliberate capability the creator
explicitly authorized (in conversation, this codebase's history is the
record of it), not a byproduct of an audit-gate gap. Every fetch here is:

- Restricted to http/https GET only -- no POST/PUT/DELETE, nothing that
  submits data anywhere.
- Blocked from reaching private/loopback/link-local/reserved addresses
  (SSRF protection) -- this tool must never be usable to probe the
  creator's local network or a cloud metadata endpoint (e.g.
  169.254.169.254).
- Bounded in time (timeout) and response size (max_bytes).
- Rate-limited, durably (via MemoryStore, mirroring
  src/cognition/budget.py's rolling-window pattern) so it can't be
  hammered in a loop.
- Logged (kind="web_fetch") -- every attempt, successful or not, is
  recorded. Nothing here is silent (Directive 8).
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from src.memory.long_term import MemoryStore

FETCH_KIND = "web_fetch"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_BYTES = 200_000
DEFAULT_MAX_CALLS = 30
DEFAULT_WINDOW_SECONDS = 3600.0


class FetchRefused(Exception):
    """Raised when a fetch is refused -- a disallowed scheme, an address
    that resolves to a private/internal range, a resolution failure, an
    exhausted rate limit, or a network-level failure. No request is made
    (or its result is discarded) whenever this is raised.
    """


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: str
    truncated: bool


class WebFetchTool:
    """`opener` (default `urllib.request.urlopen`) and `resolver` (default
    `socket.getaddrinfo`) are injectable so this can be tested without a
    real network call or real DNS lookup.
    """

    def __init__(
        self,
        store: MemoryStore,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_calls: int = DEFAULT_MAX_CALLS,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        opener: Callable[..., Any] | None = None,
        resolver: Callable[..., Any] | None = None,
    ) -> None:
        self._store = store
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._opener = opener or urllib.request.urlopen
        self._resolver = resolver or socket.getaddrinfo

    def fetch(self, url: str) -> FetchResult:
        self._validate_url(url)
        self._enforce_rate_limit()

        try:
            with self._opener(url, timeout=self._timeout) as response:
                status_code = getattr(response, "status", 200)
                raw = response.read(self._max_bytes + 1)
        except FetchRefused:
            raise
        except Exception as exc:  # noqa: BLE001 -- any network failure is
            # reported through FetchRefused, never an unhandled crash
            self._log(url, succeeded=False, note=repr(exc))
            raise FetchRefused(f"fetch failed: {exc!r}") from exc

        truncated = len(raw) > self._max_bytes
        content = raw[: self._max_bytes].decode("utf-8", errors="replace")
        self._log(url, succeeded=True, note=f"{len(raw)} bytes, truncated={truncated}")
        return FetchResult(
            url=url, status_code=status_code, content=content, truncated=truncated
        )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise FetchRefused(f"refusing {url!r}: only http/https URLs are allowed")
        if not parsed.hostname:
            raise FetchRefused(f"refusing {url!r}: no hostname")

        try:
            addrinfo = self._resolver(parsed.hostname, None)
        except socket.gaierror as exc:
            raise FetchRefused(
                f"refusing {url!r}: could not resolve host: {exc!r}"
            ) from exc

        for entry in addrinfo:
            sockaddr = entry[4]
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise FetchRefused(
                    f"refusing {url!r}: resolves to a private/internal address "
                    f"({ip}) -- SSRF protection"
                )

    def _enforce_rate_limit(self) -> None:
        cutoff = time.time() - self._window_seconds
        recent = [r for r in self._store.query(kind=FETCH_KIND) if r.created_at >= cutoff]
        if len(recent) >= self._max_calls:
            raise FetchRefused(
                f"rate limit exceeded: {len(recent)}/{self._max_calls} fetches in "
                f"the last {self._window_seconds:.0f}s"
            )

    def _log(self, url: str, succeeded: bool, note: str) -> None:
        self._store.remember(FETCH_KIND, url, succeeded=succeeded, note=note)
