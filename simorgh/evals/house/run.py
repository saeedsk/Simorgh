"""Running scenarios, one house at a time (stage 11 items 5 and 11).

Each scenario gets its own process. Not tidiness: booting the whole
system more than a few times in one interpreter **segfaults** on the
torch models -- the evals runner learnt this for repeats, and the
scenario pack hit the same wall at the fourth boot. A child process is
also what a scenario should have anyway: an evening that left Sim in a
strange mood must not be the reason the next one fails.

    python -m simorgh.evals house                    # the whole pack
    python -m simorgh.evals house --only live/       # one prefix
    python -m simorgh.evals house --one stage5/remembered-across-a-restart
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ..api import Case, FAILED, Outcome, SKIPPED, outcomes_from

#: Longest a single scenario may take. A restart boots Sim twice and
#: the models are slow the first time.
SCENARIO_TIMEOUT_S = 600.0


async def run_one(scenario) -> list[Outcome]:
    """One scenario, in this process. The child calls this."""
    from .director import Director
    from .sandbox import Sandbox
    from .script import play

    if scenario.needs_model and not _a_real_provider():
        return _skipped_for_the_floor(scenario)
    async with Sandbox(**_sandbox_args()) as box:
        director = Director(box)
        director.scene.room = scenario.room
        if _needs_voices(scenario):
            await _enrol_into(box, director)
        return with_run_summary(await play(scenario, director), director.record)


#: The environment variable an ablation run (`simorgh/evals/ablation.py`)
#: hands each scenario child its preset and model through: a JSON object
#: merged, table by table, over the sandbox's own config. Read here and
#: nowhere else -- the live Sim never sees it.
HOUSE_CONFIG_ENV = "SIMORGH_HOUSE_CONFIG"


def house_config() -> dict:
    """`SIMORGH_HOUSE_CONFIG` as a dict; `{}` when unset.

    Malformed JSON raises rather than falling back: a child that quietly
    ran the default config would score `sim` under the name of `bare`.
    """
    import os

    raw = os.environ.get(HOUSE_CONFIG_ENV, "").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{HOUSE_CONFIG_ENV} must be a JSON object, not {type(value).__name__}")
    return value


def _sandbox_args() -> dict:
    """The paid arguments (if any) with `SIMORGH_HOUSE_CONFIG` on top."""
    from .sandbox import _merge

    args = _paid_sandbox()
    extra = house_config()
    if extra:
        args["config"] = _merge(args.get("config") or {}, extra)
    return args


def run_summary(record) -> dict:
    """What one scenario run cost, read off the bus.

    `steps`: distinct numbered `task.step`s across the run, else the
    `cognition.think` count (the counting `steps_at_most` uses, over the
    whole evening rather than one beat). `cost_usd`: the sum of the
    `cognition.think.reply` costs. `model_answers`, `floor_answers` and
    `model_errors` let an ablation run tell "the model failed the chain"
    from "no model answered at all", which is a skip.
    """
    steps = {(m.payload.get("task_id"), m.payload.get("step_no")) for m in record.of("task.step")}
    replies = record.of("cognition.think.reply")
    return {
        "steps": len(steps) or len(record.of("cognition.think")),
        "cost_usd": round(sum(float(m.payload.get("cost_usd") or 0.0) for m in replies), 6),
        "model_answers": sum(1 for m in replies if not m.payload.get("error") and not m.payload.get("floor")),
        "floor_answers": sum(1 for m in replies if m.payload.get("floor")),
        "model_errors": sum(1 for m in replies if m.payload.get("error")),
    }


def with_run_summary(outcomes: list[Outcome], record) -> list[Outcome]:
    """Every outcome carries the run's summary as `detail["run"]`; the
    first also carries its cost, so a sum over outcomes counts it once."""
    from dataclasses import replace

    summary = run_summary(record)
    out = []
    for index, outcome in enumerate(outcomes):
        detail = {**outcome.case.detail, "run": summary}
        out.append(replace(outcome, case=replace(outcome.case, detail=detail),
                           cost_usd=summary["cost_usd"] if index == 0 else outcome.cost_usd))
    return out


def _skipped_for_the_floor(scenario) -> list[Outcome]:
    """One skipped case naming why, for a scenario only a real model can
    pass. Never a failure: the floor not choosing a tool says nothing
    about Sim."""
    why = (scenario.needs_model_because
           or "needs a model that can judge whether words were for it; "
              "the floor provider answers everything")
    return [Outcome(case=Case(name=scenario.id, kind="scenario", level=scenario.stage,
                              detail={"scenario": scenario.id}),
                    status=SKIPPED, why=why)]


def _a_real_provider() -> bool:
    """Whether a scenario may expect judgement. Off unless asked for:
    a pack that quietly started calling a paid model would be found on
    a bill rather than in a log."""
    import os

    return bool(os.environ.get("SIMORGH_HOUSE_PAID"))


def _paid_sandbox() -> dict:
    """The sandbox's arguments when a real model is allowed.

    Same shape as `house/bench.py`: the live provider order minus the
    floor, and the environment's keys, because a provider without one
    falls quietly through to the floor and the run then measures the
    floor while looking like it measured Sim.
    """
    import os

    if not _a_real_provider():
        return {}
    from .bench import PAID_PROVIDERS, SPEND_CAP_USD

    return {"config": {"cognition": {"provider_order": list(PAID_PROVIDERS),
                                     "max_spend_usd": SPEND_CAP_USD}},
            "secrets": dict(os.environ), "spend_cap_usd": SPEND_CAP_USD}


def _needs_voices(scenario) -> bool:
    """Whether this scenario needs the household in the speaker book.

    Enrolling is twenty sentences through Kokoro and the embedder --
    most of a scenario's runtime -- and a scenario whose every beat
    asks Sim directly never consults the book at all. Checked rather
    than assumed, because the bless subset has to stay quick enough
    that nobody is tempted to switch it off.
    """
    if any(not beat.ask_directly and beat.who for beat in scenario.beats):
        return True
    names = {e.name for beat in scenario.beats for e in beat.expect} | {e.name for e in scenario.expect}
    return any(name.startswith("identified as") for name in names)


async def _enrol_into(box, director) -> None:
    """Put the household in the sandbox's own speaker book, the real
    way. Skipped silently where the models are not installed: a
    scenario about what Sim says should still run on a machine without
    sherpa."""
    from .people import enrol

    import sys

    session = getattr(box.service("voice"), "_session", None)
    book = getattr(session, "_speakers", None)
    if session is None or book is None:
        return
    # Open the speaker engine first. A session only opens it when the
    # book ALREADY has voices -- "a household known by name only pays
    # nothing per turn" -- so a fresh sandbox has no embedder, and
    # enrolling is exactly how it gets its first voice. `voice enroll`
    # does the same thing.
    why = session._open_embedder()  # noqa: SLF001
    if why:
        _say_loudly(box, f"no speaker recognition in this sandbox: {why}")
        return
    try:
        report = await enrol(book, director._tts(), session._embedder)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 -- no models, no identities; the scenario still runs
        _say_loudly(box, f"could not enrol the household: {exc!r}")
        return
    # Loud, not swallowed. This failed silently for an hour and every
    # scenario that turned on knowing who was speaking quietly measured
    # nothing at all (2026-09-20).
    weak = {name: round(score, 2) for name, score in report.scores.items() if score < 0.6}
    if weak:
        _say_loudly(box, f"personas the book barely recognises: {weak}")


def _say_loudly(box, message: str) -> None:
    """Into the record AND onto stderr: a harness that cannot set the
    scene must not let a scenario report a result as though it had."""
    import sys

    box.record.printed_line(f"[house] {message}")
    print(f"[house] {message}", file=sys.stderr)


async def run_pack(scenarios, *, in_child: bool = True) -> list[Outcome]:
    """Every scenario, each in its own process unless told otherwise."""
    out: list[Outcome] = []
    for scenario in scenarios:
        if scenario.needs_model and not _a_real_provider():
            # Decided here rather than in a child: the answer is the
            # same, and a pack of twenty such scenarios should list its
            # reasons in a second rather than boot twenty interpreters.
            out.extend(_skipped_for_the_floor(scenario))
            continue
        out.extend(await _in_a_child(scenario) if in_child else await run_one(scenario))
    return out


def per_scenario(outcomes, scenarios=()) -> list[Outcome]:
    """One outcome per scenario, from its per-expectation outcomes.

    Stage 14's definition of success: a scenario PASSED when every
    expectation on every beat passed; FAILED when any failed (the why is
    the first failure, with its beat); SKIPPED when it could not be
    judged -- the scenario itself was skipped, or an expectation could
    not be evaluated -- so it leaves the denominator rather than
    counting either way. `scenarios` supplies ids that produced nothing
    at all, which report as skipped rather than vanishing.

    The case's `level` is the scenario's category: the second segment
    of `toolchain/<category>/<name>`, else its stage.
    """
    from ..api import PASSED

    grouped: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        sid = str(outcome.case.detail.get("scenario") or outcome.case.name)
        grouped.setdefault(sid, []).append(outcome)
    for scenario in scenarios:
        grouped.setdefault(scenario.id, [])
    out: list[Outcome] = []
    for sid, mine in grouped.items():
        parts = sid.split("/")
        level = parts[1] if len(parts) > 2 else (mine[0].case.level if mine else "")
        failed = [o for o in mine if o.status == FAILED]
        skipped = [o for o in mine if o.status == SKIPPED]
        if failed:
            first = failed[0]
            beat = first.case.detail.get("beat", "")
            status, why = FAILED, f"{first.case.name}: {first.why}" + (f" [{beat}]" if beat else "")
        elif skipped or not mine:
            status, why = SKIPPED, (skipped[0].why if skipped else "the scenario produced no outcome")
        else:
            status, why = PASSED, ""
        out.append(Outcome(case=Case(name=sid, kind="scenario", level=level,
                                     detail={"scenario": sid, "expectations": len(mine)}),
                           status=status, seconds=round(sum(o.seconds for o in mine), 2),
                           cost_usd=round(sum(o.cost_usd for o in mine), 6), why=why[:300]))
    return out


async def _in_a_child(scenario, *, env: dict | None = None) -> list[Outcome]:
    """`env`, when given, is the child's whole environment: an ablation
    run passes a copy of this one plus `SIMORGH_HOUSE_CONFIG`."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "simorgh.evals", "house", "--one", scenario.id, "--json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[3]), env=env)
    try:
        raw, err = await asyncio.wait_for(proc.communicate(), timeout=SCENARIO_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        return [Outcome(case=Case(name=scenario.id, kind="scenario", level=scenario.stage),
                        status=FAILED, why=f"the scenario did not finish in {SCENARIO_TIMEOUT_S:.0f}s")]
    text = raw.decode("utf-8", "replace")
    try:
        return outcomes_from(json.loads(text[text.index("["):text.rindex("]") + 1]))
    except (ValueError, IndexError):
        tail = (err.decode("utf-8", "replace").strip() or text)[-300:]
        # A scenario whose house fell over is one skipped case saying
        # so, never a silently smaller denominator.
        return [Outcome(case=Case(name=scenario.id, kind="scenario", level=scenario.stage),
                        status=SKIPPED, why=f"the house did not come up: {tail}")]


async def run_with_timing(scenario):
    """One scenario, plus where its seconds went."""
    from .director import Director
    from .sandbox import Sandbox
    from .script import play
    from .timing import from_record

    async with Sandbox() as box:
        director = Director(box)
        director.scene.room = scenario.room
        if _needs_voices(scenario):
            await _enrol_into(box, director)
        outcomes = await play(scenario, director)
        return outcomes, from_record(director.record)


def as_json(outcomes) -> str:
    return json.dumps([{"name": o.case.name, "kind": o.case.kind, "level": o.case.level,
                        "status": o.status, "seconds": o.seconds, "cost_usd": o.cost_usd,
                        "why": o.why, "detail": o.case.detail} for o in outcomes])


__all__ = ["HOUSE_CONFIG_ENV", "SCENARIO_TIMEOUT_S", "as_json", "house_config", "per_scenario",
           "run_one", "run_pack", "run_summary", "with_run_summary"]
