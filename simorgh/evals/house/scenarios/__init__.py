"""The scenario pack (stage 11 items 4-6).

One module per stage, plus `live.py` -- the failures that actually
reached the creator, written down so they can never come back
unnoticed. Those came first on purpose: a harness anchored in bugs
that happened is worth more than one anchored in bugs somebody
imagined.
"""

from . import live, stages

#: Every scenario the pack knows, by id.
def all_scenarios() -> list:
    found = []
    for module in (live, stages):
        found.extend(getattr(module, "SCENARIOS", ()))
    return found


#: The subset the bless runs: one scenario per stage it covers, free,
#: and quick enough that nobody is tempted to switch it off. Chosen for
#: what they would catch rather than for what they prove -- each is a
#: bug that actually happened or a promise that broke silently.
#: Five, not eleven, and the cost is why: a scenario is about
#: thirty-five seconds and nearly all of it is booting the Kernel, so
#: the subset is chosen for what each one would CATCH rather than for
#: coverage. `stage6/the-same-person-twice` is the one that hurt to
#: leave out; identification is exercised here by `misheard-name`,
#: which needs the book too.
FAST: tuple[str, ...] = (
    "live/misheard-name",                  # Sim deaf to its own name; needs the speaker book
    "live/a-camera-at-night",              # Initiative's delivery path, dead since stage 6
    "stage0/a-child-asks-for-the-door",    # the tier gate
    "stage5/remembered-across-a-restart",  # memory that is actually written down
    "stage9/the-terminal-stays-sane",      # nothing ugly on the terminal
)


def fast() -> list:
    """The bless subset, in the order above."""
    found = {s.id: s for s in all_scenarios()}
    return [found[i] for i in FAST if i in found]


def by_stage(stage: str) -> list:
    return [s for s in all_scenarios() if s.stage == stage]


def by_id(scenario_id: str):
    return next((s for s in all_scenarios() if s.id == scenario_id), None)


__all__ = ["FAST", "all_scenarios", "by_id", "by_stage", "fast", "live", "stages"]
