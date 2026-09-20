"""How long, said the way people say it: "10m", "2h", "90s".

It lives in `contracts` because two subsystems that may not import each
other need the same answer: the Kernel's scheduler arms a reminder with
it, and a session waits with it (stage 7 item 5). One parser, so "1.5m"
never means two different things in two places.
"""

from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(raw: str, *, max_seconds: float = 86400.0) -> float | None:
    """Parses "60", "60s", "1m", "2h", "1.5m" into seconds. `None` for
    anything unparseable, non-positive, or over `max_seconds` -- never
    raises (v1 `reminders.parse_duration`, verbatim behavior)."""
    match = _DURATION_RE.match(raw)
    if not match:
        return None
    seconds = float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if seconds <= 0 or seconds > max_seconds:
        return None
    return seconds


__all__ = ["parse_duration"]
