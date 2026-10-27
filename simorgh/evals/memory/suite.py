"""The memory suite: every system, the same month, the same questions (stage 15 item 4).

    python -m simorgh.evals memory --systems native,native_graph          # free, seconds
    python -m simorgh.evals memory --systems native,native_graph,graphiti,cognee --dry-run
    python -m simorgh.evals memory --systems native,graphiti,cognee --paid --cap-usd 2

Each system is fed the corpus (`corpus.episodes()`), then asked every
question; a question passes when its block holds what `corpus` says it
must and nothing it must not (`score.check`). The report is per system and
per category, each with a 95% bootstrap interval, plus -- for a sidecar --
what ingestion cost per episode and how long a recall took.

A system that cannot run reports every case `skipped` with the reason,
never failed: `native_graph` before stage 15 items 1-3 merge, a sidecar
whose package is absent, a sidecar without `--paid` or a key. A sidecar
that reaches its `--cap-usd` stops, and its unasked cases are skipped
saying so.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field

from ..api import Case, FAILED, Outcome, PASSED, Report, SKIPPED, bootstrap_ci
from .corpus import CATEGORIES, QUESTIONS, Episode, Question, episodes
from .meter import CapReached
from .score import check

#: Every system the suite knows, in report order.
SYSTEMS: tuple[str, ...] = ("native", "native_graph", "graphiti", "cognee")
FREE: frozenset[str] = frozenset({"native", "native_graph"})

#: Said in every report, because it decides how to read the numbers.
FAIRNESS = ("native systems are given each episode's facts as a perfect extractor would write them "
            "(the floor provider extracts nothing), so they measure recall only; the sidecars extract "
            "from the text themselves, so their numbers include extraction")


@dataclass
class SystemRun:
    name: str
    report: Report
    skipped: str = ""                  # why the whole system did not run
    ingestion: dict = field(default_factory=dict)
    recall_ms: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)

    def by_category(self) -> dict[str, dict]:
        out = {}
        for category in CATEGORIES:
            counted = [o for o in self.report.counted if o.case.kind == category]
            low, high = bootstrap_ci([1.0 if o.passed else 0.0 for o in counted])
            out[category] = {"passed": sum(o.passed for o in counted), "total": len(counted),
                             "ci95": [low, high]}
        return out

    def as_dict(self) -> dict:
        return {"system": self.name, "skipped": self.skipped, "summary": self.report.as_dict(),
                "by_category": self.by_category(), "ingestion": self.ingestion,
                "recall_ms": self.recall_ms, "notes": self.notes}


def make(name: str, *, paid: bool = False, cap_usd: float = 0.0):
    """The system by name."""
    if name == "native":
        from .native import Native

        return Native()
    if name == "native_graph":
        from .native import NativeGraph

        return NativeGraph()
    if name == "graphiti":
        from .graphiti_side import GraphitiSide

        return GraphitiSide(paid=paid, cap_usd=cap_usd)
    if name == "cognee":
        from .cognee_side import CogneeSide

        return CogneeSide(paid=paid, cap_usd=cap_usd)
    raise KeyError(f"no memory system {name!r}; there is {', '.join(SYSTEMS)}")


def _case(question: Question, system: str) -> Case:
    return Case(name=question.id, kind=question.category, level=question.category,
                detail={"system": system, "asker": question.asker, "question": question.text})


def _all_skipped(name: str, questions, why: str) -> list[Outcome]:
    return [Outcome(case=_case(q, name), status=SKIPPED, why=why) for q in questions]


async def run_system(system, month: list[Episode], questions=QUESTIONS) -> SystemRun:
    """Feed one system the month, ask it every question, score each block."""
    name = system.name
    report = Report(suite=f"memory:{name}")
    why = system.skip_reason()
    if why:
        report.outcomes = _all_skipped(name, questions, why)
        return SystemRun(name=name, report=report, skipped=why)
    meter = getattr(system, "meter", None)
    started = time.monotonic()
    rows: list[dict] = []
    stopped = ""
    try:
        await system.open()
    except Exception as exc:  # noqa: BLE001 -- a system that will not start is skipped, saying why
        why = f"{name} did not start: {exc!r}"[:300]
        report.outcomes = _all_skipped(name, questions, why)
        return SystemRun(name=name, report=report, skipped=why)
    try:
        for episode in month:
            before = meter.snapshot() if meter is not None else (0, 0, 0, 0.0)
            t0 = time.monotonic()
            try:
                await system.ingest(episode)
            except CapReached as exc:
                stopped = f"cap reached during ingestion at episode {episode.index}: {exc}"
                break
            if meter is not None:
                after = meter.snapshot()
                rows.append({"episode": episode.index, "calls": after[0] - before[0],
                             "tokens_in": after[1] - before[1], "tokens_out": after[2] - before[2],
                             "usd": round(after[3] - before[3], 6), "seconds": round(time.monotonic() - t0, 3)})
        latencies: list[float] = []
        for question in questions:
            if stopped:
                # A half-fed graph's score would be a number about the cap.
                report.outcomes.append(Outcome(case=_case(question, name), status=SKIPPED, why=stopped))
                continue
            t0 = time.monotonic()
            try:
                lines = await system.context(question)
            except CapReached as exc:
                stopped = f"cap reached while asking: {exc}"
                report.outcomes.append(Outcome(case=_case(question, name), status=SKIPPED, why=stopped))
                continue
            seconds = time.monotonic() - t0
            latencies.append(seconds)
            passed, reason = check(question, lines)
            report.outcomes.append(Outcome(case=_case(question, name), status=PASSED if passed else FAILED,
                                           seconds=round(seconds, 4), why=reason))
    finally:
        await system.close()
    report.seconds = time.monotonic() - started
    run = SystemRun(name=name, report=report, notes=dict(getattr(system, "notes", {}) or {}))
    if meter is not None:
        from .sidecar import Ingestion

        run.ingestion = Ingestion(rows=rows, stopped=stopped).summary()
        run.ingestion["total_usd"] = round(meter.usd, 4)
    if latencies:
        ordered = sorted(latencies)
        run.recall_ms = {"p50": round(ordered[len(ordered) // 2] * 1000, 1),
                         "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 1)}
    return run


async def run(systems: list[str], *, paid: bool = False, cap_usd: float = 0.0,
              total_episodes: int = 150) -> list[SystemRun]:
    month = episodes(total_episodes)
    runs = []
    for name in systems:
        # One at a time: two sidecars at once would share nothing but the
        # rate limit, and their per-episode seconds would measure each other.
        runs.append(await run_system(make(name, paid=paid, cap_usd=cap_usd), month))
    return runs


def dry_run(systems: list[str], *, cap_usd: float, total_episodes: int = 150) -> dict:
    """The matrix and what the paid part would cost, calling nothing."""
    month = episodes(total_episodes)
    rows = []
    for name in systems:
        system = make(name, paid=True, cap_usd=cap_usd)
        row = {"system": name, "episodes": len(month), "questions": len(QUESTIONS), "cost": "free"}
        if name in FREE:
            row["runnable"] = system.skip_reason() or "yes"
        else:
            lib, why = system.load()
            row["runnable"] = "yes" if lib is not None else f"{why}; {system.install}"
            row["estimate"] = system.estimate(len(month), len(QUESTIONS))
            row["cost"] = f"~${row['estimate']['usd']:.2f} (cap ${cap_usd:.2f})"
        rows.append(row)
    categories = {c: sum(1 for q in QUESTIONS if q.category == c) for c in CATEGORIES}
    return {"systems": rows, "categories": categories, "fairness": FAIRNESS}


def table(runs: list[SystemRun]) -> str:
    """One row per system, one column per category, each with its interval."""
    head = f"{'system':<13}" + "".join(f"{c:<22}" for c in CATEGORIES) + "overall"
    lines = [head]
    for r in runs:
        if r.skipped:
            lines.append(f"{r.name:<13}skipped: {r.skipped}")
            continue
        cells = []
        for c, row in r.by_category().items():
            low, high = row["ci95"]
            cells.append(f"{row['passed']}/{row['total']} ({low:.0%}-{high:.0%})".ljust(22))
        low, high = r.report.interval()
        lines.append(f"{r.name:<13}" + "".join(cells)
                     + f"{r.report.passed}/{r.report.total} ({low:.0%}-{high:.0%})"
                     + (f", {r.report.skipped} skipped" if r.report.skipped else ""))
    for r in runs:
        extra = []
        if r.recall_ms:
            extra.append(f"recall p50 {r.recall_ms['p50']} ms, p95 {r.recall_ms['p95']} ms")
        if r.ingestion:
            i = r.ingestion
            extra.append(f"ingestion {i['episodes']} episodes, {i['calls_per_episode']} calls and "
                         f"${i['usd_per_episode']:.4f} per episode, p50 {i['seconds_per_episode_p50']} s, "
                         f"total ${i['total_usd']:.4f}" + (f" -- {i['stopped']}" if i['stopped'] else ""))
        extra.extend(f"{k}: {v}" for k, v in r.notes.items())
        if extra:
            lines.append(f"  {r.name}: " + "; ".join(extra))
    lines.append(f"note: {FAIRNESS}")
    return "\n".join(lines)


async def outcomes() -> list[Outcome]:
    """The `memory` entry in `suites.SUITES`: the free systems, pooled.

    Free whatever flags the runner passes its child (it always passes
    `--paid`): the sidecars are reached only through `python -m
    simorgh.evals memory`.
    """
    runs = await run(sorted(FREE))
    return [o for r in runs for o in r.report.outcomes]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m simorgh.evals memory", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default="native,native_graph",
                    help=f"comma-separated, of {', '.join(SYSTEMS)}")
    ap.add_argument("--paid", action="store_true", help="let a sidecar call a real model (costs money)")
    ap.add_argument("--cap-usd", type=float, default=0.0,
                    help="hard cap per sidecar, counted from the provider's usage fields; required with --paid")
    ap.add_argument("--dry-run", action="store_true", help="list the matrix and the estimated cost; call nothing")
    ap.add_argument("--episodes", type=int, default=150, help="size of the month (default 150)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--record", default="", metavar="DATA_DIR",
                    help="append each system's report to DATA_DIR/evals.jsonl")
    args = ap.parse_args(argv)
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    unknown = [s for s in systems if s not in SYSTEMS]
    if unknown:
        ap.error(f"no memory system {', '.join(unknown)}; there is {', '.join(SYSTEMS)}")
    if args.dry_run:
        plan = dry_run(systems, cap_usd=args.cap_usd, total_episodes=args.episodes)
        if args.json:
            print(json.dumps(plan, indent=1))
        else:
            print(f"memory suite: {plan['systems'][0]['episodes'] if plan['systems'] else 0} episodes, "
                  f"{len(QUESTIONS)} questions: "
                  + ", ".join(f"{c} {n}" for c, n in plan["categories"].items()))
            for row in plan["systems"]:
                print(f"  {row['system']:<13} {row['cost']:<24} runnable: {row['runnable']}")
            print(f"note: {plan['fairness']}")
        return 0
    paid_systems = [s for s in systems if s not in FREE]
    if args.paid and paid_systems and args.cap_usd <= 0:
        print("--paid needs --cap-usd above zero: a sidecar never runs without a hard cap", flush=True)
        return 2
    runs = asyncio.run(run(systems, paid=args.paid, cap_usd=args.cap_usd, total_episodes=args.episodes))
    if args.record:
        from ..runner import record

        for r in runs:
            record(r.report, data_dir=args.record)
    if args.json:
        print(json.dumps([r.as_dict() for r in runs], indent=1))
    else:
        print(table(runs))
    # A measurement, not a gate: native is expected to miss aliases and
    # hops. Non-zero only when nothing at all ran.
    return 0 if any(not r.skipped for r in runs) else 1


__all__ = ["FAIRNESS", "FREE", "SYSTEMS", "SystemRun", "dry_run", "main", "make", "outcomes", "run",
           "run_system", "table"]
