"""Repeated denials are Sim's problem to notice, not the creator's.

The creator, 2026-09-07, after seeing `denied (policy): ['plan mode:
only read-only tools']` scroll past repeatedly: "what do you expect from
creator, and why sim cannot handle that ... why should [it] take precious
time of creator to review random warning".

The complaint was exactly right, and the specific case was worse than
noise: those denials were a bug telling on itself. Guardian built its
`DecisionContext` without a `tool`, so every tool looked like a writing
tool and plan sessions were denied `list_dir` and `search_code` -- the
only tools they have. Nothing in that needed a human. There was no
decision to make.

The reason it reached a human anyway is that `action.denied` had exactly
one consumer that did anything with it: the Interface, which printed it.
Reflection -- the subsystem whose whole job is noticing patterns and
turning them into work -- did not subscribe to denials at all.

So it does now. The same denial repeating is a pattern like any other,
and it travels the path patterns already travel: `reflect.patterns.found`
-> Planning's intake -> a real task on the backlog. A denial that repeats
is either a rule that needs fixing or a habit Sim needs to drop, and both
of those are jobs it can open for itself.

Deliberately *not* every denial. A one-off denial is Guardian doing its
job correctly and is worth nothing but a log line. Only repetition
carries information, which is why this counts before it speaks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DenialSample:
    tool: str
    reason: str
    layer: str
    ts: float


@dataclass(frozen=True)
class DenialPattern:
    tool: str
    reason: str
    layer: str
    count: int

    @property
    def proposal(self) -> str:
        return (
            f"Guardian denied `{self.tool}` {self.count} times with the same reason "
            f"({self.layer} layer): \"{self.reason}\". Work out whether the rule is wrong for this "
            f"tool or the tool is being asked for in the wrong session, and fix whichever it is."
        )


class DenialMiner:
    """Counts denials per (tool, reason) inside a rolling window and
    reports each group once it repeats enough to mean something.

    Reports at the moment the threshold is crossed rather than waiting
    for the next sleep tick: that tick is six-hourly, so a denial loop
    would otherwise run for hours before anything noticed. Each group is
    reported once per window, so noticing a problem cannot itself become
    a flood.
    """

    def __init__(self, *, window_seconds: float = 3600.0, min_repeats: int = 5) -> None:
        self._window_seconds = window_seconds
        self._min_repeats = max(2, min_repeats)
        self._samples: list[DenialSample] = []
        self._reported: dict[tuple[str, str], float] = {}

    def add(self, *, tool: str, reason: str, layer: str, now: float) -> DenialPattern | None:
        """Record one denial. Returns a pattern the moment this group
        becomes worth raising, and `None` every other time."""
        if not tool or not reason:
            return None  # nothing actionable to name
        self._samples.append(DenialSample(tool, reason, layer, now))
        self._prune(now)

        key = (tool, reason)
        last = self._reported.get(key)
        if last is not None and now - last < self._window_seconds:
            return None  # already raised this window
        group = [s for s in self._samples if (s.tool, s.reason) == key]
        if len(group) < self._min_repeats:
            return None
        self._reported[key] = now
        return DenialPattern(tool=tool, reason=reason, layer=group[-1].layer, count=len(group))

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        self._samples = [s for s in self._samples if s.ts >= cutoff]
        self._reported = {k: t for k, t in self._reported.items() if t >= cutoff}

    def counts(self) -> dict[tuple[str, str], int]:
        """Current window, for `health()` and tests."""
        out: dict[tuple[str, str], int] = {}
        for sample in self._samples:
            key = (sample.tool, sample.reason)
            out[key] = out.get(key, 0) + 1
        return out


__all__ = ["DenialMiner", "DenialPattern", "DenialSample"]
