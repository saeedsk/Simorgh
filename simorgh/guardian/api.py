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
    # Who asked, and over which channel (stage 6 item 5): "" is the
    # console, which is the owner's.
    requester: str = ""
    requester_channel: str = ""


@dataclass(frozen=True)
class ToolInfo:
    """What Guardian knows about the tool a proposal names.

    Built by `registry.ToolRegistry.info_for` from `tool.registered`, not
    from the proposal (stage 2 item 7, evaluation S6): `read_only` is the
    registered flag, `reversibility` the stricter of the registered class
    and the proposal's claim (a proposer may tighten, never loosen).
    `registered` is False only for a tool Execution has not announced;
    then both facts are the proposal's own claim and `notes` says so."""

    name: str
    read_only: bool
    reversibility: str
    # The tool's argument schema from `tool.registered`, or None when the
    # tool is unregistered or announced none (an older ledger record).
    input_schema: dict | None = None
    registered: bool = False
    # Said on the decision: an unregistered tool, a proposal that claimed
    # a looser class than the registration.
    notes: tuple[str, ...] = ()


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
    #: `(person) -> (belief, verified)` from World Model's `world:home`
    #: (stage 6 item 5): how sure Sim is that this person is in the
    #: house right now, and whether the voice that said so was
    #: speaker-verified. None where nothing can answer -- which
    #: `PresenceRule` treats as "not present", never as "present".
    presence: Callable[[str], Awaitable[tuple[float, bool]]] | None = None


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
    # What a rule noticed but did not act on. `ShellcheckRule` returns
    # its non-dangerous findings on an `abstain` -- its docstring says
    # they ride along "so the finding is visible in the trace without
    # blocking the call" -- but `Pipeline.decide` read reasons only from
    # `deny` and `escalate`, so they went nowhere at all and the
    # documented behaviour was not real. An approved action can now
    # carry them.
    notes: tuple[str, ...] = ()


class Rule(Protocol):
    name: str
    layer: str

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: ...
