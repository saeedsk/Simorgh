"""The benchmarks, scored through the sandbox (stage 11 item 7).

`simorgh/benchmark` has known how to ask a case and score an answer
since 2026-09-10, and `simorgh/evals` has listed those cases as
`skipped: needs a model run` ever since -- two halves of a measurement
that never met, which is this project's favourite bug and was sitting
inside its measuring equipment.

They meet here. A sandbox boots a whole Sim; the benchmark Runner
takes its bus and asks each case exactly as `python -m
simorgh.benchmark run` would; each `CaseResult` becomes an `Outcome`,
so repeats get the bootstrap interval the evals report already knows
how to compute.

Two things are deliberate:

**It costs money, and says so.** The floor provider cannot answer a
BFCL case, so a free run scores near zero and that number means
nothing about Sim. The suites stay in `PAID`, a run without `--paid`
refuses, and a `--limit` keeps a first look at a handful of cases
rather than a dataset.

**A wrong answer is a failure, a case we could not ask is a skip.** A
missing attachment or a crashed harness scored as wrong would make
Sim look worse the more of the dataset was unavailable, which is
exactly backwards.
"""

from __future__ import annotations

from ..api import Case, FAILED, Outcome, PASSED, SKIPPED

#: How many cases a run takes when nobody says. Small on purpose: the
#: point of the first run is that the wire works.
DEFAULT_LIMIT = 5

#: What one scored run may spend, in dollars. A cap rather than a
#: budget: the first paid run of a suite is there to show the scoring
#: works, and nobody should find out how much it cost from a bill.
SPEND_CAP_USD = 0.50

#: Who answers a paid case. The live order minus `floor`, because a
#: floor answer inside a paid run is a case that silently did not
#: happen: the runner skips it, and five skips look identical whether
#: the dataset was missing or every provider was.
PAID_PROVIDERS: tuple[str, ...] = ("together", "gemini", "claude_code_cli")


async def score(suite: str, *, limit: int = DEFAULT_LIMIT, level: str = "",
                model: str = "", config: dict | None = None, paid: bool = False,
                dialect: str = "", spend_cap_usd: float = SPEND_CAP_USD) -> list[Outcome]:
    """Run `suite`'s cases through a sandboxed Sim and score them.

    Without `paid` the sandbox keeps its floor provider, every case
    comes back `skipped: not the model` (the runner's own guard), and
    the run proves the wire rather than Sim. With `paid` the ordinary
    provider order applies and the day budget is capped at
    `spend_cap_usd` for this sandbox alone.
    """
    from simorgh.benchmark.datasets import DatasetUnavailable, load
    from simorgh.benchmark.runner import Runner

    from .sandbox import Sandbox

    try:
        loaded = load(suite)
    except DatasetUnavailable as exc:
        return [Outcome(case=Case(name=suite, kind=suite), status=SKIPPED, why=str(exc)[:200])]

    cases = [c for c in loaded.cases if not level or str(getattr(c, "level", "")) == level]
    cases = cases[:limit] if limit else cases
    if not cases:
        return [Outcome(case=Case(name=suite, kind=suite), status=SKIPPED,
                        why=f"no cases in {suite}" + (f" at level {level}" if level else ""))]

    secrets = None
    if paid:
        # Out of the sandbox's floor-only default and back to the real
        # order, with a day budget this run cannot exceed -- and with
        # the environment's keys, because a provider with no key falls
        # through to the floor and the floor's answers are skipped,
        # which reads as "nothing ran" rather than "nothing could".
        import os

        cognition = {"provider_order": list(PAID_PROVIDERS), "max_spend_usd": float(spend_cap_usd)}
        if dialect:
            # Stage 2's open question, and the reason this argument
            # exists: markers scored 6/7 against native's 6/7 in a
            # trial round, and a tie is not a win, so nothing was
            # flipped. A tool-use benchmark is the harness that was
            # missing -- the same cases, the same model, one setting
            # apart (stage 2's definition of done).
            cognition["providers"] = {name: {"tool_dialect": dialect} for name in PAID_PROVIDERS}
        config = {**(config or {}), "cognition": cognition}
        secrets = dict(os.environ)
    async with Sandbox(config=config, spend_cap_usd=spend_cap_usd, secrets=secrets) as sandbox:
        runner = Runner(sandbox.kernel.bus, repo_root=sandbox.data_dir)
        outcomes: list[Outcome] = []
        for case in cases:
            result = await runner.run_case(case)
            outcomes.append(_outcome(suite, result))
    return outcomes


def _outcome(suite: str, result) -> Outcome:
    case = Case(name=result.case_id, kind=suite, level=result.level or "",
                detail={"cost_usd": round(result.cost_usd, 4), "steps": result.steps,
                        "answer": (result.answer or "")[:200],
                        "expected": (result.expected or "")[:200]})
    if result.skipped:
        return Outcome(case=case, status=SKIPPED, seconds=result.seconds,
                       why=result.error or "the case could not be asked")
    if result.correct:
        return Outcome(case=case, status=PASSED, seconds=result.seconds)
    why = result.error or f"answered {(result.answer or '(nothing)')[:80]!r}"
    return Outcome(case=case, status=FAILED, seconds=result.seconds, why=why)


def suite_runner(suite: str, *, level: str = "", limit: int = DEFAULT_LIMIT, paid: bool = False):
    """A `suites.Runner` for the evals registry."""

    async def runner() -> list[Outcome]:
        return await score(suite, limit=limit, level=level, paid=paid)

    return runner


__all__ = ["DEFAULT_LIMIT", "PAID_PROVIDERS", "SPEND_CAP_USD", "score", "suite_runner"]
