"""Running the code-first suite (stage 19 item 8).

Two ways, two suite names:

    code_first_scripted   free, offline, a second: the two scripted models
                          (`models.py`) over Sim's real tools. A case PASSES
                          when the computing model is exact and ran a
                          program, and the page reader is wrong and did
                          not -- i.e. the case is a fair question: the
                          data, the expected answer and the scorer agree,
                          and one page cannot answer it.
    code_first            paid: Sim itself, one sandbox per case, each in
                          its own process. A case PASSES when the answer is
                          exact; whether a `run_analysis` action ran is in
                          `detail["method"]` and counted separately.

    python -m simorgh.evals run code_first_scripted
    python -m simorgh.evals run code_first --paid
    python -m simorgh.evals code-first --scripted          # both models' answers, per case
    python -m simorgh.evals code-first --paid              # Sim, with the method column
    python -m simorgh.evals code-first --one mail/latest-per-sender --paid --json

The Sim run is the household sandbox (`house/sandbox.py`) with the
house's paid arguments (`house/run.py::_sandbox_args`: the live provider
order minus the floor, the environment's keys, the spend cap), and
`SIMORGH_HOUSE_CONFIG` merged on top -- which is how a before/after run
turns the stage-19 switches off (`[execution] workbench = false`,
`[orchestration] supervisor_approach = false`). The World is wired in by
the tools' own injection seams (`_PimTool._given`) and by two files in
the sandbox's OWN repo clone; a sandbox whose repo root is this checkout
is refused rather than written into.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from ..api import Case, FAILED, Outcome, PASSED, SKIPPED, outcomes_from
from .cases import CASES, CodeFirstCase, by_id
from .method import method_of, ran_program, tally
from .world import ACCOUNT, DEFAULT_SEED, TEST_ANCHOR, World, build

#: Longest one Sim case may take: a program, a decomposition or a
#: background crew is minutes, not seconds.
CASE_TIMEOUT_S = 900.0
#: The seed a run uses, overridable for a second household of the same shape.
SEED_ENV = "SIMORGH_CODEFIRST_SEED"
#: Why the Sim run skips without a model.
_WHY_FLOOR = "needs a model that reads and computes; the floor provider proposes nothing (run with --paid)"


def _seed() -> int:
    return int(os.environ.get(SEED_ENV) or DEFAULT_SEED)


def _case(case: CodeFirstCase, **detail) -> Case:
    return Case(name=case.id, kind="code_first", level=case.domain,
                detail={"domain": case.domain, "shape": case.shape, **detail})


# ------------------------------------------------------------------ the scripted check
async def scripted_one(case: CodeFirstCase, model: str, world: World) -> dict:
    """One scripted model on one case: its answer, score and method."""
    from .models import MODELS, Bench

    with tempfile.TemporaryDirectory(prefix="simorgh-codefirst-") as tmp:
        bench = Bench(world, tmp)
        attempt = await MODELS[model](case.id, bench)
    score = case.score(attempt.text, world)
    return {"exact": score.exact, "got": score.got, "why": score.why, "method": method_of(attempt.tools),
            "tools": tally(attempt.tools), "answer": attempt.text}


async def scripted_outcomes(*, seed: int | None = None, anchor=None) -> list[Outcome]:
    """`code_first_scripted`: is every case a fair question?"""
    world = build(seed if seed is not None else _seed(), anchor or TEST_ANCHOR)
    out = []
    for case in CASES:
        started = time.monotonic()
        computer = await scripted_one(case, "computer", world)
        reader = await scripted_one(case, "reader", world)
        problems = []
        if not computer["exact"]:
            problems.append(f"the computing model was wrong ({computer['got']}): {computer['why']}")
        if computer["method"] != "program":
            problems.append("the computing model's run_analysis was not counted")
        if reader["exact"]:
            problems.append("one page answered it: the case does not need a program")
        if reader["method"] != "reading":
            problems.append("the page reader was counted as a program")
        out.append(Outcome(
            case=_case(case, seed=world.seed, anchor=world.anchor.isoformat(),
                       computer={k: computer[k] for k in ("exact", "got", "method")},
                       reader={k: reader[k] for k in ("exact", "got", "method")}),
            status=FAILED if problems else PASSED, seconds=round(time.monotonic() - started, 2),
            why="; ".join(problems)[:300] if problems else f"page reader {reader['got']}, program {computer['got']}"))
    return out


# ------------------------------------------------------------------ Sim
def wire(box, world: World) -> Path:
    """Give the booted sandbox's tools this World. Returns the repo root
    the two files were written under."""
    from simorgh.execution.config import find_repo_root

    execution = box.service("execution")
    if execution is None:
        raise RuntimeError("the sandbox has no execution service")
    connectors = {f"{ACCOUNT}-mail": world.mailbox(), f"{ACCOUNT}-calendar": world.calendar()}
    wired = []
    for tool in execution._registry.values():  # noqa: SLF001 -- the domain tools' own seam, as the house does
        if getattr(tool, "name", "") in ("cal_list", "mail_search", "mail_read") and hasattr(tool, "_given"):
            tool._given = connectors  # noqa: SLF001
            wired.append(tool.name)
    if len(wired) < 3:
        raise RuntimeError(f"only {wired} could be given the World; the pim tools are not registered")
    root = Path(execution._config.repo_root).resolve()  # noqa: SLF001
    if root == find_repo_root().resolve():
        raise RuntimeError(f"the sandbox's repo root is this checkout ({root}); refusing to write the World "
                           f"into it -- run with --paid (the sandbox then clones) or name [execution] repo_root")
    world.install(root)
    return root


async def sim_one(case: CodeFirstCase, *, seed: int | None = None, timeout_s: float = CASE_TIMEOUT_S,
                  config: dict | None = None, anchor=None) -> Outcome:
    """One case, Sim answering, in this process."""
    from ..house.director import Director
    from ..house.run import _a_real_provider, _sandbox_args, ledger_facts
    from ..house.sandbox import Sandbox, _merge

    if not _a_real_provider() and config is None:
        return Outcome(case=_case(case), status=SKIPPED, why=_WHY_FLOOR)
    world = build(seed if seed is not None else _seed(), anchor)
    args = _sandbox_args()
    if config:
        args["config"] = _merge(args.get("config") or {}, config)
    started = time.monotonic()
    async with Sandbox(**args) as box:
        wire(box, world)
        director = Director(box)
        mark = director.now()
        question = case.question(world)
        typing = asyncio.ensure_future(director.type(question, wait=False))
        answer, floor = await _answer(director, mark, timeout_s)
        typing.cancel()
        tools = [str(m.payload.get("tool") or "") for m in box.record.of("action.proposed", since=mark)]
        facts = await ledger_facts(box)
    seconds = round(time.monotonic() - started, 1)
    spend = float(facts.get("spend_usd") or 0.0)
    detail = {"seed": world.seed, "anchor": world.anchor.isoformat(), "method": method_of(tools),
              "program": ran_program(tools), "tools": tally(tools), "answer": (answer or "")[:2000]}
    if answer is None:
        return Outcome(case=_case(case, **detail), status=FAILED, seconds=seconds, cost_usd=spend,
                       why=f"no answer in {timeout_s:.0f}s")
    if floor:
        return Outcome(case=_case(case, **detail), status=SKIPPED, seconds=seconds, cost_usd=spend,
                       why="the floor provider answered: no model was reached")
    score = case.score(answer, world)
    detail.update(exact=score.exact, got=score.got)
    how = f"by {detail['method']}"
    return Outcome(case=_case(case, **detail), status=PASSED if score.exact else FAILED, seconds=seconds,
                   cost_usd=spend, why=(f"exact, {how}" if score.exact else f"{score.got}, {how}: {score.why}")[:300])


async def _answer(director, mark: float, timeout_s: float) -> tuple[str | None, bool]:
    """The turn's reply, plus any background report delivered for it
    (stage 18: a crew sent to the background answers by `ui.notice`).
    `(None, False)` when nothing came in time."""
    deadline = time.monotonic() + timeout_s
    turn = None
    while time.monotonic() < deadline:
        turn = next((m for m in director.record.of("turn.completed", since=mark)
                     if m.payload.get("channel") == "cli"), None)
        if turn is not None:
            break
        await asyncio.sleep(0.2)
    if turn is None:
        return None, False
    text = str(turn.payload.get("text") or "")
    floor = bool(turn.payload.get("floor"))
    if director.record.of("crew.spawned", since=mark):
        # Something was sent to work in the background: wait for its
        # report, which is the answer the turn promised.
        while time.monotonic() < deadline:
            notices = [m for m in director.record.of("ui.notice", since=mark) if m.payload.get("source") == "crew"]
            if notices:
                text += "\n\n" + "\n\n".join(str(m.payload.get("text") or "") for m in notices)
                floor = False
                break
            await asyncio.sleep(0.5)
    return text, floor


async def sim_outcomes() -> list[Outcome]:
    """`code_first`: every case, each in its own process (two whole Sims
    in one interpreter is the segfault the house runner forks around)."""
    from ..house.run import _a_real_provider

    if os.environ.get("SIMORGH_EVALS_PAID"):
        os.environ["SIMORGH_HOUSE_PAID"] = "1"
    if not _a_real_provider():
        return [Outcome(case=_case(c), status=SKIPPED, why=_WHY_FLOOR) for c in CASES]
    out = []
    for case in CASES:
        out.extend(await _in_a_child(case))
    return out


async def _in_a_child(case: CodeFirstCase) -> list[Outcome]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "simorgh.evals", "code-first", "--one", case.id, "--json", "--paid",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(Path(__file__).resolve().parents[3]))
    try:
        raw, err = await asyncio.wait_for(proc.communicate(), timeout=CASE_TIMEOUT_S + 120)
    except asyncio.TimeoutError:
        proc.kill()
        return [Outcome(case=_case(case), status=FAILED, why=f"the case did not finish in {CASE_TIMEOUT_S:.0f}s")]
    text = raw.decode("utf-8", "replace")
    try:
        return outcomes_from(json.loads(text[text.index("["):text.rindex("]") + 1]))
    except (ValueError, IndexError):
        tail = (err.decode("utf-8", "replace").strip() or text)[-300:]
        return [Outcome(case=_case(case), status=SKIPPED, why=f"the sandbox did not come up: {tail}")]


# ------------------------------------------------------------------ the command
def _as_json(outcomes: list[Outcome]) -> str:
    return json.dumps([{"name": o.case.name, "kind": o.case.kind, "level": o.case.level, "status": o.status,
                        "seconds": o.seconds, "cost_usd": o.cost_usd, "why": o.why, "detail": o.case.detail}
                       for o in outcomes], default=str)


def table(outcomes: list[Outcome], *, scripted: bool = False) -> str:
    counted = [o for o in outcomes if o.status != SKIPPED]
    passed = sum(1 for o in counted if o.status == PASSED)
    programs = sum(1 for o in counted if o.case.detail.get("program"))
    head = f"code_first{' (scripted)' if scripted else ''}: {passed}/{len(counted)} exact"
    if not scripted:
        head += f", {programs}/{len(counted)} by a program"
    lines = [head]
    for o in outcomes:
        if scripted:
            r, c = o.case.detail.get("reader", {}), o.case.detail.get("computer", {})
            lines.append(f"  {o.case.name:30} {o.status:7} reader {r.get('got', '-'):>9}  program {c.get('got', '-'):>9}"
                         + (f"  {o.why[:60]}" if o.status != PASSED else ""))
        else:
            lines.append(f"  {o.case.name:30} {o.status:7} {o.case.detail.get('method', '-'):8} "
                         f"{o.seconds:>6.1f}s  {o.why[:70]}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    import argparse
    import contextlib
    import io

    ap = argparse.ArgumentParser(prog="python -m simorgh.evals code-first", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scripted", action="store_true", help="the two scripted models, offline and free")
    ap.add_argument("--one", default="", help="one case by id, in this process")
    ap.add_argument("--paid", action="store_true", help="let Sim reach a real model (costs money)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.seed is not None:
        os.environ[SEED_ENV] = str(args.seed)
    if args.scripted:
        outcomes = asyncio.run(scripted_outcomes())
        if args.one:
            outcomes = [o for o in outcomes if o.case.name == args.one]
        print(_as_json(outcomes) if args.json else table(outcomes, scripted=True))
        return 0 if all(o.status == PASSED for o in outcomes) else 1
    if args.paid:
        os.environ["SIMORGH_HOUSE_PAID"] = "1"
    if args.one:
        case = by_id(args.one)
        if case is None:
            print(f"no case {args.one!r}; there is {', '.join(c.id for c in CASES)}", file=sys.stderr)
            return 2
        with contextlib.redirect_stdout(io.StringIO()):
            outcomes = [asyncio.run(sim_one(case))]
    else:
        if not args.paid:
            print("the Sim run calls a real model and costs money; pass --paid, or --scripted for the free check",
                  file=sys.stderr)
            return 2
        outcomes = asyncio.run(sim_outcomes())
    print(_as_json(outcomes) if args.json else table(outcomes))
    return 0 if all(o.status != FAILED for o in outcomes) else 1


__all__ = ["CASE_TIMEOUT_S", "SEED_ENV", "main", "scripted_outcomes", "sim_one", "sim_outcomes", "table", "wire"]
