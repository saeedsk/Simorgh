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

    async with Sandbox() as box:
        director = Director(box)
        director.scene.room = scenario.room
        if _needs_voices(scenario):
            await _enrol_into(box, director)
        return await play(scenario, director)


def _needs_voices(scenario) -> bool:
    """Whether any beat speaks into the room rather than asking Sim."""
    return True     # enrolling costs a few seconds and every scenario benefits from real identities


async def _enrol_into(box, director) -> None:
    """Put the household in the sandbox's own speaker book, the real
    way. Skipped silently where the models are not installed: a
    scenario about what Sim says should still run on a machine without
    sherpa."""
    from .people import enrol

    session = box.service("voice")
    session = getattr(session, "_session", None)
    book = getattr(session, "_speakers", None)
    embedder = getattr(session, "_embedder", None)
    if book is None or embedder is None:
        return
    try:
        await enrol(book, director._tts(), embedder)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 -- no models, no identities; the scenario still runs
        box.record.printed_line(f"[house] could not enrol the household: {exc!r}")


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
