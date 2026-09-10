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
    # Output tokens one step may use. `apply_source_patch` takes the
    # COMPLETE new content of a file, so a patch session that cannot
    # emit a whole file cannot apply anything -- and this is shared
    # with the model's reasoning tokens, which a reasoning model
    # spends first. Live-caught 2026-09-07: at 2000, asked to edit a
    # 1,365-token file, the model read it eight times and applied
    # nothing, because the patch would not have fit in the reply.
    max_output_tokens: int = 2_000
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
    user_text: str = ""
    # The file this task is already about, when the task named one.
    # Without it a patch session is told to go and find the code it
    # was handed the path to (see `scaffolds.render`).
    subject: str | None = None
    depth: int = 0
    parent_id: str | None = None
    steps: list[Step] = field(default_factory=list)
    budget: Budget = field(default_factory=lambda: Budget(max_steps=6))
    # What this session's thinking has cost so far. `Step.cost_usd` has
    # existed since the beginning and nothing ever set it, so
    # `task.step` carried no cost, so a benchmark run summed its cases
    # to $0.00 and reported that as the price of the run -- a number
    # whose whole job is to be true.
    spent_usd: float = 0.0
    spent_tokens: int = 0
    messages: list[dict] = field(default_factory=list)  # the running cognition.think transcript
    # Whether this session has already told the model that a marker
    # buried mid-sentence is not a tool call. Once is a correction; a
    # second time would mean the reply really is prose about a tool, and
    # correcting it again would loop.
    marker_corrected: bool = False
    # Files this session wrote and has not committed. A session that
    # ends with anything left here put a change in the tree and
    # walked away from it; `SessionRunner` cleans up before it
    # returns.
    uncommitted: set[str] = field(default_factory=set)
    # The subset of `uncommitted` that did not exist before this session
    # wrote it. `git_discard` cannot restore an untracked file, so these
    # are deleted at cleanup instead.
    created: set[str] = field(default_factory=set)
    # Every path this session wrote, ever. Distinct from the two sets
    # above, which are cleanup bookkeeping: both are DISCARDED on a
    # successful `git_commit`, so a task that did the right thing ends
    # with both empty. Verification's file-reading checks (js_syntax,
    # render, trailing_narration) need "what did this session produce",
    # which is exactly the question those sets stop answering the moment
    # the work succeeds -- live-caught 2026-09-09, when a page with the
    # model's own `GIT_COMMIT:` marker appended after `</html>` passed
    # verification because the checks saw no paths at all. Only grows.
    wrote: set[str] = field(default_factory=set)
    state: str = "CLAIMED"
    resumed_from_step: int = 0
    # A retry's memory of the attempts before it (`resume.py`): what
    # they did and how they ended, rendered for the model. Empty on a
    # first attempt.
    carried: str = ""
    attempt: int = 1
    # The git commit this session started from, captured once by
    # `SessionRunner.run`. Travels to Verification in the verify
    # subject so `full_suite_ran` can stage the tree as it was BEFORE
    # this session and ask whether a failing test was already failing.
    # Empty when there is no git repo to ask, which every reader must
    # treat as "cannot attribute" rather than "nothing pre-existed".
    base_ref: str = ""

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
