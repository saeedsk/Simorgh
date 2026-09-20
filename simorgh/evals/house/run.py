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
        return [Outcome(case=Case(name=scenario.id, kind="scenario", level=scenario.stage),
                        status=SKIPPED,
                        why="needs a model that can judge whether words were for it; "
                            "the floor provider answers everything")]
    async with Sandbox() as box:
        director = Director(box)
        director.scene.room = scenario.room
        if _needs_voices(scenario):
            await _enrol_into(box, director)
        return await play(scenario, director)


def _a_real_provider() -> bool:
    """Whether a scenario may expect judgement. Off unless asked for:
    a pack that quietly started calling a paid model would be found on
    a bill rather than in a log."""
    import os

    return bool(os.environ.get("SIMORGH_HOUSE_PAID"))


def _needs_voices(scenario) -> bool:
    """Whether any beat speaks into the room rather than asking Sim."""
    return True     # enrolling costs a few seconds and every scenario benefits from real identities


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
        out.extend(await _in_a_child(scenario) if in_child else await run_one(scenario))
    return out


async def _in_a_child(scenario) -> list[Outcome]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "simorgh.evals", "house", "--one", scenario.id, "--json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parents[3]))
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


def as_json(outcomes) -> str:
    return json.dumps([{"name": o.case.name, "kind": o.case.kind, "level": o.case.level,
                        "status": o.status, "seconds": o.seconds, "cost_usd": o.cost_usd,
                        "why": o.why} for o in outcomes])


__all__ = ["SCENARIO_TIMEOUT_S", "as_json", "run_one", "run_pack"]
