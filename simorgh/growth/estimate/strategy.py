"""Answers `learn.strategy.suggest` (spec section 3.3) from the live
`CompetenceTable` -- a pure projection read, no model call, so the
200ms budget the spec names is trivially met. With zero samples for
`task_type` the reply simply omits `strategy` (the real catalog's
`LearnStrategySuggestReply` has no separate `floor` field -- an absent
`strategy` *is* the floor signal, and `success_rate` stays the neutral
prior 0.5 rather than a fabricated number).

`CompetenceTable.suggest()` only ever ranks *per-strategy* stats
(`TaskTypeStats.strategies`), and nothing in real use populates those:
an outcome only carries a `strategy` when `OutcomeRecorder` finds one on
`learn:patch:<task_id>`'s `started` checkpoint, and `PatchPipeline`
never writes one there (`pipeline.py`'s `run()` checkpoints only `kind`/
`subject`). So for every real task type, `suggest()` returns `[]` even
after real outcomes pile up, and a caller reading only "did I get a
`scores` list back" would see the same reply for a type with zero
history and a type with a hundred real, mostly-failing samples --
observed live: 8 recorded `patch:src/memory` outcomes (6 failed) still
answered `{success_rate: 0.5, samples: 0}`. Below, an *overall*
(strategy-blind) competence figure is used as the fallback whenever real
task-level history exists but no strategy breakdown does -- still never
a fabricated number, still no `strategy` key (there is no known best
strategy to name), but no longer indistinguishable from true floor."""

from __future__ import annotations

from .competence import CompetenceTable
from .config import Config


def build_reply(task_type: str, *, competence: CompetenceTable, config: Config) -> dict:
    scores = competence.suggest(
        task_type, explore_bonus=config.explore_bonus, min_samples_for_trust=config.min_samples_for_trust
    )
    if not scores:
        samples = competence.samples(task_type)
        if samples == 0:
            return {"success_rate": 0.5, "samples": 0}
        return {"success_rate": competence.success_rate(task_type), "samples": samples}
    best = scores[0]
    parts = best.strategy.split(":")
    provider = parts[0] if parts else best.strategy
    purpose = parts[1] if len(parts) > 1 else ""
    edit_mode = parts[2] if len(parts) > 2 else ""
    return {
        "success_rate": best.success_rate,
        "samples": best.n,
        "strategy": {"approach": best.strategy, "provider": provider,
                      "purpose_config": {"purpose": purpose, "edit_mode": edit_mode}},
    }
