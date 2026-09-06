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
from .streams import is_per_id

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$")
_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}

DEFAULT_RETENTION: dict[str, str] = {"trace:": "7d", "dead:": "30d", "activity": "90d"}


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
        if is_per_id(stream):
            last = await backend.last_ts(stream)
            if last is not None and last < oldest_allowed:
                await backend.delete_stream(stream)
                report.streams_deleted += 1
                report.details.append((stream, "delete", 1))
            continue
        # singleton stream: keep only events inside the window
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
