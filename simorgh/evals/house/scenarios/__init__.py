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


def by_stage(stage: str) -> list:
    return [s for s in all_scenarios() if s.stage == stage]


def by_id(scenario_id: str):
    return next((s for s in all_scenarios() if s.id == scenario_id), None)


__all__ = ["all_scenarios", "by_id", "by_stage", "live", "stages"]
