"""Command grammar -- a port of v1's `strip_command_slash` /
`autocorrect_command` (`src/main.py`). A leading `/` is optional; a
near-miss first word is corrected *and announced*, never silently
(spec section 3.3's closing note).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

COMMAND_NAMES = (
    "reflect", "propose", "improve", "patch", "batch", "plan", "evolve", "research",
    "project", "discover", "tasks", "work", "autonomous", "digest", "news", "growth",
    "pending", "skills", "use", "log", "trace", "fetch", "interest", "interests",
    "curious", "sleep", "history", "run", "budget", "vitals", "remind",
    "status", "pause", "resume", "stop", "exit", "quit", "help",
)

_AUTOCORRECT_CUTOFF = 0.75


@dataclass(frozen=True)
class Command:
    name: str | None  # None means "plain chat text", not a recognized command
    args: str
    raw: str
    guessed_from: str | None = None


def parse(line: str) -> Command | None:
    raw = line
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("!"):
        return Command(name="!", args=stripped[1:].strip(), raw=raw)

    body = stripped[1:] if stripped.startswith("/") else stripped
    first, _, rest = body.partition(" ")
    lowered = first.lower()

    if lowered in COMMAND_NAMES:
        return Command(name=lowered, args=rest.strip(), raw=raw)

    if len(lowered) >= 4:
        match = difflib.get_close_matches(lowered, COMMAND_NAMES, n=1, cutoff=_AUTOCORRECT_CUTOFF)
        if match:
            return Command(name=match[0], args=rest.strip(), raw=raw, guessed_from=first)

    return Command(name=None, args=stripped, raw=raw)
