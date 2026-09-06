"""Pattern mining (spec section 5.2) -- a port of v1's
`src/orchestrator/reflection.py` `ReflectionAgent.reflect()`: group
outcomes and look for a group whose failure rate crosses a threshold.

v1 grouped purely by agent (`by_agent`); `learn.outcome.recorded`
(section 4.11) carries `task_type` and an optional `strategy`, not the
`area`/`tool` v1's own outcome shape never had either -- this groups by
`(task_type, strategy)`, the finest key the real message actually
supports, and notes the simplification rather than inventing fields no
producer sends.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Config


@dataclass(frozen=True)
class OutcomeSample:
    task_type: str
    succeeded: bool
    strategy: str | None
    ts: float


@dataclass(frozen=True)
class Pattern:
    kind: str  # "failure_rate"
    task_type: str
    rate: float
    proposal: str
    agent: str | None = None  # kept for the reflect.patterns.found schema; unused (no agent concept in v2)


class PatternMiner:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        self._samples: list[OutcomeSample] = []

    def add(self, task_type: str, succeeded: bool, strategy: str | None, ts: float) -> None:
        self._samples.append(OutcomeSample(task_type, succeeded, strategy, ts))

    def mine(self, now: float, *, window_s: float | None = None, min_rate: float | None = None, min_samples: int | None = None) -> list[Pattern]:
        window_s = self._config.pattern_window_seconds if window_s is None else window_s
        min_rate = self._config.pattern_min_rate if min_rate is None else min_rate
        min_samples = self._config.pattern_min_samples if min_samples is None else min_samples

        cutoff = now - window_s
        self._samples = [s for s in self._samples if s.ts >= cutoff]

        by_key: dict[tuple[str, str | None], list[OutcomeSample]] = {}
        for s in self._samples:
            by_key.setdefault((s.task_type, s.strategy), []).append(s)

        patterns: list[Pattern] = []
        for (task_type, strategy), group in by_key.items():
            if len(group) < min_samples:
                continue
            failures = sum(1 for s in group if not s.succeeded)
            rate = failures / len(group)
            if rate >= min_rate:
                strat_note = f" (strategy {strategy!r})" if strategy else ""
                patterns.append(Pattern(
                    kind="failure_rate",
                    task_type=task_type,
                    rate=rate,
                    proposal=(
                        f"'{task_type}' tasks{strat_note} failed {failures}/{len(group)} "
                        f"recent outcomes ({rate:.0%}) -- worth reviewing for a systematic issue."
                    ),
                ))
        return patterns
