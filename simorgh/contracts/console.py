"""What Sim said on its own console, written down.

Every scrolling line in the REPL passes through one gate
(`interface/service.py`'s `_out`), and until now that gate printed and
forgot. The live process runs with stdin, stdout and stderr all on the
same tty and `sim.sh` redirects none of them, so a line that scrolled
past existed nowhere else: not in the ledger, not in a log, not in
memory. The console was write-only.

That is not a cosmetic gap. On 2026-09-16 the creator asked, out loud,
"what was the red message?" -- a question about Sim's own screen. Sim
had no tool that could answer it, tried `read_file` on a log that does
not exist, got a refusal, searched and got no matches, and then
answered anyway: three repeats of a 429 rate-limit error, the garden
camera timing out, the front camera's baseline updated fine. None of it
had happened. `workspace/cameras/baselines.json` did not (and does not)
exist. The honesty rule in this project is that a tool must never
succeed while saying nothing true; here there was no tool at all, and
the gap itself produced the fiction. A question with no reachable
ground truth is an invitation to invent one.

So the lines are recorded here, and Execution gets a tool that reads
them. Interface writes, Execution reads, and neither may import the
other -- which is exactly the shape Contracts exists for (see
`scratch.py` for the same argument about `workspace/`).

Bounded on purpose. This project has already paid once for unbounded
append (the 192k-file trace explosion, 2026-09-07): the file is trimmed
back to `KEEP_LINES` whenever it passes `MAX_BYTES`, so the worst case
is a fixed cost rather than a growing one.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .settings import settings_home

#: Stripped before recording. The file is read back by a model and by a
#: person; escape sequences in it would be noise at best, and at worst
#: the `\x1b[2J` that cleared a terminal in the 2026-09-10 incident.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

#: Trim when the file passes this, back to the last `KEEP_LINES`.
MAX_BYTES = 512 * 1024
KEEP_LINES = 2000

#: How often to stat the file. `_out` runs on the asyncio loop thread
#: for every line Sim prints, so the trim check is amortised rather
#: than paid per line.
_CHECK_EVERY = 200

_since_check = 0


def console_log_path(home: Path | None = None) -> Path:
    return settings_home(home) / "interface" / "console.log"


def plain(text: str) -> str:
    """One console line with its colour removed."""
    return _ANSI.sub("", text or "").rstrip()


def record(text: str, home: Path | None = None) -> None:
    """Append one printed line. Never raises.

    `_out` is the one gate every scrolling line passes through, and a
    console that cannot print because its recorder threw would be a
    strictly worse system than one that forgets. Recording is
    best-effort by construction.
    """
    global _since_check
    line = plain(text)
    if not line:
        return
    try:
        path = console_log_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {line}\n")
        _since_check += 1
        if _since_check >= _CHECK_EVERY:
            _since_check = 0
            _trim(path)
    except OSError:
        return


def _trim(path: Path) -> None:
    try:
        if path.stat().st_size <= MAX_BYTES:
            return
        kept = path.read_text(encoding="utf-8", errors="replace").splitlines()[-KEEP_LINES:]
        tmp = path.with_suffix(".log.tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return


def tail(limit: int = 40, *, contains: str = "", home: Path | None = None) -> list[str]:
    """The last `limit` recorded lines, oldest first.

    `contains` filters case-insensitively before the limit is applied,
    so asking for errors returns the last `limit` ERRORS rather than
    whichever errors happen to fall inside the last `limit` lines --
    the distinction that makes the filter worth having.
    """
    try:
        lines = console_log_path(home).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if contains:
        needle = contains.lower()
        lines = [line for line in lines if needle in line.lower()]
    return lines[-max(1, limit):]


__all__ = ["KEEP_LINES", "MAX_BYTES", "console_log_path", "plain", "record", "tail"]
