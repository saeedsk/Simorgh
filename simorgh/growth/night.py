"""The nightly loop (stage 8 item 8).

Everything in this package happens when nobody is asking for anything:
run the evals, see what keeps going wrong, check whether what was
adopted is still working, draft what might help. Left to itself that is
an unbounded amount of work on a paid model, at three in the morning,
with nobody watching -- which is precisely the shape of a bill nobody
meant to run up.

So a night is a fixed list of steps, each run **once**, in order,
cheapest first, against one budget. A step declares what it is likely
to cost before it runs; when the remaining budget will not cover the
next step, the night stops there and says so. Stopping early is the
ordinary outcome, not a failure: the steps are ordered so that what
matters most is also what costs least.

The order is not arbitrary:

    evals        free, and the thing every other judgement rests on
    review       free, and it can only ever REMOVE a policy
    diagnose     free; counting, not asking
    draft        costs money: one lesson phrased by a model (not built)
    propose      free; writing down what the drafting produced (not built)
    measure      costs money: a proposed rule on its held-out suite,
                 with and without it (`measure.py`, off by default)

A step that raises is recorded and the night goes on. One bad step at
3am should not mean no evals ran.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

#: What a night may spend, in dollars, unless configured otherwise.
#: Low on purpose: this runs every night, and a cap nobody notices is a
#: cap that is too high.
DEFAULT_NIGHTLY_USD = 0.50


@dataclass(frozen=True)
class Step:
    """One thing a night does."""

    name: str
    run: Callable[[], Awaitable[object]]
    #: What it is likely to cost. An estimate, not a measurement: the
    #: cap is enforced before a step runs, because a model call cannot
    #: be taken back once it has been made.
    est_usd: float = 0.0


@dataclass
class Ran:
    """What one step did."""

    name: str
    ok: bool = True
    skipped: str = ""      # why, if it did not run
    detail: str = ""
    seconds: float = 0.0
    spent_usd: float = 0.0


@dataclass
class NightReport:
    steps: list[Ran] = field(default_factory=list)
    budget_usd: float = DEFAULT_NIGHTLY_USD
    spent_usd: float = 0.0
    stopped_at: str = ""   # the step the budget ran out on, if any

    @property
    def ran(self) -> list[str]:
        return [s.name for s in self.steps if not s.skipped]

    @property
    def failed(self) -> list[str]:
        return [s.name for s in self.steps if not s.ok]

    def as_dict(self) -> dict:
        return {"ran": self.ran, "failed": self.failed, "stopped_at": self.stopped_at,
                "budget_usd": round(self.budget_usd, 4), "spent_usd": round(self.spent_usd, 4),
                "steps": [{"name": s.name, "ok": s.ok, "skipped": s.skipped, "detail": s.detail[:200],
                           "seconds": round(s.seconds, 2), "spent_usd": round(s.spent_usd, 4)}
                          for s in self.steps]}


async def run_night(steps, *, budget_usd: float = DEFAULT_NIGHTLY_USD, clock=None,
                    spent_so_far: float = 0.0) -> NightReport:
    """Run each step once, in order, until the budget will not cover
    the next one.

    `spent_so_far` is what the day has already cost elsewhere, so the
    cap is a cap on the day rather than on this function.
    """
    now = clock or time.monotonic
    report = NightReport(budget_usd=budget_usd, spent_usd=0.0)
    day_spent = max(0.0, spent_so_far)
    for step in steps:
        remaining = budget_usd - day_spent
        if step.est_usd > remaining:
            # Checked BEFORE the call: a model call cannot be taken
            # back once it has been made, so an after-the-fact cap is
            # not a cap.
            report.steps.append(Ran(name=step.name, skipped=(
                f"would cost about ${step.est_usd:.2f} and ${remaining:.2f} is left")))
            if not report.stopped_at:
                report.stopped_at = step.name
            continue
        started = float(now())
        try:
            result = await step.run()
        except Exception as exc:  # noqa: BLE001 -- one bad step is not a lost night
            report.steps.append(Ran(name=step.name, ok=False, detail=repr(exc),
                                    seconds=float(now()) - started))
            continue
        spent = _spent_of(result, step.est_usd)
        day_spent += spent
        report.spent_usd += spent
        # A step may decline for a reason of its own (nothing to do, not
        # configured, switched off) by returning `{"skipped": why}`; the
        # record says so rather than listing it as having run.
        declined = str(result.get("skipped") or "") if isinstance(result, dict) else ""
        report.steps.append(Ran(name=step.name, skipped=declined, detail=_detail_of(result),
                                seconds=float(now()) - started, spent_usd=spent))
    return report


def _spent_of(result, fallback: float) -> float:
    """What a step actually cost, if it says, else what it estimated.

    A step that reports nothing is assumed to have cost its estimate
    rather than nothing: the cap has to hold even when a step is not
    instrumented, and guessing zero is how a budget quietly stops
    being one.
    """
    if isinstance(result, dict) and "spent_usd" in result:
        try:
            return max(0.0, float(result["spent_usd"]))
        except (TypeError, ValueError):
            return fallback
    return fallback


def _detail_of(result) -> str:
    if isinstance(result, dict):
        return str(result.get("detail") or "")
    return "" if result is None else str(result)[:200]


__all__ = ["DEFAULT_NIGHTLY_USD", "NightReport", "Ran", "Step", "run_night"]
