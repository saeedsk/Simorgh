"""Dataclasses and protocols internal to `simorgh.orchestration`
(docs/blueprint/subsystems/16-orchestration.md section 3.4). Not part of
`simorgh.contracts` -- nothing outside this package imports these types;
subsystems only ever see the messages this package produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class Profile:
    """Per task-kind policy: what a Session is allowed to try, and how
    much of it. `tools` are *requests* -- Guardian is the sole authority
    on whether any one of them is actually approved (16 section 5).
    """

    name: str
    tools: tuple[str, ...]
    read_only: bool
    max_steps: int
    max_revisions: int
    scaffold: str
    last_step_hint: str = (
        "This is your last step -- no more tool calls will be honored. "
        "Answer now with what you have, even if incomplete."
    )
    verify: bool = True


@dataclass
class Step:
    no: int
    phase: Literal["gather", "act", "verify"]
    summary: str
    tool: str | None = None
    action_id: str | None = None
    ok: bool | None = None
    confidence: float | None = None
    cost_usd: float = 0.0
    tokens: int = 0


@dataclass
class Budget:
    """Remaining allowance for one Session -- steps is the only bound
    enforced by v1 experience (`_FINAL_TURN_HINT`, milestone 83); tokens/
    cost/seconds are tracked but Cognition is the actual spender.
    """

    max_steps: int
    steps_used: int = 0
    max_revisions: int = 2
    revisions_used: int = 0

    @property
    def steps_left(self) -> int:
        return max(0, self.max_steps - self.steps_used)

    @property
    def is_last_step(self) -> bool:
        return self.steps_left <= 1

    @property
    def exhausted(self) -> bool:
        return self.steps_used >= self.max_steps


@dataclass
class Session:
    task_id: str
    kind: str
    mode: Literal["plan", "execute"]
    profile: Profile
    worker_id: str = ""
    depth: int = 0
    parent_id: str | None = None
    steps: list[Step] = field(default_factory=list)
    budget: Budget = field(default_factory=lambda: Budget(max_steps=6))
    messages: list[dict] = field(default_factory=list)  # the running cognition.think transcript
    state: str = "CLAIMED"
    resumed_from_step: int = 0

    def next_step_no(self) -> int:
        return len(self.steps) + 1

    def record(self, step: Step) -> None:
        self.steps.append(step)


@dataclass(frozen=True)
class Outcome:
    kind: Literal["completed", "failed", "blocked", "paused"]
    result_summary: str = ""
    reason: str = ""
    verification_ref: str | None = None
    floor: bool = False
    confidence: float | None = None


class ContextAssembler(Protocol):
    async def assemble(self, session: Session, purpose: str) -> list[dict]: ...


class ToolCallRouter(Protocol):
    def to_action(self, session: Session, call: dict) -> dict: ...
