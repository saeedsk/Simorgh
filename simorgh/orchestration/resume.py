"""What a Session inherits from the `task:<id>` stream before it runs.

Two different situations look alike from here -- a task whose last
worker died mid-run, and a task that finished an attempt and came back
for another -- and they need opposite treatment.

- **A crash** (the last `task.started` has no outcome after it): the
  new worker is *continuing the same attempt*, so the steps already
  spent count against the budget and it must not redo them (16
  section 4/section 5 RESUME).

- **A retry** (the last attempt ended `blocked`/`failed` and Planning
  offered the task again): a *new attempt* with a fresh budget -- but
  with a memory of what the earlier attempts did, so it continues
  rather than restarts.

The second case did not exist before 2026-09-07. `restore_step_count`
treated every prior step as this attempt's, so a task blocked on "step
budget exhausted" came back with its budget already exhausted and no
memory of why: it could never make progress, and the creator's question
-- "what if a task requires long and multiple tool access, aren't we
limiting sim?" -- was exactly right about the effect. Now the cap bounds
one attempt; the work spans attempts.
"""

from __future__ import annotations

from simorgh.contracts import topics

from .api import Session, Step
from .session import EDITS_KEPT

# How much of the earlier attempts the new one is told about. A patch
# step keeps more because its summary carries the diff, which is the
# one thing worth re-applying quickly.
_CARRY_CHARS = 6000
_STEP_CHARS = 220
_PATCH_STEP_CHARS = 1400
_ENDED = {topics.TASK_BLOCKED: "blocked", topics.TASK_FAILED: "failed", topics.TASK_COMPLETED: "completed"}


def _attempts(events) -> list[dict]:
    """Split a task stream into attempts: each starts at `task.started`
    and ends at the first outcome after it (an orchestration
    `task.blocked`/`task.failed`/`task.completed` event, or Planning's
    `status_changed` to blocked/failed on the same stream)."""
    attempts: list[dict] = []
    current: dict | None = None
    for e in events:
        if e.type == topics.TASK_STARTED:
            current = {"steps": [], "ended": None, "reason": "", "kept": [], "created": []}
            attempts.append(current)
        elif current is None:
            continue
        elif e.type == topics.TASK_STEP:
            current["steps"].append(e.payload)
        elif e.type == EDITS_KEPT:
            current["kept"] = list(e.payload.get("paths") or [])
            current["created"] = list(e.payload.get("created") or [])
        elif e.type in _ENDED and current["ended"] is None:
            current["ended"] = _ENDED[e.type]
            current["reason"] = str(e.payload.get("reason") or e.payload.get("result_summary") or "")
        elif e.type == "status_changed" and current["ended"] is None:
            status = e.payload.get("status")
            if status in ("blocked", "failed"):
                current["ended"] = status
                current["reason"] = str(e.payload.get("note") or "")
    return attempts


def carried_note(attempts: list[dict]) -> str:
    """The earlier attempts, rendered for the model: what each did and
    how it ended. Oldest first; trimmed from the front when long, so the
    most recent attempt is always the one kept whole."""
    blocks: list[str] = []
    for n, attempt in enumerate(attempts, start=1):
        lines = [f"Attempt {n} ended {attempt['ended'] or 'unknown'}" + (f": {attempt['reason'][:200]}" if attempt["reason"] else "")]
        for step in attempt["steps"]:
            tool = step.get("tool") or step.get("phase") or "step"
            cap = _PATCH_STEP_CHARS if tool in ("apply_source_patch", "apply_skill") else _STEP_CHARS
            summary = str(step.get("summary") or "")
            summary = summary if len(summary) <= cap else summary[:cap] + "…"
            mark = {True: "ok", False: "FAILED"}.get(step.get("ok"), "")
            lines.append(f"- {tool}: {summary}  {mark}".rstrip())
        if attempt.get("kept"):
            lines.append(f"Left in the tree, uncommitted, for the next attempt: {', '.join(attempt['kept'])}")
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    while len(text) > _CARRY_CHARS and len(blocks) > 1:
        blocks.pop(0)
        text = "(earlier attempts omitted)\n\n" + "\n\n".join(blocks)
    return text[-_CARRY_CHARS:] if len(text) > _CARRY_CHARS else text


async def restore_session(session: Session, ledger) -> int:
    """Prepare `session` from its stream. Returns the number of steps
    this attempt already spent (non-zero only after a crash)."""
    events = await ledger.read(f"task:{session.task_id}")
    attempts = _attempts(events)
    if not attempts:
        return 0
    last = attempts[-1]
    if last["ended"] is None:
        # Mid-attempt: pick up where the dead worker left off.
        for p in last["steps"]:
            session.record(Step(
                p.get("step_no", len(session.steps) + 1), p.get("phase", "act"), p.get("summary", ""),
                tool=p.get("tool"), ok=p.get("ok"),
            ))
        session.budget.steps_used = len(last["steps"])
        session.resumed_from_step = len(last["steps"])
        if len(attempts) > 1:
            session.carried = carried_note(attempts[:-1])
            # The edits the DEAD attempt inherited are still in the tree.
            # Without this the resumed session does not know it owns
            # them, so neither `_keep_uncommitted` nor
            # `_discard_uncommitted` ever touches them again and the
            # edit is orphaned there permanently (observer, 2026-09-08).
            previous = attempts[-2]
            session.uncommitted.update(previous.get("kept") or ())
            session.created.update(previous.get("created") or ())
        session.uncommitted.update(last["kept"])
        session.created.update(last["created"])
        return len(last["steps"])
    session.carried = carried_note(attempts)
    session.attempt = len(attempts) + 1
    # Edits the last attempt left in the tree on purpose: this attempt
    # owns them now -- commits them, keeps them again, or discards them
    # at its end.
    session.uncommitted.update(last["kept"])
    session.created.update(last["created"])
    return 0


async def restore_step_count(session: Session, ledger) -> int:
    """The pre-2026-09-07 entry point, kept for callers that only ever
    meant crash-resume. Same as `restore_session`."""
    return await restore_session(session, ledger)


__all__ = ["carried_note", "restore_session", "restore_step_count"]
