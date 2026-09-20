"""What an eval is, in this system (stage 4 item 9).

Three harnesses grew up separately -- `simorgh/benchmark` (GAIA, BFCL,
SWE-bench against a model), `tools/trial_suite.py` (seven real tasks
against the whole running system) and `tools/recall_scenario.py` (one
scripted conversation, probed) -- and each had its own idea of a case, a
score and a report. That is why "did this change make Sim better?" had
three answers in three formats, none of them comparable across a week.

An eval here is one shape:

    Case    one thing to try, with what counts as having worked
    Outcome what happened on one attempt: passed, and why not
    Report  a suite's outcomes over N repeats, with an interval

The interval matters more than the number. A seven-case suite that
scores 6 once has told you almost nothing; the same suite run three
times with a bootstrap CI tells you whether 6 is where it lives. Every
suite here reports `passed/total` with a 95% interval over repeats, so a
bless can ask "is this worse than the last one" rather than "is this
number smaller".

**Floor answers do not count.** A case whose reply came from the floor
provider never reached a model, so scoring it measures the fallback, not
the system: it is `skipped`, and a report says how many were skipped
rather than quietly folding them into the denominator.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

#: A case that ended this way never reached a model; it is not a failure
#: and it is not a pass -- it is absent from the denominator.
SKIPPED = "skipped"
PASSED = "passed"
FAILED = "failed"


@dataclass(frozen=True)
class Case:
    """One thing to try."""

    name: str
    #: What the suite does with it; suites define their own vocabulary
    #: ("probe", "trial", "question"), kept for the report's grouping.
    kind: str = ""
    #: Difficulty band, if the suite has one (GAIA's 1..3). Reports are
    #: always per level as well as overall: a suite that answers every
    #: easy case and no hard one is a different system from one that
    #: scores the same spread out.
    level: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class Outcome:
    """What happened on one attempt at one case."""

    case: Case
    status: str = FAILED          # passed | failed | skipped
    seconds: float = 0.0
    cost_usd: float = 0.0
    why: str = ""                 # why it failed, or why it was skipped

    @property
    def passed(self) -> bool:
        return self.status == PASSED

    @property
    def counted(self) -> bool:
        return self.status != SKIPPED


@dataclass
class Report:
    """One suite, over one or more repeats."""

    suite: str
    outcomes: list[Outcome] = field(default_factory=list)
    repeats: int = 1
    seconds: float = 0.0

    @property
    def counted(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.counted]

    @property
    def skipped(self) -> int:
        return len(self.outcomes) - len(self.counted)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.counted if o.passed)

    @property
    def total(self) -> int:
        return len(self.counted)

    @property
    def rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    @property
    def cost_usd(self) -> float:
        return round(sum(o.cost_usd for o in self.outcomes), 4)

    def interval(self) -> tuple[float, float]:
        """A 95% bootstrap interval on the pass rate."""
        return bootstrap_ci([1.0 if o.passed else 0.0 for o in self.counted])

    def by_level(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for outcome in self.counted:
            bucket = out.setdefault(outcome.case.level or "-", [0, 0])
            bucket[0] += 1 if outcome.passed else 0
            bucket[1] += 1
        return {level: (passed, total) for level, (passed, total) in sorted(out.items())}

    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.status == FAILED]

    def as_dict(self) -> dict:
        low, high = self.interval()
        return {
            "suite": self.suite, "passed": self.passed, "total": self.total,
            "rate": round(self.rate, 4), "ci95": [round(low, 4), round(high, 4)],
            "skipped": self.skipped, "repeats": self.repeats,
            "seconds": round(self.seconds, 1), "cost_usd": self.cost_usd,
            "by_level": {k: list(v) for k, v in self.by_level().items()},
            "failures": [{"case": o.case.name, "why": o.why} for o in self.failures()],
            "cases": [{"name": o.case.name, "kind": o.case.kind, "level": o.case.level,
                       "status": o.status, "seconds": o.seconds, "cost_usd": o.cost_usd,
                       "why": o.why} for o in self.outcomes],
        }


def outcomes_from(rows: list[dict]) -> list[Outcome]:
    """The `cases` of an `as_dict` back as outcomes.

    Each repeat of a suite runs in its own process (booting the whole
    system twice in one interpreter segfaults on the torch models), so a
    report has to survive a trip through JSON to be pooled.
    """
    return [Outcome(case=Case(name=str(row.get("name") or ""), kind=str(row.get("kind") or ""),
                              level=str(row.get("level") or "")),
                    status=str(row.get("status") or FAILED), seconds=float(row.get("seconds") or 0.0),
                    cost_usd=float(row.get("cost_usd") or 0.0), why=str(row.get("why") or ""))
            for row in rows]


def bootstrap_ci(values: list[float], *, confidence: float = 0.95, resamples: int = 2000,
                 seed: int = 20260919) -> tuple[float, float]:
    """A percentile bootstrap interval on the mean of `values`.

    Seeded, so two runs of the same outcomes print the same interval: an
    eval report that moves when nothing moved is a report nobody reads
    twice. With fewer than two values there is no interval to give, and
    saying (0, 1) is more honest than inventing a tight one.
    """
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (0.0, 1.0) if values[0] in (0.0, 1.0) else (values[0], values[0])
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples))
    tail = (1.0 - confidence) / 2.0
    low = means[max(0, int(math.floor(tail * resamples)))]
    high = means[min(resamples - 1, int(math.ceil((1.0 - tail) * resamples)) - 1)]
    return (round(low, 4), round(high, 4))


__all__ = ["Case", "FAILED", "Outcome", "PASSED", "Report", "SKIPPED", "bootstrap_ci", "outcomes_from"]
