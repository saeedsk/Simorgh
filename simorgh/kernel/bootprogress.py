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

TOTAL_STAGES = 10  # ledger + bus + the seven subsystem layers + the tick/status services
SLOW_STAGE_S = 2.0
_BAR_WIDTH = 24
_FILLED, _EMPTY = "━", "─"
#: The look (the creator, 2026-10-04: "more visually pleasant, elegant,
#: modern and futuristic"): one live line with a cyan-to-violet bar while a
#: stage runs; each finished stage collapses to a quiet aligned row.
_RUNNING, _DONE, _FAILED, _READY = "◇", "◆", "✕", "✦"
_GRADIENT = (51, 45, 39, 33, 63, 99, 135, 171)      # xterm-256: cyan -> violet
_LABEL_W = 9
_MAX_WIDTH = 96


class NullBootProgress:
    """The no-op used off a terminal. Same surface, prints nothing."""

    def stage(self, label: str, detail: str = "") -> None: ...

    def detail(self, detail: str) -> None: ...

    def done(self, detail: str = "") -> None: ...

    def finish(self, detail: str = "") -> None: ...


def _terminal_width() -> int:
    import shutil

    return shutil.get_terminal_size((_MAX_WIDTH, 24)).columns


class BootProgress:
    def __init__(self, *, out: Callable[[str], None] | None = None, color: bool = True,
                 total: int = TOTAL_STAGES, now: Callable[[], float] = time.monotonic,
                 width: int | None = None) -> None:
        self._out = out or (lambda s: sys.stdout.write(s))
        self._color = color
        self._total = max(1, total)
        self._now = now
        self._width = max(40, min(_MAX_WIDTH, width or _terminal_width()))
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
        self._live()

    def detail(self, detail: str) -> None:
        """Replace the current stage's detail mid-flight -- what a stage
        found once it was far enough in to know (how many streams, which
        provider). Silent if no stage is open."""
        if not self._open:
            return
        self._detail = detail
        self._live()

    def done(self, detail: str = "") -> None:
        if not self._open:
            return
        if detail:
            self._detail = detail
        elapsed = self._now() - self._stage_started_at
        failed = detail == "failed"
        stamp = f"{elapsed:.1f}s"
        slow = elapsed >= SLOW_STAGE_S
        tail = f"{stamp}  ▲ slow" if slow else stamp
        room = self._width - 4 - _LABEL_W - 2 - len(tail) - 2
        text = self._fit(self._detail, room)
        glyph = self._paint(_FAILED, "1;31") if failed else self._paint(_DONE, "38;5;43")
        line = (f"  {glyph} {self._paint(self._label.ljust(_LABEL_W), '1')}  {self._dim(text.ljust(room))}  "
                + (self._paint(tail, "38;5;214") if slow else self._dim(tail)))
        self._out("\r\033[K" + line + "\n")
        self._open = False

    def finish(self, detail: str = "") -> None:
        """Close the last stage, draw the closing rule and the total."""
        if self._open:
            self.done()
        total = self._now() - self._started_at
        rule = self._gradient(_FILLED * (self._width - 4), self._width - 4)
        tail = f"  ·  {detail}" if detail else ""
        self._out(f"  {rule}\n  {self._paint(_READY, '1;38;5;171')} {self._bold('Sim is ready')}"
                  f"{self._dim(' in ')}{self._bold(f'{total:.1f}s')}{self._dim(tail)}\n")

    # -- rendering ----------------------------------------------------------
    def _live(self) -> None:
        """The stage running now, rewritten in place: what it is, what it
        is doing, and the whole boot's bar with a count."""
        filled = round(_BAR_WIDTH * self._n / self._total)
        bar = self._gradient(_FILLED * filled, _BAR_WIDTH) + self._paint(_EMPTY * (_BAR_WIDTH - filled), "38;5;238")
        count = f"{self._n}/{self._total}"
        room = self._width - 4 - _LABEL_W - 2 - _BAR_WIDTH - len(count) - 4
        text = self._fit(self._detail, room)
        line = (f"  {self._paint(_RUNNING, '38;5;45')} {self._paint(self._label.ljust(_LABEL_W), '1')}  "
                f"{self._dim(text.ljust(room))}  {bar}  {self._dim(count)}")
        self._out("\r\033[K" + line)

    @staticmethod
    def _fit(text: str, room: int) -> str:
        text = " ".join(str(text or "").split())
        room = max(0, room)
        return text if len(text) <= room else text[: max(0, room - 1)] + "…"

    def _gradient(self, text: str, span: int) -> str:
        """`text` coloured cell by cell along the cyan-to-violet ramp, as
        if it were `span` cells long."""
        if not self._color:
            return text
        out = []
        for i, ch in enumerate(text):
            code = _GRADIENT[min(len(_GRADIENT) - 1, i * len(_GRADIENT) // max(1, span))]
            out.append(f"\033[38;5;{code}m{ch}")
        return "".join(out) + ("\033[0m" if out else "")

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self._color else text

    def _dim(self, text: str) -> str:
        return self._paint(text, "2")

    def _bold(self, text: str) -> str:
        return self._paint(text, "1")


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
