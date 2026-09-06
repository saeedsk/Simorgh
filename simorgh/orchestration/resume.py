"""Rebuild a `Session`'s step count from `task:<id>` after a crash (16
section 4/section 5 RESUME). Simplified this session: restores
`budget.steps_used` (so a second Worker never re-spends the exhausted
step budget) from the durable `task.step` events already appended, but
does not restore the full assembled-message transcript from a
`context.snapshot` blob -- the next THINK simply re-assembles fresh
context. Full fork/snapshot restore is out of scope this build (see
README "Not done this session").
"""

from __future__ import annotations

from simorgh.contracts import topics

from .api import Session, Step


async def restore_step_count(session: Session, ledger) -> int:
    events = await ledger.read(f"task:{session.task_id}")
    steps = [e for e in events if e.type == topics.TASK_STEP]
    for e in steps:
        session.record(Step(
            e.payload.get("step_no", len(session.steps) + 1),
            e.payload.get("phase", "act"),
            e.payload.get("summary", ""),
            tool=e.payload.get("tool"),
            ok=e.payload.get("ok"),
        ))
    session.budget.steps_used = len(steps)
    session.resumed_from_step = len(steps)
    return len(steps)
