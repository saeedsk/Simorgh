"""Command grammar -- a port of v1's `strip_command_slash` /
`autocorrect_command` (`src/main.py`). A leading `/` is optional; a
near-miss first word is corrected *and announced*, never silently
(spec section 3.3's closing note).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

#: Every command, once. `(name, argument hint, what it does)`.
#:
#: One table, because there were three: this module's name list, the
#: TUI's completion table, and the help panel's rows. Adding a command
#: meant remembering all three, and on 2026-09-09 four new commands were
#: added to two of them -- so `tool`, `domains`, `config` and `alerts`
#: worked when typed and did not autocomplete, which reads like the
#: command does not exist.
COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("status", "", "health, vitals, posture and git in one panel"),
    ("domains", "[name]", "documents, mail, the house, energy, media, security: on? working?"),
    ("tool", "[name] [args]", "list every tool, or run one -- Guardian gates it as usual"),
    ("alerts", "[all]", "what the monitors have raised, and what is waiting for the digest"),
    ("config", "[section]", "the settings actually in force, and any nothing reads"),
    ("capabilities", "", "what Sim can actually reach: Node, Docker, optional packages"),
    ("tasks", "[work]", "see the backlog, or advance the next item"),
    ("cancel", "<task_id>", "stop a running task"),
    ("improve", "<path> <description>", "revise existing code, tested before it lands"),
    ("plan", "<goal>", "break a goal into tracked steps"),
    ("research", "<topic>", "investigate a question, no code written"),
    ("interests", "", "topics Sim is following"),
    ("benchmark", "", "score this system on GAIA or BFCL, and track it"),
    ("schedule", "[every] <15m> <label>", "fire a reminder later, or on a repeat"),
    ("mcp", "", "review external tools Sim has proposed"),
    ("auto", "[on|off|now]", "control the idle self-improvement loop"),
    ("pause", "", "hold everything"),
    ("resume", "", "let it continue"),
    ("help", "", "list everything"),
    ("exit", "", "leave (Ctrl-D also detaches)"),
)

COMMAND_NAMES: tuple[str, ...] = tuple(name for name, _, _ in COMMANDS)


#: How many rows the startup splash shows. The table is ordered most
#: useful first, so the splash is its head: twenty rows on the first
#: screen someone sees is a wall, and `help` is one word away.
SPLASH_COMMANDS = 8


def command_help(limit: int | None = None) -> tuple[tuple[str, str], ...]:
    """`(usage, description)` for the help panel and the completion
    menu, derived rather than kept in step by hand."""
    rows = tuple((f"{name} {args}".strip(), description) for name, args, description in COMMANDS)
    return rows[:limit] if limit else rows

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
