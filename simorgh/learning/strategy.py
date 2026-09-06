"""Answers `learn.strategy.suggest` (spec section 3.3) from the live
`CompetenceTable` -- a pure projection read, no model call, so the
200ms budget the spec names is trivially met. With zero samples for
`task_type` the reply simply omits `strategy` (the real catalog's
`LearnStrategySuggestReply` has no separate `floor` field -- an absent
`strategy` *is* the floor signal, and `success_rate` stays the neutral
prior 0.5 rather than a fabricated number)."""

from __future__ import annotations

from .competence import CompetenceTable
from .config import Config


def build_reply(task_type: str, *, competence: CompetenceTable, config: Config) -> dict:
    scores = competence.suggest(
        task_type, explore_bonus=config.explore_bonus, min_samples_for_trust=config.min_samples_for_trust
    )
    if not scores:
        return {"success_rate": 0.5, "samples": 0}
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
