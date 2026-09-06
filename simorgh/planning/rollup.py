"""`project_status` -- a pure function of children's statuses (ported
verbatim from v1 `src/orchestrator/projects.py`; spec section 5.3 and
`harness-03`'s "rollup status is computed, not separately tracked").
Never stored as independent state -- a stored parent status *can*
diverge from what its children actually did, and will, the first time an
edge case isn't handled."""

from __future__ import annotations

from typing import Sequence

from .model import BLOCKED, COMPLETED, FAILED, IN_PROGRESS, PENDING, TERMINAL_STATUSES, Task


def project_status(children: Sequence[Task]) -> str:
    if not children:
        return PENDING
    statuses = [c.status for c in children]
    if all(s == COMPLETED for s in statuses):
        return COMPLETED
    if all(s in TERMINAL_STATUSES for s in statuses):
        # every child finished, but not all succeeded (the DONE check
        # above already caught "all completed") -- at least one FAILED.
        return FAILED
    if any(s == IN_PROGRESS for s in statuses):
        return IN_PROGRESS
    if any(s == COMPLETED for s in statuses):
        # some children finished, others haven't started -- still
        # actively progressing, not merely pending.
        return IN_PROGRESS
    if any(s == BLOCKED for s in statuses):
        return BLOCKED
    return PENDING


def is_stalled(children: Sequence[Task], *, now: float, stalled_after_seconds: float) -> bool:
    """`BLOCKED` with nothing scheduled to retry it, or `IN_PROGRESS`
    with an expired lease and no successor claim yet, for longer than
    the threshold -- surfaced in `task.list.reply` so a stuck project
    isn't indistinguishable from a genuinely active one (spec section 8,
    "make 'stalled' itself a detectable, queryable state")."""
    for child in children:
        if child.status == BLOCKED and (now - child.updated_at) > stalled_after_seconds:
            return True
        if child.status == IN_PROGRESS and child.lease is not None and child.lease.until < now \
                and (now - child.lease.until) > stalled_after_seconds:
            return True
    return False


__all__ = ["is_stalled", "project_status"]
