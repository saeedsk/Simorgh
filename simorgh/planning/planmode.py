"""Plan Mode's decision logic (spec section 5.4): the approval policy
matrix and the revision diff. Kept free of bus/Ledger calls so it's
testable as pure functions; `service.py` wires it to real messages.
`PlanState` is the in-memory state of one plan; its durable record is the
`planning:plans` Ledger stream, where `service.py` appends the whole state
whenever it changes and replays it at start (since 2026-09-19).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Step

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

PROPOSED = "proposed"
AWAITING_HUMAN = "awaiting_human"
APPROVED = "approved"
REJECTED = "rejected"
TIMED_OUT = "timed_out"

# Statuses a plan can no longer leave -- `_on_plan_reviewed` and
# `_on_prompt_answered` must no-op on a plan already in one of these
# (spec section 8, "duplicate messages ... a no-op"); without this a
# human answer that arrives after `human_approval_timeout_seconds` has
# already paused the task would attempt an illegal PAUSED -> COMPLETED
# or PAUSED -> FAILED transition and crash the handler.
RESOLVED_STATUSES = frozenset({APPROVED, REJECTED, TIMED_OUT})


@dataclass
class PlanState:
    plan_id: str
    task_id: str
    goal: str
    steps: list[Step]
    risk: str
    estimated_cost: float = 0.0
    revisions: int = 0
    status: str = PROPOSED
    prompt_id: str | None = None
    # When `status == AWAITING_HUMAN` was entered -- the clock reading
    # `service.py` compares against `human_approval_timeout_seconds` on
    # every `system.tick.second` to decide whether the human has gone
    # unanswered long enough to pause the project task rather than hang
    # on it forever (see this module's docstring and spec section 5.4's
    # "timeout -> project task paused with reason").
    prompt_asked_at: float | None = None
    #: The Self Model's Beta posterior for this plan's task type, and
    #: how many outcomes it rests on. Asked for when the plan is
    #: proposed, not when it is decided: the review round trip is far
    #: longer than the estimate, so the answer is there by the time it
    #: matters, and the decision path never waits on a bus request that
    #: may have no responder (stage 6 item 2).
    posterior: float | None = None
    posterior_samples: int = 0


def approval_decision(verdict: str, risk: str, auto_approve_max_risk: str,
                      *, posterior: float | None = None, samples: int = 0,
                      weak_below: float = 0.0, min_samples: int = 8) -> str:
    """Returns one of `"auto_approve"`, `"ask_human"`, `"replan"`, `"reject"`
    -- the section 5.4 policy table, `insufficient_evidence` folded into
    the same bounded-replan path as `revise` (a first pass simply hasn't
    used up a revision yet, it isn't a distinct branch).

    `posterior` is the Beta mean for this kind of work, from the Self
    Model (stage 6 item 2). A plan Sim is measurably bad at does not
    auto-approve however low its risk looks: risk is what the plan
    SAYS about itself, and the posterior is what actually happened
    the last N times Sim tried this. Only with real evidence behind
    it -- `min_samples` -- because `Beta(1,1)` has a mean of 0.5 and
    means "nothing recorded yet", and treating that as bad would send
    every new kind of work to a person.
    """
    if verdict == "reject":
        return "reject"
    if verdict in ("revise", "insufficient_evidence"):
        return "replan"
    if verdict == "approve":
        if weak_below > 0.0 and posterior is not None and samples >= min_samples and posterior < weak_below:
            return "ask_human"
        if _RISK_ORDER[risk] <= _RISK_ORDER[auto_approve_max_risk]:
            return "auto_approve"
        return "ask_human"
    raise ValueError(f"unknown verdict {verdict!r}")


def compute_diff(before: list[Step], after: list[Step]) -> dict:
    """`{added, removed, reordered}` by step description -- spec section
    5.4's "computed diff (added/removed/reordered by step description)".
    A step present in both but at a different index counts as reordered,
    not removed+added (so a genuine no-op reshuffle is visible as such)."""
    before_desc = [s.description for s in before]
    after_desc = [s.description for s in after]
    before_set, after_set = set(before_desc), set(after_desc)
    added = [d for d in after_desc if d not in before_set]
    removed = [d for d in before_desc if d not in after_set]
    common = [d for d in after_desc if d in before_set]
    reordered = [d for d in common if before_desc.index(d) != after_desc.index(d)]
    return {"added": added, "removed": removed, "reordered": reordered}


def is_human_approval_timed_out(state: PlanState, *, now: float, timeout_seconds: float) -> bool:
    """True iff `state` is still waiting on a human answer and has been
    for at least `timeout_seconds` -- pure so the scan in `service.py`
    (and its tests) don't need a real clock or bus."""
    if state.status != AWAITING_HUMAN or state.prompt_asked_at is None:
        return False
    return (now - state.prompt_asked_at) >= timeout_seconds


__all__ = [
    "APPROVED", "AWAITING_HUMAN", "PROPOSED", "REJECTED", "RESOLVED_STATUSES", "TIMED_OUT",
    "PlanState", "approval_decision", "compute_diff", "is_human_approval_timed_out",
]
