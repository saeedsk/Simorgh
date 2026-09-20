"""The suites, and how a suite is found (stage 4 item 9).

A suite is a name and an async function that yields `Outcome`s. That is
deliberately the whole interface: the three harnesses this package
merges are wildly different underneath -- one boots the system and types
at it, one runs real tasks in a repo copy, one asks a model questions
from a dataset -- and the only thing they usefully share is what they
report. Anything richer here would be a framework that each of them
fights.

Registered today:

    household     the scripted conversation, probed for what the model saw
    trials        the seven real tasks (`tools/trial_suite.py`), real money
    tooluse       BFCL, through `simorgh/benchmark`
    research      GAIA, through `simorgh/benchmark`
    code          the SWE-bench Verified slice, through `simorgh/benchmark`

`household` is the one the loader's bless runs: it needs no model, no
network and no money, it takes about two seconds, and it measures the
thing that broke most often in the live system -- whether what the
family said reaches the prompt.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from .api import Case, FAILED, Outcome, PASSED, SKIPPED

#: name -> runner. A runner takes no arguments and returns outcomes.
Runner = Callable[[], Awaitable[list[Outcome]]]

#: Suites that cost real money. `run` refuses them without `--paid`,
#: because "I ran the evals" should never be a surprise on a bill.
PAID: frozenset[str] = frozenset({"trials", "tooluse", "research", "code"})


async def household() -> list[Outcome]:
    """The scripted household conversation, one case per probe.

    A probe passes when every fact it expects is in the context the
    model would have reasoned over, and -- for the correction probe --
    the correction is there without the superseded value winning.
    """
    from .scenario import run as run_scenario

    report = await run_scenario()
    outcomes: list[Outcome] = []
    per_probe = report["seconds"] / max(1, len(report["probes"]))
    for probe in report["probes"]:
        name = str(probe["probe"])
        seen, order_ok = bool(probe["seen"]), probe["order_ok"]
        passed = seen and order_ok in (None, True)
        why = ""
        if not seen:
            why = "the fact never reached the prompt"
        elif order_ok is False:
            why = "the superseded value outranked the correction"
        outcomes.append(Outcome(
            case=Case(name=name, kind="probe", level="recall",
                      detail={"turn": probe["turn"], "where": probe["where"]}),
            status=PASSED if passed else FAILED, seconds=round(per_probe, 2), why=why))
    return outcomes


async def trials() -> list[Outcome]:
    """The seven real tasks, in a copy of the repo, against a real model.

    Each trial is a case; a trial that failed for a reason that is the
    harness's fault rather than the system's (`_OUR_FAULT`: a timeout,
    an oversized context, no provider) is skipped, not counted, because
    a provider outage is not a regression in Sim.
    """
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "tools"))
    try:
        # `tools/` is a directory of scripts, not a package, and it is
        # not there in an installed copy. The harness itself stays put:
        # it is how every real bug in this system has been found, and
        # moving 500 lines of it on a day nobody can afford a paid run
        # to re-verify would be trading a working thing for a tidier
        # import. This package owns the *reporting*; that move is noted
        # in CONTRACT.md as still to do.
        from trial_suite import TRIALS, _OUR_FAULT, make_lab, run_one  # noqa: PLC0415, SLF001
    except ImportError as exc:
        return [Outcome(case=Case(name="trials", kind="trial"), status=SKIPPED,
                        why=f"the trial harness is not importable from here: {exc}")]

    root = make_lab(str(repo))
    outcomes: list[Outcome] = []
    for trial in TRIALS:
        result = await run_one(trial, root, timeout_s=900.0)
        ours = any(fault in problem for problem in result.problems for fault in _OUR_FAULT)
        outcomes.append(Outcome(
            case=Case(name=trial.name, kind="trial", level=trial.kind),
            status=SKIPPED if ours else (PASSED if result.ok else FAILED),
            seconds=round(result.seconds, 1), cost_usd=result.cost_usd,
            why="; ".join(result.problems)[:300]))
    return outcomes


def _benchmark_suite(suite: str, level: str = "") -> Runner:
    """A `simorgh/benchmark` suite as an evals suite.

    The benchmark unit already scores each case and keeps its own
    history per model; what it does not do is report an interval over
    repeats, which is the whole reason this package exists. So the
    cases come from there and the statistics from here.
    """

    async def runner() -> list[Outcome]:
        from simorgh.benchmark.datasets import DatasetUnavailable, load  # noqa: PLC0415

        try:
            loaded = load(suite)
        except DatasetUnavailable as exc:
            # A suite that cannot start says so as one skipped case. An
            # eval that silently scores zero is worse than one that
            # admits it never ran.
            return [Outcome(case=Case(name=suite, kind=suite), status=SKIPPED, why=str(exc)[:200])]
        outcomes: list[Outcome] = []
        for case in loaded.cases:
            if level and str(getattr(case, "level", "")) != level:
                continue
            outcomes.append(Outcome(case=Case(name=case.id, kind=suite,
                                              level=str(getattr(case, "level", ""))),
                                    status=SKIPPED,
                                    why="needs a model run: `python -m simorgh.benchmark run`"))
        return outcomes

    return runner


SUITES: dict[str, Runner] = {
    "household": household,
    "trials": trials,
    "tooluse": _benchmark_suite("bfcl"),
    "research": _benchmark_suite("gaia"),
    "code": _benchmark_suite("swebench"),
}


def find(name: str) -> Runner:
    """The suite by name, or a `KeyError` naming the ones that exist."""
    try:
        return SUITES[name]
    except KeyError:
        raise KeyError(f"no suite {name!r}; there is {', '.join(sorted(SUITES))}") from None


async def timed(runner: Runner) -> tuple[list[Outcome], float]:
    started = time.monotonic()
    outcomes = await runner()
    return outcomes, time.monotonic() - started


__all__ = ["PAID", "Runner", "SUITES", "find", "household", "timed", "trials"]
