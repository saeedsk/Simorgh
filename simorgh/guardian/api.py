"""Guardian's internal protocol (09-guardian.md section 3.4). `Rule` is
the unit every check in `rules.py` implements; `Pipeline` runs them in a
fixed order and folds their `Decision`s into one `Verdict`. Kept
deliberately small: a Rule is a pure function of a `Proposal` and a
`DecisionContext` snapshot, so the pipeline's ordering (deny
short-circuits, escalations accumulate) is the only place control flow
lives -- easy to test exhaustively (section 9's "pipeline ordering test").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Mapping, Protocol

from .config import Config
from .posture import Posture


@dataclass(frozen=True)
class Proposal:
    action_id: str
    tool: str
    args: dict
    scope: dict
    reversibility: str
    rationale: str
    proposed_by: str
    task_id: str | None = None
    # Not on the wire payload -- Guardian's own TaskModes projection
    # supplies these from task.created/task.started (section 3.1); a
    # proposal with no known task (an Interface command) defaults both.
    task_mode: str = "execute"  # execute | plan
    origin: str = "human"


@dataclass(frozen=True)
class ToolInfo:
    name: str
    read_only: bool
    reversibility: str


@dataclass(frozen=True)
class BudgetStatus:
    provider: str
    fraction_used: float  # 0..1+; >=1 means at/over cap


@dataclass(frozen=True)
class DecisionContext:
    now: float
    system_state: str  # running | paused | stopping
    posture: Posture
    config: Config
    tool: ToolInfo | None = None
    budgets: Mapping[str, BudgetStatus] = field(default_factory=dict)
    rejected_similarity: Callable[[str], tuple[float, str] | None] = lambda code: None
    classify: Callable[[Proposal], Awaitable[str | None]] | None = None  # None | "ALLOW"/"DENY"/"ASK"


@dataclass(frozen=True)
class Decision:
    kind: str  # allow | deny | escalate | abstain
    layer: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    kind: str  # approved | denied | needs_human
    layer: str = ""
    reasons: tuple[str, ...] = ()
    constraints: dict = field(default_factory=dict)


class Rule(Protocol):
    name: str
    layer: str

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: ...
