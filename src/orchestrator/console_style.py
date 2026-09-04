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
