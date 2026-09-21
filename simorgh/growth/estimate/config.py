"""`[growth.estimate]` config: the knobs the outcome record and the
strategy ranking read. The six PatchPipeline keys (`max_draft_attempts`,
`max_pipeline_wall_seconds`, `action_timeout_seconds`,
`verify_timeout_seconds`, `hot_swap_slots`, `max_concurrent_pipelines`)
were removed on 2026-09-19; the pipeline itself retired on 2026-09-18.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Config:
    explore_bonus: float = 0.15
    # How long before an outcome counts half as much (stage 6 item 1's
    # exponential forgetting). What Sim was bad at in the spring must
    # not outvote what it is good at now: without this, a bad
    # fortnight keeps routing away from a task type long after the bug
    # behind it was fixed, and nothing it does afterwards can outweigh
    # enough history. 0 turns forgetting off.
    competence_half_life_days: float = 30.0
    min_samples_for_trust: int = 5
    blocked_sample_weight: float = 0.5
    # How much a completion nobody checked is worth, against a verified
    # one (stage 8 item 2). "The task said it finished" is a
    # self-report, and an estimate built on self-reports measures
    # confidence rather than competence -- but throwing the outcome
    # away entirely would leave whole task types with no estimate at
    # all, so it counts a little and says how much.
    unverified_sample_weight: float = 0.25
    # How much one eval case is worth against one verified task outcome
    # (stage 8 item 2). Less, because a fixture is a fixture: it is the
    # same question every time and the house is not in it.
    eval_sample_weight: float = 0.5
    # Which eval suite speaks for which task type, when one does.
    # `posterior("patch")` blends `eval:trials` at `eval_sample_weight`.
    eval_suites: tuple[tuple[str, str], ...] = (("patch", "trials"), ("research", "research"),
                                                ("chat", "household"))
    # Where the eval reports are. The loader writes them here on every
    # bless, which is before Sim is up -- exactly when the numbers are
    # worth having. Relative to the working directory; `data_dir` is
    # also tried, so a test or a sandbox can put its own there.
    evals_record: str = ".simorgh_loader/evals.jsonl"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Config":
        data = dict(data or {})
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})
