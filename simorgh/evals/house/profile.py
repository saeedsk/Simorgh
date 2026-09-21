"""Where the time actually went, sampled from inside (stage 11 item 8).

The timing table says which SEGMENT is slow -- STT, think, a tool,
first audio. That is the right first question and it is not the last
one: when a segment is slow for no reason the table can see, or when a
thread spins with no I/O at all, what you need is the stack it was in.

The plan asked for `py-spy` here. py-spy is the better profiler and it
is the wrong tool for this job on this machine: attaching to another
process on macOS needs root, and "a spinning main thread could not be
stack-traced" (2026-09-20, the SQLite ledger default, stage 9 item 5)
is exactly that wall. A sampler that runs INSIDE the process needs no
permission from anybody, and `sys._current_frames()` is in the
standard library. Recorded as a departure in the plan file.

What it cannot do is see native frames or a thread holding the GIL in
C -- if a stack sits in the same C call forever, that is the answer
this reports, and py-spy under `sudo` is the next step. Saying so is
the point: a profiler that quietly cannot see something is worse than
no profiler.

Read it as WALL CLOCK, not CPU. A thread blocked in `recv` is sampled
exactly as often as one spinning in a loop, so "26% of samples in
shutdown" means "a thread was sitting in shutdown for a quarter of
the run", which is usually correct and boring. What separates the two
is the frame: a blocked thread is in a syscall, a spinning one is in
your code. That distinction is the whole reason to look at stacks
rather than at a timing table, and reading a percentage here as CPU
share is the mistake this paragraph exists to stop.

The collapsed-stack output is the format flamegraph.pl and speedscope
both read, so the flame graph the plan asks for is one pipe away
without a dependency.
"""

from __future__ import annotations

import collections
import sys
import threading
import time
from dataclasses import dataclass, field

#: How often to take a stack. 10 ms is 100 samples a second per
#: thread: fine enough to find a spin in a one-second turn, coarse
#: enough that the sampler is not what the profile shows.
INTERVAL_S = 0.010

#: Frames from these files are the sampler and the machinery around
#: it, and every profile would otherwise be topped by them.
_BORING = ("evals/house/profile.py", "threading.py", "selectors.py")


@dataclass
class Profile:
    """Stacks and how often each was seen."""

    counts: collections.Counter = field(default_factory=collections.Counter)
    samples: int = 0
    seconds: float = 0.0

    def collapsed(self) -> str:
        """One line per stack, `a;b;c count` -- what flamegraph.pl and
        speedscope read."""
        return "\n".join(f"{stack} {count}" for stack, count in self.counts.most_common())

    def hottest(self, limit: int = 12) -> list[tuple[str, int, float]]:
        """`(stack, samples, share)`, worst first."""
        total = max(1, self.samples)
        return [(stack, count, count / total) for stack, count in self.counts.most_common(limit)]

    def render(self, limit: int = 8) -> str:
        if not self.samples:
            return "nothing was sampled (the run was shorter than one interval)"
        lines = [f"{self.samples} samples over {self.seconds:.1f}s, {len(self.counts)} distinct stacks"]
        for stack, count, share in self.hottest(limit):
            leaf = stack.rsplit(";", 1)[-1]
            lines.append(f"  {share:5.1%}  {count:5}  {leaf}")
            # The caller of the leaf, which is usually what names the
            # bug: "it is in `read`" says nothing, "it is in `read`
            # under the retention sweep" says where to look.
            parts = stack.split(";")
            if len(parts) > 1:
                lines.append(f"                under {' <- '.join(reversed(parts[-4:-1]))}")
        return "\n".join(lines)


class Sampler:
    """Samples every thread's stack on a background thread.

    A context manager, because a sampler left running outlives the
    thing it was measuring and quietly taxes everything after it.
    """

    def __init__(self, *, interval_s: float = INTERVAL_S, boring: tuple[str, ...] = _BORING) -> None:
        self.interval_s = max(0.001, float(interval_s))
        self._boring = boring
        self.profile = Profile()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Sampler":
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="house-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.profile.seconds = time.monotonic() - self._started

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            for thread_id, frame in sys._current_frames().items():  # noqa: SLF001 -- the whole point
                if thread_id == threading.get_ident():
                    continue          # the sampler is never the answer
                stack = self._stack(frame)
                if stack:
                    self.profile.counts[stack] += 1
                    self.profile.samples += 1

    def _stack(self, frame) -> str:
        parts: list[str] = []
        while frame is not None and len(parts) < 60:
            code = frame.f_code
            name = code.co_filename
            if not any(dull in name for dull in self._boring):
                short = "/".join(name.rsplit("/", 2)[-2:])
                parts.append(f"{short}:{code.co_name}")
            frame = frame.f_back
        return ";".join(reversed(parts))


__all__ = ["INTERVAL_S", "Profile", "Sampler"]
