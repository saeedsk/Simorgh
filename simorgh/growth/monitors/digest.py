"""Monitors, alerts, and the daily digest -- written once, here, because
five designs had each specified their own.

`home-automation-design.md` wanted a daily digest and severity-routed
alerts. `network-discovery-design.md` wanted the same. So did energy
("solar underperforming"), security ("a certificate expires in 20
days"), and pim ("sync failed, re-authenticate"). Five copies of one
mechanism is five places for the interesting half of it -- the part
that decides what is worth waking a person for -- to be got subtly
wrong.

`platform-connectors-design.md` section 6 generalises it. This module
is the pure core of that: no bus, no `notify`, no I/O, a clock passed
in. Reflection's `Service` runs it on `system.tick.idle` and turns the
`Delivery` objects it returns into actual sends. That split is what
lets the rules below be tested against a `FakeClock` in milliseconds
rather than against a running system at three in the morning.

The rules, and why each one exists:

- **An alert is idempotent per `key`.** A monitor that notices a
  problem does so on every check while the problem lasts -- a
  certificate does not stop expiring because it has been mentioned.
  Only the *transition* is news. A monitor may therefore be dumb and
  stateless, reporting everything it sees each time, which is the only
  kind of monitor that is easy to write correctly.
- **Clearing is automatic.** An alert the monitor stops reporting is
  resolved. Requiring an explicit `clear()` means every monitor grows a
  second code path that only runs on the good day, and that path is
  never the one anybody tests.
- **A reopened alert is not a new alert.** Something that breaks,
  gets fixed, and breaks again is a worse fact than something that
  broke once, and the count travels with the delivery so a digest can
  say so (domain 4 calls this `regressed`).
- **`warn` is rate-limited per monitor.** The failure mode of a
  notifier is not silence, it is twenty messages in a minute, after
  which a person stops reading any of them.
- **Quiet hours hold back `warn`, never `critical`.** A quiet-hours
  rule that can swallow a critical alert is a bug with a config key in
  front of it. If `critical` is not worth waking someone for, the
  monitor has the severity wrong -- fix it there, not here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Literal, Protocol, runtime_checkable

from simorgh.contracts.timewindow import in_quiet_hours, parse_quiet_hours

Severity = Literal["info", "warn", "critical"]

#: Ordered weakest-first, so severities compare.
SEVERITIES: tuple[Severity, ...] = ("info", "warn", "critical")

#: Where a delivery is meant to go. `digest` is the daily summary;
#: `notify` is the `notify` tool (a person, now); `announce` is the
#: house speaking out loud, which only `critical` ever earns.
Channel = Literal["digest", "notify", "announce"]


@dataclass(frozen=True)
class Alert:
    """One thing a monitor noticed.

    `key` is the identity of the *problem*, not of the observation:
    two checks that find the same expiring certificate must produce the
    same key or the alert will be reported twice. Include the asset in
    it (`"cert:ha.local"`, not `"cert_expiring"`).
    """

    monitor: str
    severity: Severity
    key: str
    message: str
    #: The thing this is about (an entity id, a host, a mailbox), for a
    #: rule or a digest that wants to group by it. Never required.
    entity: str = ""
    #: Free-form supporting detail for the digest and the ledger. Keep
    #: it small and keep secrets out of it -- this is written down.
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}; one of {SEVERITIES}")
        if not self.key:
            raise ValueError("an alert needs a key: it is what makes it idempotent")

    @property
    def ident(self) -> tuple[str, str]:
        return (self.monitor, self.key)


@runtime_checkable
class Monitor(Protocol):
    """Something that looks at one thing on a schedule.

    `check` is called no more often than `interval_s` and must be cheap,
    because the whole point is that it runs unattended forever. It
    returns every problem it can currently see; saying the same thing
    twice is free (the router dedupes) and forgetting to say it is how
    an alert silently clears.
    """

    name: str
    interval_s: float

    async def check(self, now: float) -> list[Alert]:
        ...


@dataclass(frozen=True)
class Delivery:
    """One thing to actually do about an alert. Reflection's Service
    turns these into sends; nothing in this module performs I/O."""

    alert: Alert
    channel: Channel
    #: Why this went where it went, in words -- so a person asking "why
    #: didn't I hear about this" gets an answer instead of a shrug.
    reason: str
    #: 0 the first time this key opens, 1+ each time it opens again
    #: after having been resolved.
    reopened: int = 0


@dataclass
class _Open:
    alert: Alert
    opened_at: float
    reopened: int


class AlertRouter:
    """Holds what is currently wrong, and decides what that means.

    The state here is small on purpose -- open alerts by identity, and
    when each monitor last sent a `warn`. It is rebuildable from a
    single round of checks, so losing it across a restart costs at most
    one repeated notification, never a missed one.
    """

    def __init__(self, *, clock=time.time, warn_window_s: float = 3600.0,
                 quiet_hours: str = "", localtime=time.localtime,
                 announce_enabled: bool = False) -> None:
        self._clock = clock
        self._warn_window_s = warn_window_s
        self._quiet = parse_quiet_hours(quiet_hours)
        self._localtime = localtime
        self._announce_enabled = announce_enabled
        self._open: dict[tuple[str, str], _Open] = {}
        self._last_warn: dict[str, float] = {}
        self._suppressed_warns: dict[str, int] = {}
        # How many times each identity has been resolved. An alert that
        # comes back after being fixed is a worse fact than one that
        # broke once, and this is what lets a delivery say so.
        self._resolved_count: dict[tuple[str, str], int] = {}

    # -- state ---------------------------------------------------------------

    @property
    def open_alerts(self) -> list[Alert]:
        return [entry.alert for entry in self._open.values()]

    def open_for(self, monitor: str) -> list[Alert]:
        return [e.alert for k, e in self._open.items() if k[0] == monitor]

    def clear(self, monitor: str, key: str) -> Alert | None:
        """Resolve one alert by hand. Automatic clearing covers the
        normal case; this is for the human act of "yes, I fixed that"
        (domain 4's `sec_accept`)."""
        entry = self._open.pop((monitor, key), None)
        return entry.alert if entry else None

    # -- the decision --------------------------------------------------------

    def observe(self, monitor: str, alerts: Iterable[Alert]) -> tuple[list[Delivery], list[Alert]]:
        """Take one monitor's complete current view.

        Returns `(deliveries, resolved)` -- what to send now, and the
        alerts that have stopped being true since the last look. A
        monitor that reports nothing therefore clears everything it had
        open, which is what makes "the problem went away" a thing the
        system notices rather than a thing it never mentions again.
        """
        now = self._clock()
        current: dict[tuple[str, str], Alert] = {}
        deliveries: list[Delivery] = []

        for alert in alerts:
            if alert.monitor != monitor:
                raise ValueError(
                    f"monitor {monitor!r} reported an alert attributed to {alert.monitor!r}")
            current[alert.ident] = alert

        for ident, alert in current.items():
            existing = self._open.get(ident)
            if existing is not None:
                # Already known. Keep the newest wording (a countdown
                # alert's message changes while its key does not), but
                # say nothing: the transition is the news.
                existing.alert = alert
                continue
            reopened = self._resolved_count.get(ident, 0)
            self._open[ident] = _Open(alert=alert, opened_at=now, reopened=reopened)
            deliveries.append(self._route(alert, now, reopened))

        resolved: list[Alert] = []
        for ident in [k for k in self._open if k[0] == monitor and k not in current]:
            entry = self._open.pop(ident)
            resolved.append(entry.alert)
            self._resolved_count[ident] = entry.reopened + 1

        return deliveries, resolved

    def _route(self, alert: Alert, now: float, reopened: int) -> Delivery:
        if alert.severity == "info":
            return Delivery(alert, "digest", "info alerts are collected into the digest", reopened)

        hour = self._localtime(now).tm_hour
        quiet = in_quiet_hours(hour, self._quiet)

        if alert.severity == "critical":
            # Deliberately not subject to quiet hours or the rate limit.
            # A `critical` that can be held back is not critical, and a
            # config key that can swallow one is a bug with a name.
            channel: Channel = "announce" if self._announce_enabled else "notify"
            return Delivery(alert, channel, "critical alerts always go out immediately", reopened)

        if quiet:
            return Delivery(alert, "digest",
                            f"quiet hours ({self._quiet[0]:02d}:00-{self._quiet[1]:02d}:00): "
                            "held for the digest", reopened)

        last = self._last_warn.get(alert.monitor)
        if last is not None and now - last < self._warn_window_s:
            self._suppressed_warns[alert.monitor] = self._suppressed_warns.get(alert.monitor, 0) + 1
            wait = self._warn_window_s - (now - last)
            return Delivery(alert, "digest",
                            f"{alert.monitor} already sent a warning {now - last:.0f}s ago "
                            f"(one per {self._warn_window_s:.0f}s); held for the digest, "
                            f"next warning allowed in {wait:.0f}s", reopened)

        self._last_warn[alert.monitor] = now
        return Delivery(alert, "notify", "first warning from this monitor in the window", reopened)

    @property
    def suppressed_warnings(self) -> dict[str, int]:
        """How many warnings the rate limit held back, per monitor. The
        digest says so -- a limit that silently eats alerts is
        indistinguishable from a monitor that stopped working."""
        return dict(self._suppressed_warns)

    def take_suppressed(self) -> dict[str, int]:
        counts, self._suppressed_warns = dict(self._suppressed_warns), {}
        return counts


class MonitorRegistry:
    """Every monitor any subsystem registered, run when due.

    A monitor that raises is a failed monitor, never a failed tick: the
    subsystem whose job is noticing problems must not be taken down by
    one of them.
    """

    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._monitors: dict[str, Monitor] = {}
        self._last_run: dict[str, float] = {}
        self.failures: dict[str, str] = {}

    def register(self, monitor: Monitor) -> None:
        if monitor.name in self._monitors:
            raise ValueError(f"monitor already registered: {monitor.name}")
        self._monitors[monitor.name] = monitor

    def unregister(self, name: str) -> None:
        self._monitors.pop(name, None)
        self._last_run.pop(name, None)
        self.failures.pop(name, None)

    @property
    def names(self) -> list[str]:
        return sorted(self._monitors)

    def due(self, now: float | None = None) -> list[Monitor]:
        now = self._clock() if now is None else now
        out = []
        for name, monitor in self._monitors.items():
            last = self._last_run.get(name)
            if last is None or now - last >= monitor.interval_s:
                out.append(monitor)
        return out

    async def run_due(self, router: AlertRouter, now: float | None = None
                      ) -> tuple[list[Delivery], list[Alert]]:
        """Check every due monitor and route what they found."""
        now = self._clock() if now is None else now
        deliveries: list[Delivery] = []
        resolved: list[Alert] = []
        for monitor in self.due(now):
            self._last_run[monitor.name] = now
            try:
                found = await monitor.check(now)
            except Exception as exc:  # noqa: BLE001 -- a broken monitor is data, not a crash
                self.failures[monitor.name] = repr(exc)
                continue
            self.failures.pop(monitor.name, None)
            sent, cleared = router.observe(monitor.name, found or [])
            deliveries.extend(sent)
            resolved.extend(cleared)
        return deliveries, resolved


@dataclass
class DigestSection:
    title: str
    lines: list[str] = field(default_factory=list)

    def add(self, line: str) -> None:
        if line:
            self.lines.append(line)


class Digest:
    """The once-a-day summary. Sections are contributed by whoever has
    something to say; this only decides when it is due and how it
    reads.

    Held alerts accumulate here between sends, so the daily message is
    the place everything that was not worth interrupting for finally
    arrives.
    """

    def __init__(self, *, hour: int = 8, clock=time.time, localtime=time.localtime) -> None:
        self.hour = int(hour)
        self._clock = clock
        self._localtime = localtime
        self._sections: dict[str, DigestSection] = {}
        self._held: list[Alert] = []
        # Anchored at construction: if today's hour has already passed,
        # today's digest is treated as done and the first one arrives
        # tomorrow. Without this, starting Sim at three in the afternoon
        # sends a "daily digest" within seconds of boot, containing
        # whatever the first tick happened to notice -- which is not a
        # summary of a day, and teaches a person that the digest is
        # noise. A machine restarted every day still gets tomorrow's.
        stamp = self._localtime(self._clock())
        self._last_sent_day: tuple[int, int, int] | None = (
            (stamp.tm_year, stamp.tm_mon, stamp.tm_mday) if stamp.tm_hour >= self.hour else None
        )

    def hold(self, alert: Alert) -> None:
        self._held.append(alert)

    def section(self, title: str) -> DigestSection:
        return self._sections.setdefault(title, DigestSection(title))

    @property
    def held(self) -> list[Alert]:
        return list(self._held)

    def due(self, now: float | None = None) -> bool:
        """True once per day, at or after `hour`.

        Keyed on the calendar day rather than a 24-hour interval: a
        digest that drifts an hour later every day because the machine
        was busy is a digest that eventually arrives at midnight.
        """
        now = self._clock() if now is None else now
        stamp = self._localtime(now)
        today = (stamp.tm_year, stamp.tm_mon, stamp.tm_mday)
        if self._last_sent_day == today:
            return False
        return stamp.tm_hour >= self.hour

    def render(self, *, title: str = "Daily digest", monitor_failures: dict[str, str] | None = None,
               suppressed: dict[str, int] | None = None) -> str:
        """The message body. Empty string when there is nothing to say
        -- a digest that arrives every day saying "nothing happened"
        trains a person to delete it unread, and then the one that
        matters gets deleted too."""
        blocks: list[str] = []
        by_severity: dict[str, list[Alert]] = {}
        for alert in self._held:
            by_severity.setdefault(alert.severity, []).append(alert)
        for severity in reversed(SEVERITIES):
            group = by_severity.get(severity) or []
            if not group:
                continue
            lines = [f"- [{a.monitor}] {a.message}" for a in group]
            blocks.append(f"{severity.upper()} ({len(group)}):\n" + "\n".join(lines))

        for name in sorted(self._sections):
            section = self._sections[name]
            if section.lines:
                blocks.append(f"{section.title}:\n" + "\n".join(f"- {line}" for line in section.lines))

        for monitor, count in sorted((suppressed or {}).items()):
            if count:
                blocks.append(f"{monitor}: {count} further warning(s) held back by the rate limit.")

        broken = sorted((monitor_failures or {}).items())
        if broken:
            blocks.append("Monitors that failed to run:\n"
                          + "\n".join(f"- {name}: {error}" for name, error in broken))

        if not blocks:
            return ""
        return f"{title}\n\n" + "\n\n".join(blocks)

    def sent(self, now: float | None = None) -> None:
        """Mark it delivered and start the next one empty."""
        now = self._clock() if now is None else now
        stamp = self._localtime(now)
        self._last_sent_day = (stamp.tm_year, stamp.tm_mon, stamp.tm_mday)
        self._held.clear()
        self._sections.clear()


__all__ = [
    "Alert", "AlertRouter", "Channel", "Delivery", "Digest", "DigestSection",
    "Monitor", "MonitorRegistry", "SEVERITIES", "Severity",
    "in_quiet_hours", "parse_quiet_hours",
]
