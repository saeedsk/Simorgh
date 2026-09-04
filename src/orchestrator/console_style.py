"""Minimal ANSI color helpers for the CLI (src/main.py) -- purely
cosmetic, never load-bearing: every caller must still work correctly if
color is stripped or disabled, since color is skipped automatically
whenever stdout isn't a real terminal (piped output, tests, a log file)
or the user has set NO_COLOR (see https://no-color.org).
"""

from __future__ import annotations

import os
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
