"""Minimal ANSI color helpers for the CLI (src/main.py) -- purely
cosmetic, never load-bearing: every caller must still work correctly if
color is stripped or disabled, since color is skipped automatically
whenever stdout isn't a real terminal (piped output, tests, a log file)
or the user has set NO_COLOR (see https://no-color.org).
"""

from __future__ import annotations

import keyword
import os
import re
import sys
import threading
import time
from typing import Callable

_ENABLED = sys.stdout.isatty() and "NO_COLOR" not in os.environ

_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    # No standard ANSI "orange" -- 256-color code 208 is the closest widely
    # supported approximation; falls back gracefully (just no color) on a
    # terminal that only supports the 8/16-color basic codes, since it
    # simply won't recognize the escape and most terminals still print the
    # rest of the text plainly in that case.
    "orange": "\033[38;5;208m",
}


def style(text: str, *names: str) -> str:
    """Wrap `text` in the named ANSI codes (e.g. style(x, "green", "bold")).
    Returns `text` unchanged when color is disabled -- callers never need
    their own isatty/NO_COLOR check.
    """
    if not _ENABLED or not names:
        return text
    prefix = "".join(_CODES[name] for name in names if name in _CODES)
    return f"{prefix}{text}{_CODES['reset']}"


# Longest-first so e.g. "async" doesn't get half-matched by a shorter
# alternative before it -- re's alternation otherwise tries alternatives
# left-to-right and stops at the first match, not the longest one.
_PY_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(sorted(keyword.kwlist, key=len, reverse=True)) + r")\b"
)
_COMMENT_RE = re.compile(r"(#.*)$")


def _highlight_python_line(line: str) -> str:
    """A light, regex-based approximation of syntax highlighting --
    keywords and trailing comments only, no real tokenizer (so it can
    mis-highlight a '#' inside a string literal, for instance). Good
    enough to make a code block visually scannable; never claimed to be
    a real Python lexer.
    """
    if not _ENABLED:
        return line
    comment_match = _COMMENT_RE.search(line)
    code_part, comment_part = (line[: comment_match.start()], line[comment_match.start() :]) if comment_match else (line, "")
    highlighted = _PY_KEYWORD_RE.sub(lambda m: style(m.group(1), "magenta", "bold"), code_part)
    return highlighted + (style(comment_part, "dim") if comment_part else "")


def format_code_block(
    code: str, *, label: str = "code", max_lines: int = 30, max_line_chars: int = 160
) -> str:
    """Render `code` as a bordered, (lightly) syntax-highlighted block
    for terminal display, bounded in both directions -- a huge or
    pathologically long-lined payload (e.g. a confused model dumping a
    hallucinated transcript into what should have been a one-line tool
    argument) gets truncated with a clear count of what was cut, rather
    than flooding the terminal. With color disabled, this still reads
    fine as a plain bordered block -- the border/truncation notice is
    the substance, highlighting is a bonus.
    """
    lines = (code or "").splitlines() or [""]
    shown = lines[:max_lines]
    cut_line_count = len(lines) - len(shown)

    rendered = []
    for line in shown:
        cut_chars = len(line) - max_line_chars
        if cut_chars > 0:
            line = line[:max_line_chars] + style(f"…(+{cut_chars})", "dim")
        rendered.append(f"{style('│', 'dim')} {_highlight_python_line(line)}")

    header = style(f"┌─ {label} ", "dim", "bold") + style("─" * max(3, 50 - len(label)), "dim")
    footer_notice = (
        [style(f"│ … {cut_line_count} more line(s) truncated", "dim")] if cut_line_count > 0 else []
    )
    footer = style("└" + "─" * 52, "dim")
    return "\n".join([header, *rendered, *footer_notice, footer])


def format_diff_block(diff_lines: list[str], *, label: str = "diff", max_lines: int = 60) -> str:
    """Render a unified diff (e.g. from `difflib.unified_diff`) as a
    bordered, colored block -- `+`/`-` lines in green/red, `@@` hunk
    headers cyan, the `---`/`+++` file headers bold, everything else
    left plain. Bounded like `format_code_block` (a full-file rewrite's
    diff can still be huge) with the same truncation notice; empty input
    renders as an explicit "(no changes)" line rather than an empty
    block that could read as a rendering bug.
    """
    lines = list(diff_lines) or ["(no changes)"]
    shown = lines[:max_lines]
    cut_line_count = len(lines) - len(shown)

    rendered = []
    for raw in shown:
        line = raw.rstrip("\n")
        if line.startswith("+++") or line.startswith("---"):
            colored = style(line, "bold")
        elif line.startswith("@@"):
            colored = style(line, "cyan", "bold")
        elif line.startswith("+"):
            colored = style(line, "green")
        elif line.startswith("-"):
            colored = style(line, "red")
        else:
            colored = line
        rendered.append(f"{style('│', 'dim')} {colored}")

    header = style(f"┌─ {label} ", "dim", "bold") + style("─" * max(3, 50 - len(label)), "dim")
    footer_notice = (
        [style(f"│ … {cut_line_count} more line(s) truncated", "dim")] if cut_line_count > 0 else []
    )
    footer = style("└" + "─" * 52, "dim")
    return "\n".join([header, *rendered, *footer_notice, footer])


_CHECKLIST_ICONS = {
    "pending": "○",
    "in_progress": "◐",
    "done": "✅",
    "failed": "❌",
}
_CHECKLIST_COLORS = {
    "pending": "dim",
    "in_progress": "cyan",
    "done": "green",
    "failed": "red",
}


def render_checklist(items: list[tuple[str, str]], title: str = "") -> str:
    """A compact, icon-prefixed checklist for multi-step work (`batch`,
    `evolve`) -- `items` is a list of `(label, status)` pairs, `status`
    one of "pending"/"in_progress"/"done"/"failed". Reprinted as a whole
    block after each step changes (not redrawn in place -- same
    reasoning as `LiveTicker`: a cursor/carriage-return-based redraw is
    fragile across terminals, piped output, and non-TTY logging), so a
    multi-item run has a visible, persistent "what's left" view between
    the individual step's own drafting/audit/test narration, instead of
    only a scrolling trail with no summary until the very end.
    """
    lines = [style(title, "magenta", "bold")] if title else []
    for label, status in items:
        icon = _CHECKLIST_ICONS.get(status, "?")
        color = _CHECKLIST_COLORS.get(status, "dim")
        lines.append(f"  {style(icon, color)} {label}")
    return "\n".join(lines)


DEFAULT_TICK_INTERVAL_SECONDS = 5.0


class LiveTicker:
    """A periodic "still working... (Ns elapsed)" status line for a
    long-running blocking call that would otherwise sit completely
    silent -- run_isolated_test_suite (copies the repo, runs the entire
    test suite twice) is the direct motivating case: previously just two
    static print()s around a subprocess call that can genuinely take a
    while, with zero feedback in between. This is Claude Code's
    "ongoing status" idea (the creator's own phrase), adapted to a
    plain-text, no-TUI-library CLI: not a true in-place spinner (a
    carriage-return redraw is fragile across terminals, and this project
    already has a working, safer precedent to reuse instead) -- a new
    line every `interval` seconds, printed by a daemon thread while the
    caller's own code stays blocked on the slow call. Safe for exactly
    the same reason reminders/the autonomous loop are: the thread only
    ever prints between the caller's own output, never concurrently with
    it, as long as the wrapped block doesn't itself print (true here --
    the wrapped call is a blocking subprocess.run with nothing printed
    until it returns).

    Usage:
        with LiveTicker("running the isolated test suite"):
            slow_call()
    """

    def __init__(
        self,
        message: str,
        interval: float = DEFAULT_TICK_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._message = message
        self._interval = interval
        self._clock = clock
        self._start = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "LiveTicker":
        self._start = self._clock()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()
        return self

    def _tick(self) -> None:
        while not self._stop_event.wait(self._interval):
            elapsed = self._clock() - self._start
            print(style(f"   ⏳ {self._message}... ({elapsed:.0f}s elapsed)", "dim"))

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1.0)
