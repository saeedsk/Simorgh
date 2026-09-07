"""What Sim is doing while it boots, printed as it happens.

The creator, 2026-09-07, on a boot that took 38 seconds: "why does it
take so long ... add some progress bar at startup with details of what is
being loaded and performed at each boot stage". The 38 seconds turned out
to be the JSONL ledger re-reading all 192,456 stream files (fixed in
`ledger/backends/jsonl.py`), and boot is now around a second -- but the
reason nobody could see where those seconds went is that boot printed
nothing at all until it was over. A slow stage should name itself while
it is slow, not in a profiler afterwards.

Each stage prints a bar, its name, and what it actually loaded -- stream
counts for the ledger, the subsystems in each layer -- then is rewritten
in place with its elapsed time once it finishes. Anything over
`SLOW_STAGE_S` is marked, so the next regression of this kind announces
itself on the way past.

Non-interactive runs (`--self-check`, the HTTP API, tests, a piped
stdout) get a silent reporter: this writes to a terminal or not at all.
"""

from __future__ import annotations

import sys
import time
from typing import Callable

TOTAL_STAGES = 9  # ledger + bus + the six subsystem layers + the tick/status services
SLOW_STAGE_S = 2.0
_BAR_WIDTH = 24
_FILLED, _EMPTY = "█", "░"


class NullBootProgress:
    """The no-op used off a terminal. Same surface, prints nothing."""

    def stage(self, label: str, detail: str = "") -> None: ...

    def detail(self, detail: str) -> None: ...

    def done(self, detail: str = "") -> None: ...

    def finish(self, detail: str = "") -> None: ...


class BootProgress:
    def __init__(self, *, out: Callable[[str], None] | None = None, color: bool = True,
                 total: int = TOTAL_STAGES, now: Callable[[], float] = time.monotonic) -> None:
        self._out = out or (lambda s: sys.stdout.write(s))
        self._color = color
        self._total = max(1, total)
        self._now = now
        self._n = 0
        self._label = ""
        self._detail = ""
        self._started_at = now()
        self._stage_started_at = now()
        self._open = False

    # -- the three things a caller does ------------------------------------
    def stage(self, label: str, detail: str = "") -> None:
        """Begin a stage. Any stage still open is closed first, so a
        caller never has to pair calls by hand."""
        if self._open:
            self.done()
        self._n = min(self._n + 1, self._total)
        self._label, self._detail = label, detail
        self._stage_started_at = self._now()
        self._open = True
        self._render(end="")

    def detail(self, detail: str) -> None:
        """Replace the current stage's detail mid-flight -- what a stage
        found once it was far enough in to know (how many streams, which
        provider). Silent if no stage is open."""
        if not self._open:
            return
        self._detail = detail
        self._render(end="")

    def done(self, detail: str = "") -> None:
        if not self._open:
            return
        if detail:
            self._detail = detail
        self._render(end="\n", elapsed=self._now() - self._stage_started_at)
        self._open = False

    def finish(self, detail: str = "") -> None:
        """Close the last stage and print the total."""
        if self._open:
            self.done()
        total = self._now() - self._started_at
        tail = f"  {detail}" if detail else ""
        self._out(f"{self._dim('  ready in')} {self._bold(f'{total:.1f}s')}{self._dim(tail)}\n")

    # -- rendering ----------------------------------------------------------
    def _render(self, *, end: str, elapsed: float | None = None) -> None:
        filled = round(_BAR_WIDTH * self._n / self._total)
        bar = _FILLED * filled + _EMPTY * (_BAR_WIDTH - filled)
        line = f"\r  {self._cyan(bar)} {self._label}"
        if self._detail:
            line += self._dim(f"  {self._detail}")
        if elapsed is not None:
            stamp = f"  {elapsed:.1f}s"
            line += self._yellow(stamp + "  slow") if elapsed >= SLOW_STAGE_S else self._dim(stamp)
        # Pad past whatever the previous, possibly longer, line left behind.
        self._out(line + " " * 8 + end)

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self._color else text

    def _dim(self, text: str) -> str:
        return self._paint(text, "2")

    def _bold(self, text: str) -> str:
        return self._paint(text, "1")

    def _cyan(self, text: str) -> str:
        return self._paint(text, "36")

    def _yellow(self, text: str) -> str:
        return self._paint(text, "33")


def make_boot_progress(interactive: bool, *, stream=None) -> BootProgress | NullBootProgress:
    """A real reporter only for an interactive run writing to a TTY --
    the in-place rewriting is meaningless in a pipe or a log file."""
    stream = stream if stream is not None else sys.stdout
    if not interactive:
        return NullBootProgress()
    try:
        if not stream.isatty():
            return NullBootProgress()
    except (AttributeError, ValueError):
        return NullBootProgress()
    return BootProgress(out=lambda s: (stream.write(s), stream.flush()) and None)


__all__ = ["BootProgress", "NullBootProgress", "make_boot_progress", "SLOW_STAGE_S", "TOTAL_STAGES"]
