"""Was the answer computed, or read? (stage 19 item 8.)

Counted by tool NAME, from the actions a run proposed, and nothing else:
`run_analysis` is the workbench (`execution/workbench.py`, stage 19
item 1), and whether it exists in this checkout does not matter here.
Before it lands no run can name it, so every case reports "by reading";
after, a run that used it says so. Nothing in this package imports it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

#: The tools whose use means "a program over the full data". One today.
PROGRAM_TOOLS: frozenset[str] = frozenset({"run_analysis"})


def ran_program(tools: Iterable[str]) -> bool:
    return any(tool in PROGRAM_TOOLS for tool in tools)


def method_of(tools: Iterable[str]) -> str:
    """"program" or "reading"."""
    return "program" if ran_program(tools) else "reading"


def tally(tools: Iterable[str]) -> dict[str, int]:
    """tool -> how many times it was proposed, most first."""
    return dict(Counter(t for t in tools if t).most_common())


__all__ = ["PROGRAM_TOOLS", "method_of", "ran_program", "tally"]
