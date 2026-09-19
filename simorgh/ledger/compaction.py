"""Record compaction (02-ledger section 5.2) -- retention of the *log
itself*, distinct from context compaction (which is Cognition's job and
operates on what a model sees, not on what is stored).

Policy is per stream prefix: a duration ("7d", "90d") or "forever".
- Per-id streams (`trace:<id>`, `dead:<type>`) under a duration are
  deleted whole once their last event is older than the window.
- Singleton streams (`activity`) under a duration are truncated to the
  events inside the window.
- `forever` streams that have a snapshot are truncated to the snapshot
  plus the last `keep_tail` events: the snapshot preserves state, the
  tail preserves recent debuggability.

Forgetting is explicit and auditable: the Service records what each pass
removed (counts, never contents) on `ledger:compaction`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .api import LedgerBackend

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$")
_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}

# `trace:` is one stream -- and one idempotency file -- per traced
# message, so its cost is file *count*, not bytes: 192,332 of them on
# the creator's ledger held 364MB of JSON in 1.5GB of disk, all of it
# written inside a single day. A trace answers "why did Sim just do
# that", which is a question asked within hours, so a week of them was
# never read and only ever slowed the boot that had to stat them.
# Prefix -> window. A per-id stream (`action:<id>`) is deleted whole once
# its last event is older than the window; a journal stream
# (`metrics:history`) is truncated within. A stream with no entry here is
# forever, and forever is truncated only below a snapshot -- so every
# stream that grows on a timer and that no decision is rebuilt from
# gets a window. Until 2026-09-19 only traces had one, and the three
# largest streams on disk were a metrics snapshot every 10 s (114 MB), a
# paused Curiosity's tick every 3 s (43 MB) and mood decay every 5 s
# (17 MB) (2026-09-18 evaluation, B3/B19). Kept forever on purpose:
# `task:` (resume, outcome typing), `learn:outcomes` (the competence
# fold), `memory:*`, `guardian:rejected` (immunity), `self:*`.
DEFAULT_RETENTION: dict[str, str] = {
    "trace:": "2d", "dead:": "30d", "activity": "90d",
    "metrics:history": "7d", "curiosity:ticks": "7d", "persona:state": "7d",
    "execution:inflight": "7d", "execution:tools": "30d", "cognition:budget:": "3d",
    "cognition:summaries:": "30d", "cognition:calls": "14d", "voice:turns": "30d",
    "action:": "30d", "verify:": "90d", "reflect:": "90d", "reflection:alerts": "90d",
}


def parse_duration(text: str | float | int | None) -> float | None:
    """`"7d"` -> 604800.0; `"forever"`/None -> None; a bare number is seconds."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    if str(text).strip().lower() == "forever":
        return None
    match = _DURATION.match(str(text))
    if not match:
        raise ValueError(f"bad duration {text!r}: use e.g. 30s, 5m, 12h, 7d, or 'forever'")
    return float(match.group(1)) * _UNITS[match.group(2)]


@dataclass(frozen=True)
class RetentionPolicy:
    windows: dict[str, float | None] = field(default_factory=dict)  # prefix -> seconds (None = forever)
    keep_tail: int = 50

    @classmethod
    def parse(cls, mapping: Mapping[str, object] | None, *, keep_tail: int = 50) -> "RetentionPolicy":
        merged: dict[str, object] = dict(DEFAULT_RETENTION)
        merged.update({k: v for k, v in (mapping or {}).items() if k != "keep_tail"})
        keep = int((mapping or {}).get("keep_tail", keep_tail))  # type: ignore[arg-type]
        return cls({prefix: parse_duration(v) for prefix, v in merged.items()}, keep)  # type: ignore[arg-type]

    def window_for(self, stream: str) -> float | None:
        """The longest matching prefix wins; no match means forever."""
        best: str | None = None
        for prefix in self.windows:
            if stream.startswith(prefix) and (best is None or len(prefix) > len(best)):
                best = prefix
        return self.windows[best] if best is not None else None


@dataclass
class CompactionReport:
    streams_seen: int = 0
    streams_deleted: int = 0
    events_truncated: int = 0
    details: list[tuple[str, str, int]] = field(default_factory=list)  # (stream, action, count)

    def as_payload(self) -> dict:
        return {"streams_seen": self.streams_seen, "streams_deleted": self.streams_deleted,
                "events_truncated": self.events_truncated}


async def run_compaction(backend: LedgerBackend, policy: RetentionPolicy, *, now: float,
                         protect: tuple[str, ...] = ("ledger:",)) -> CompactionReport:
    report = CompactionReport()
    for stream in await backend.streams(""):
        if stream.startswith(protect):
            continue
        report.streams_seen += 1
        window = policy.window_for(stream)
        if window is None:
            snapshot = await backend.read_snapshot(stream)
            if snapshot is None:
                continue
            _, at_seq = snapshot
            cutoff = at_seq - policy.keep_tail  # events with seq <= cutoff are removed
            if cutoff >= 1:
                removed = await backend.truncate_below(stream, cutoff + 1)
                if removed:
                    report.events_truncated += removed
                    report.details.append((stream, "truncate_below_snapshot", removed))
            continue
        oldest_allowed = now - window
        # Idle past its window: delete it whole (a finished `trace:`/`action:`
        # stream). Still being written: truncate what is older than the
        # window. The choice used to be made by the NAME (`":" in name` meant
        # per-id, delete-only), so `metrics:history`, `curiosity:ticks`,
        # `persona:state`, `voice:turns` and the other long-lived streams with
        # a colon were never truncated while alive, and the retention windows
        # added for them on 2026-09-18 did nothing (found writing ledger's
        # CONTRACT.md: 20 daily events under 7d, 0 removed).
        last = await backend.last_ts(stream)
        if last is not None and last < oldest_allowed:
            await backend.delete_stream(stream)
            report.streams_deleted += 1
            report.details.append((stream, "delete", 1))
            continue
        head_events = await backend.read(stream, from_seq=1, limit=1)
        if not head_events or head_events[0].ts >= oldest_allowed:
            continue  # nothing old enough to drop: skip the full read
        first_kept: int | None = None
        for event in await backend.read(stream, from_seq=1, limit=None):
            if event.ts >= oldest_allowed:
                first_kept = event.seq
                break
        if first_kept is None:
            head = await backend.head(stream)
            first_kept = head + 1 if head else None
        if first_kept and first_kept > 1:
            removed = await backend.truncate_below(stream, first_kept)
            if removed:
                report.events_truncated += removed
                report.details.append((stream, "truncate_window", removed))
    return report


__all__ = ["DEFAULT_RETENTION", "CompactionReport", "RetentionPolicy", "parse_duration", "run_compaction"]
