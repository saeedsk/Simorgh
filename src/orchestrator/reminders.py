"""Lightweight, in-process reminders: a background timer that prints a
message to the terminal after a delay -- the direct fix for "remind me
to wake up in one minute" getting the honest but unhelpful answer "I
have no way to interrupt you unprompted." That used to be true; it no
longer is, once src/orchestrator/autonomy.py proved a daemon thread can
safely print between prompts while the main loop blocks on `input()`.
This reuses that exact pattern for a much smaller, session-scoped need.

Deliberately NOT durable or persisted across a restart or relaunch --
these are ephemeral, one-off nudges for the current session, not tracked
work. See src/orchestrator/tasks.py for the durable, resumable kind of
"remembered for later."
"""

from __future__ import annotations

import re
import threading

from src.orchestrator.console_style import style

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}

MAX_DURATION_SECONDS = 24 * 3600.0  # a day -- a sanity ceiling, not a real limit


def parse_duration(raw: str) -> float | None:
    """Parses "60", "60s", "1m", "2h", "1.5m" (case-insensitive, no unit
    defaults to seconds) into seconds. Returns None for anything
    unparseable, non-positive, or absurdly long (see
    MAX_DURATION_SECONDS) -- never raises.
    """
    match = _DURATION_RE.match(raw)
    if not match:
        return None
    seconds = float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if seconds <= 0 or seconds > MAX_DURATION_SECONDS:
        return None
    return seconds


def schedule_reminder(
    delay_seconds: float, message: str, prompt_redraw: str = "> "
) -> threading.Timer:
    """Fires exactly once, after `delay_seconds`, printing `message`
    clearly and then redrawing the input prompt so the terminal doesn't
    look stuck. Returns the underlying `threading.Timer` (a daemon
    thread, so it dies with the process rather than keeping it alive)
    without blocking the caller -- scheduling a reminder is instant.
    """
    def _fire() -> None:
        print(style(f"\n⏰ [reminder] {message}", "yellow", "bold"))
        print(style(prompt_redraw, "cyan", "bold"), end="", flush=True)

    timer = threading.Timer(delay_seconds, _fire)
    timer.daemon = True
    timer.start()
    return timer
