"""Plan Mode's decision logic (spec section 5.4): the approval policy
matrix and the revision diff. Kept free of bus/Ledger calls so it's
testable as pure functions; `service.py` wires it to real messages.
`PlanState` is process-local convenience state -- the durable record is
the `plan:<id>` Ledger stream (spec section 4); a restart rebuilds it by
replay, this dict is just a fast-path cache the same way `TaskIndex` is
for tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Step

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

PROPOSED = "proposed"
AWAITING_HUMAN = "awaiting_human"
APPROVED = "approved"
REJECTED = "rejected"


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


def approval_decision(verdict: str, risk: str, auto_approve_max_risk: str) -> str:
    """Returns one of `"auto_approve"`, `"ask_human"`, `"replan"`, `"reject"`
    -- the section 5.4 policy table, `insufficient_evidence` folded into
    the same bounded-replan path as `revise` (a first pass simply hasn't
    used up a revision yet, it isn't a distinct branch)."""
    if verdict == "reject":
        return "reject"
    if verdict in ("revise", "insufficient_evidence"):
        return "replan"
    if verdict == "approve":
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


__all__ = ["APPROVED", "AWAITING_HUMAN", "PROPOSED", "REJECTED", "PlanState", "approval_decision", "compute_diff"]
