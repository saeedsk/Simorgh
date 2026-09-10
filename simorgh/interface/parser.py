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
    ("improve", "[path] <description>", "change something, tested before it lands"),
    ("skill", "<topic>", "draft a new reusable skill, audited before it lands"),
    ("plan", "<goal>", "break a goal into tracked steps"),
    ("research", "<topic>", "investigate a question, no code written"),
    ("interests", "[topic]", "topics Sim is following, or add one"),
    ("benchmark", "[suites|load|run|stop|history|show]", "score this system on GAIA, BFCL or SWE-bench, and track it"),
    ("schedule", "[every] <15m> <label>", "fire a reminder later, or on a repeat"),
    ("mcp", "[list|approve|deny]", "review external tools Sim has proposed"),
    ("auto", "[on|off|now]", "control the idle self-improvement loop"),
    ("pause", "", "hold everything"),
    ("resume", "", "let it continue"),
    ("help", "", "list everything"),
    ("exit", "", "leave (Ctrl-D also detaches)"),
)

COMMAND_NAMES: tuple[str, ...] = tuple(name for name, _, _ in COMMANDS)

#: Commands that take nothing, derived from the table's own argument
#: hints rather than listed again -- a second list is a list that
#: drifts, and three of these hints were wrong until 2026-09-10.
#:
#: Words after one of these is a sentence, not a command with an
#: argument, and that difference had teeth: `exit strategy for the
#: company is unclear` shut the system down, and `pause for a moment and
#: think about it` paused every subsystem (observer, 2026-09-10). Both
#: read `args` as a free-text "reason", so nothing downstream could tell
#: a remark from an instruction.
NO_ARGUMENT_COMMANDS: frozenset[str] = frozenset(
    name for name, hint, _ in COMMANDS if not hint
)


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

    explicit = stripped.startswith("/")
    body = stripped[1:] if explicit else stripped
    first, _, rest = body.partition(" ")
    # A trailing full stop or comma is typing, not syntax: `status.` is
    # still `status`. But only when the punctuation is all that stood in
    # the way -- `benchmark, how did it go?` is a question about the
    # benchmark, not a request to run one.
    lowered = first.lower()
    if lowered in COMMAND_NAMES and (explicit or not _swallows_a_sentence(lowered, rest)):
        return Command(name=lowered, args=rest.strip(), raw=raw)
    trimmed = lowered.rstrip(_SENTENCE_PUNCTUATION)
    if (trimmed in COMMAND_NAMES and (explicit or not _looks_like_prose(first, rest))
            and (explicit or not _swallows_a_sentence(trimmed, rest))):
        return Command(name=trimmed, args=rest.strip(), raw=raw)
    lowered = trimmed

    if (len(lowered) >= 4 and (explicit or not _looks_like_prose(first, rest))
            and (explicit or not _swallows_a_sentence(lowered, rest))):
        match = difflib.get_close_matches(lowered, COMMAND_NAMES, n=1, cutoff=_AUTOCORRECT_CUTOFF)
        if match:
            return Command(name=match[0], args=rest.strip(), raw=raw, guessed_from=first)

    return Command(name=None, args=stripped, raw=raw)


#: Punctuation a command never ends in, and a sentence often does.
_SENTENCE_PUNCTUATION = ",.;:!?"


def _swallows_a_sentence(name: str, rest: str) -> bool:
    """Whether treating `name` as a command would eat a sentence.

    A command that takes no arguments, followed by words, is somebody
    talking. `exit strategy for the company is unclear` stopped the
    system and `pause for a moment and think about it` paused every
    subsystem, because both commands accept `args` as a free-text
    reason and neither could tell a remark from an instruction
    (observer, 2026-09-10).

    Typing the slash overrides this, as it does everywhere else here:
    `/exit the meeting overran` is a person saying "this is a command",
    reason and all."""
    return bool(rest.strip()) and name in NO_ARGUMENT_COMMANDS


def _looks_like_prose(first: str, rest: str) -> bool:
    """Whether a near-miss first word is a typo or just a sentence.

    Live-caught 2026-09-09. The creator typed

        improvment, now the game works for one second, then it freezes

    meaning it as a remark. `improvment,` is close enough to `improve`
    to clear the cutoff, so it became `improve <topic>` -- which, with
    no path in it, creates a *skill* task. A bug report about a game
    became "write a skill", and three rounds of verification then asked
    whether a skill had been produced.

    An exact command is still a command however it is punctuated. This
    only holds back the GUESS, and only without a leading `/`: typing
    the slash is a person saying "this is a command", and their typo
    should still be corrected.
    """
    if not rest.strip():
        # A word on its own is not a sentence, whatever it ends in.
        # `status.` is somebody typing `status` and a full stop.
        return False
    if first.rstrip(_SENTENCE_PUNCTUATION) != first:
        # `improve` never ends in a comma. A sentence often does.
        return True
    # A guessed command carrying a comma'd clause after it is a sentence
    # far more often than an argument: real arguments are paths, ids and
    # topics, not prose with punctuation in the middle.
    return "," in rest
