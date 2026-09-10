"""The `Connector` protocol: one shape for every account-backed
integration (calendar, mail, media server, energy provider, router).

`docs/plans/platform-connectors-design.md` section 3 specifies it. The
point is that a domain's *tools* never speak a vendor's API directly --
they speak to a `Connector`, which returns domain dataclasses, so one
`calendar_*` tool surface sits over CalDAV and Google and Microsoft
alike, and a test drives the whole domain through an in-memory fake of
the same protocol with no account and no network.

Three rules every connector obeys, enforced by convention and by the
tests each one ships:

- **Construction never raises.** A missing package, a missing
  credential, an unreachable host: none of these are errors at
  construction time. They surface through `probe()`, which is the
  health check the `capabilities` CLI reads -- so "why can't Sim reach
  my mail" is one command, not a stack trace at boot.
- **Credentials come from the vault (kernel/vault.py) or the scoped
  secret store, never from a tool argument, and never appear in a
  return value, a log, or an error string.** Each connector ships the
  `SECRET`-appears-nowhere test the vault established.
- **A rate limit and backoff live in the connector**, with a
  per-connector `Budget` (calls per window) in config; exhaustion is a
  clean refusal that says when, never an unbounded retry loop.

This module is dependency-free (stdlib + contracts only) so it can sit
in `contracts/` where every subsystem may import it, the same
placement the Ledger/Bus protocols already use.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ConnectorStatus:
    """What `Connector.probe()` returns: whether the connector can
    actually be used right now, and -- when it cannot -- exactly what is
    missing, phrased for a person ("set GOOGLE_CLIENT_ID and run
    `vault add google:me oauth2`", not "KeyError")."""

    ok: bool
    detail: str = ""
    # The packages / credential ids / env vars this connector needs but
    # does not have, so `capabilities` can list them without re-deriving.
    missing: tuple[str, ...] = ()


@runtime_checkable
class Connector(Protocol):
    """One account-backed integration. Methods beyond these are the
    domain's own (a calendar connector adds `events()`, a mail
    connector `search()`); the protocol only fixes the lifecycle every
    domain shares."""

    name: str                       # "google_calendar", "imap", "unifi"
    needs: tuple[str, ...]          # credential ids / env vars; any-of groups joined with "|"
    packages: tuple[str, ...]       # optional pip deps this connector imports lazily

    async def probe(self) -> ConnectorStatus:
        """Cheap and side-effect-free -- never a paid API call, never a
        real fetch. Import-check the packages, presence-check the
        credentials, and (only where free) a HEAD/whoami. Returns
        `ok=False` with `missing` naming what to set, never raises."""

    async def close(self) -> None:
        """Release any client/session. Idempotent; safe to call on a
        connector that never opened one."""


def missing_requirements(needs: tuple[str, ...], has: Mapping[str, bool]) -> tuple[str, ...]:
    """The subset of `needs` not satisfied by `has`. A `needs` entry may
    be an any-of group written `a|b|c` (satisfied if ANY of a/b/c is
    present) -- e.g. `"GEMINI_API_KEY|GOOGLE_API_KEY"`. Used by every
    connector's `probe()` so the any-of logic lives in one tested place
    rather than being re-implemented (subtly differently) per connector."""
    out = []
    for entry in needs:
        options = entry.split("|")
        if not any(has.get(opt, False) for opt in options):
            out.append(entry)
    return tuple(out)


def missing_packages(packages: tuple[str, ...]) -> tuple[str, ...]:
    """The optional packages a connector imports lazily that are not
    installed here. `importlib.util.find_spec` only, so a probe never
    pays a real import (some packages start threads or read config on
    import, which is exactly what a boot-time probe must not do)."""
    import importlib.util

    out = []
    for name in packages:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            out.append(name)
    return tuple(out)


class BudgetExhausted(RuntimeError):
    """The connector's rate budget is spent. The message says when the
    next call is allowed -- a refusal that names its own end is one a
    caller can schedule around; a bare 429 is one it retries against."""

    def __init__(self, name: str, *, limit: int, window_s: float, retry_after_s: float) -> None:
        self.name, self.limit, self.window_s, self.retry_after_s = name, limit, window_s, retry_after_s
        super().__init__(
            f"{name}: rate budget of {limit} calls per {window_s:.0f}s is spent; "
            f"try again in {max(retry_after_s, 0.0):.0f}s"
        )


@dataclass
class Budget:
    """A sliding-window call budget for one connector: `limit` calls per
    `window_s` seconds. Pure and clock-injected so a test can drive it
    without sleeping.

    `take()` records a call or raises `BudgetExhausted`; nothing here
    sleeps, retries, or backs off on its own. Backoff after a provider's
    own 429/503 is the connector's decision too, but it is bounded by
    `backoff_s(attempt)`: exponential from `base_backoff_s`, capped at
    `max_backoff_s`, never unbounded -- a refusal that says when beats a
    loop that never ends.
    """

    name: str
    limit: int = 60
    window_s: float = 3600.0
    base_backoff_s: float = 1.0
    max_backoff_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _calls: deque = field(default_factory=deque, repr=False)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()

    def remaining(self) -> int:
        self._trim(self.clock())
        return max(self.limit - len(self._calls), 0)

    def take(self) -> None:
        now = self.clock()
        self._trim(now)
        if self.limit <= 0 or len(self._calls) >= self.limit:
            retry_after = (self._calls[0] + self.window_s - now) if self._calls else self.window_s
            raise BudgetExhausted(self.name, limit=self.limit, window_s=self.window_s,
                                  retry_after_s=retry_after)
        self._calls.append(now)

    def backoff_s(self, attempt: int) -> float:
        """Seconds to wait before retry number `attempt` (1-based) after
        the provider itself pushed back. Capped, so a connector that
        honours it can never wait forever."""
        if attempt <= 0:
            return 0.0
        return min(self.base_backoff_s * (2 ** (attempt - 1)), self.max_backoff_s)


class FakeConnector:
    """The in-memory stand-in every domain's tests use -- and the model
    for each real connector's own `Fake<Name>`. Satisfies `Connector`;
    reports whatever the test configures; records its lifecycle so a
    test can assert `close()` was called exactly as expected."""

    def __init__(self, name: str = "fake", *, needs: tuple[str, ...] = (), packages: tuple[str, ...] = (),
                 ok: bool = True, detail: str = "fake connector", missing: tuple[str, ...] = ()) -> None:
        self.name = name
        self.needs = needs
        self.packages = packages
        self._status = ConnectorStatus(ok=ok, detail=detail, missing=missing)
        self.probes = 0
        self.closed = 0

    async def probe(self) -> ConnectorStatus:
        self.probes += 1
        return self._status

    async def close(self) -> None:
        self.closed += 1


__all__ = [
    "Budget", "BudgetExhausted", "Connector", "ConnectorStatus", "FakeConnector",
    "missing_packages", "missing_requirements",
]
