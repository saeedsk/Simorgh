"""`project_status` -- a pure function of children's statuses (ported
verbatim from v1 `src/orchestrator/projects.py`; spec section 5.3 and
`harness-03`'s "rollup status is computed, not separately tracked").
Never stored as independent state -- a stored parent status *can*
diverge from what its children actually did, and will, the first time an
edge case isn't handled."""

from __future__ import annotations

from typing import Sequence

from .model import (
    BLOCKED, COMPLETED, DEPENDENCY_FAILED_NOTE, FAILED, IN_PROGRESS, PENDING,
    TERMINAL_STATUSES, Task,
)


def is_dead(child: Task) -> bool:
    """Whether this child can never run again.

    A terminal status is the obvious case. The other one is a child
    parked because a dependency failed terminally: BLOCKED is not a
    terminal status, so a project whose remaining work was all
    dependency-blocked reported IN_PROGRESS forever -- nothing could
    move, `project.failed` was never published, and the project sat
    there indefinitely. Live-caught by an observer over a real Kernel,
    2026-09-10: three children, one completed, one failed, one blocked
    on the failure, `rollup=in_progress done=1/3` and no project event
    ever emitted.

    A child BLOCKED for any other reason -- out of step budget, waiting
    on a human -- is still alive, because Planning re-offers those."""
    if child.status in TERMINAL_STATUSES:
        return True
    return child.status == BLOCKED and (child.note or "").startswith(DEPENDENCY_FAILED_NOTE)


def doomed_ids(children: Sequence[Task]) -> set[str]:
    """Children that can never run, from the dependency graph itself.

    `is_dead` reads the `dependency_failed:` note, and that note is only
    written when the child's status CHANGES to blocked -- a child
    already BLOCKED for another reason (out of step budget, say) never
    gets it, because BLOCKED -> BLOCKED is not a legal transition. That
    is the commoner case, and the project then reported `blocked`
    forever with nothing able to move (observer, 2026-09-10, on the
    rollup fix from the same morning).

    Walking the edges answers it without depending on a note being
    written. Cycle-safe: a child already in the set is not re-expanded.
    """
    by_id = {c.id: c for c in children}
    doomed = {c.id for c in children if c.status == FAILED}
    changed = True
    while changed:
        changed = False
        for child in children:
            if child.id in doomed or child.status == COMPLETED:
                continue
            if any(dep in doomed for dep in (child.depends_on or ())):
                doomed.add(child.id)
                changed = True
    # A dependency on something outside this project cannot be judged
    # here, so it is left alone rather than assumed dead.
    return {cid for cid in doomed if cid in by_id}


def project_status(children: Sequence[Task]) -> str:
    if not children:
        return PENDING
    statuses = [c.status for c in children]
    if all(s == COMPLETED for s in statuses):
        return COMPLETED
    doomed = doomed_ids(children)
    if all(is_dead(c) or c.id in doomed for c in children):
        # Nothing left that can move, and not everything succeeded (the
        # check above already caught that) -- at least one failed, or
        # was parked forever behind one that did.
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
