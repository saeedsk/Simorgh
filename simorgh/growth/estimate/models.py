"""Plain data shapes used across the package -- no Ledger/Bus knowledge
here, so `competence.py` and `pipeline.py` can be unit-tested with
nothing but these."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Strategy:
    """The tuple competence is keyed on (spec section 3.4)."""

    provider: str
    purpose: str
    edit_mode: str = ""

    def key(self) -> str:
        return f"{self.provider}:{self.purpose}:{self.edit_mode}" if self.edit_mode else f"{self.provider}:{self.purpose}"


@dataclass(frozen=True)
class Outcome:
    task_id: str
    task_type: str
    succeeded: bool
    weight: float
    verdict: str
    cost_usd: float
    duration_s: float
    strategy: str | None = None
    stated_confidence: float | None = None
    ts: float = 0.0


@dataclass
class StrategyStats:
    #: A float, not a count: with exponential forgetting the effective
    #: number of samples decays between outcomes, so 12 last month is
    #: worth about 6 this month at a 30-day half-life.
    n: float = 0.0
    successes_w: float = 0.0
    cost_sum: float = 0.0
    #: When these sums were last aged to. 0 means "never aged", which
    #: is how a table written before forgetting existed loads.
    at: float = 0.0

    def rate(self) -> float:
        return (self.successes_w + 1) / (self.n + 2)


@dataclass
class TaskTypeStats:
    n: float = 0.0
    successes_w: float = 0.0
    cost_sum: float = 0.0
    dur_sum: float = 0.0
    at: float = 0.0
    calib_bins: dict[int, list[int]] = field(default_factory=dict)  # bin -> [n, hits]
    strategies: dict[str, StrategyStats] = field(default_factory=dict)

    def rate(self) -> float:
        return (self.successes_w + 1) / (self.n + 2)


@dataclass(frozen=True)
class StrategyScore:
    strategy: str
    success_rate: float
    n: int
    score: float


@dataclass(frozen=True)
class PatchTaskSpec:
    task_id: str
    kind: str  # patch | skill
    description: str
    subject: str | None
    prior_reasons: list[str]
