"""`[planning]` config (spec section 3.5)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    lease_seconds: float = 600.0
    max_task_attempts: int = 3
    # How much waiting work (pending + available + blocked) the store may
    # hold before Sim's OWN ideas are deferred. The creator, 2026-09-10,
    # looking at 330 queued tasks: "why would a system schedule that
    # many tasks -- shouldn't it wait until the backlog drops, then add
    # more?" It should. Intake accepted every candidate unconditionally;
    # dedupe was the only brake. A person's request is never deferred by
    # this (they asked; the reply tells them how deep the queue is), but
    # curiosity, reflection, research follow-ups and project steps wait.
    # 0 disables the cap.
    max_backlog: int = 40
    max_blocked_retries: int = 9
    blocked_retry_delay_seconds: float = 300.0
    # A task that only ran out of steps comes back this soon, with a
    # fresh budget and a memory of the attempt (see service.py's
    # `_retry_delay`). Its tool results are still fresh; waiting the
    # full blocked delay just made a long task slower.
    continuation_delay_seconds: float = 10.0
    dedupe_similarity_threshold: float = 0.45
    project_step_count: int = 4
    # Path prefixes a decomposed patch step may target. `simorgh/` is
    # the live tree; `src/` is v1, retired but not deleted, and kept
    # here only so a step naming it is not silently dropped.
    source_roots: tuple[str, ...] = ("simorgh/", "src/")
    max_plan_revisions: int = 2
    auto_approve_max_risk: str = "medium"
    human_approval_timeout_seconds: float = 3600.0
    regrounding_age_seconds: float = 21600.0
    reground_after_sibling_failure: bool = True
    stalled_after_seconds: float = 1800.0
    # A benchmark case sits below a human's own request and above the
    # system's self-directed work: it was asked for, but the human is
    # not waiting on this particular case. This dict is the ONLY real
    # default -- `scheduler.py` used to carry its own separate
    # `DEFAULT_PRIORITY_WEIGHTS` module constant that PlanningService
    # never actually used (it always builds its Scheduler from
    # `self.config.priority_weights`, i.e. this field), so adding
    # "benchmark" to the scheduler's constant on 2026-09-08 changed
    # nothing at runtime: `weight.get("benchmark", 0)` resolved to 0,
    # BELOW curiosity, the opposite of intended -- an observer proved a
    # human task preempted a running benchmark case only because 0 is
    # still less than 3, and would have preempted curiosity over
    # benchmark had both been running, backwards from the ranking this
    # was supposed to establish. `scheduler.py` now imports this dict
    # rather than keeping its own copy, so there is one default to get
    # right, not two to keep in sync by hand.
    # Origins that `auto off` (a `scope="autonomous"` pause) stops.
    # Matches guardian/config.py::autonomous_origins, duplicated rather
    # than imported for the same reason Guardian duplicates the repo
    # root: a subsystem may not import another's internals. "human" is
    # deliberately absent -- pausing autonomy must never stop the work
    # a person just asked for.
    autonomous_origins: tuple[str, ...] = ("curiosity", "reflection", "research", "project", "assistant")
    priority_weights: dict = field(
        default_factory=lambda: {"human": 3, "benchmark": 2, "reflection": 2, "assistant": 2, "curiosity": 1}
    )
    leader: bool = True
    # A decomposition or re-grounding is a real model call. This was an
    # unconfigurable 8.0s in `bridge.py`, and every replan measured at
    # exactly 8.0s -> None -> no steps (watched trial, 2026-09-07).
    # Matches the Worker's `think_timeout_s`.
    # Same reasoning as `orchestration/config.py::think_timeout_s`:
    # above Cognition's 180-second per-call ceiling, so a slow provider
    # is waited for rather than declared absent.
    think_timeout_s: float = 200.0

    @classmethod
    def from_mapping(cls, data: dict | None) -> "Config":
        data = dict(data or {})
        lease = os.environ.get("SIMORGH_PLANNING_LEASE_SECONDS")
        if lease is not None:
            data["lease_seconds"] = float(lease)
        fields = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**fields)


__all__ = ["Config"]
