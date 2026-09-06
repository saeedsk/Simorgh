"""Re-grounding (spec section 5.5): before making a stale child
`available`, one bounded `cognition.think(purpose="reground")` call asks
whether it still serves the project's goal. Same "scan every line for a
verdict, a non-answer defers to the existing plan" rule Verification uses
for the identical reason (milestone 92: a rambling non-answer must never
be graded as a rejection)."""

from __future__ import annotations

import re

from .bridge import BusCognitionCaller
from .model import Task

_STILL_VALID_LINE = re.compile(r"^\s*STILL_VALID\s*:\s*(yes|no)\b(.*)$", re.IGNORECASE)

_REGROUND_PROMPT = """You are Sim, checking whether a planned step still
makes sense given what has changed since it was planned.

Project goal: {goal}
Step: {description}
Why this step was planned: {why}

What has changed since:
{changes}

Does this step still serve the goal? Respond with a line:
STILL_VALID: yes
or
STILL_VALID: no -- <one sentence, and if you have one, a suggested revision>"""


def needs_check(child: Task, *, now: float, regrounding_age_seconds: float, sibling_failed_since: bool) -> bool:
    return sibling_failed_since or (now - child.created_at) > regrounding_age_seconds


async def check(
    caller: BusCognitionCaller, *, goal: str, child: Task, why: str, changes_since: list[str],
) -> tuple[bool | None, str]:
    """Returns `(still_valid, reason)`. `still_valid=None` means no clear
    verdict was returned -- treated as valid by the caller (a non-answer
    is not evidence of drift, spec section 5.5 and `01` section 4.5)."""
    prompt = _REGROUND_PROMPT.format(
        goal=goal, description=child.description, why=why or "(no reason recorded)",
        changes=("\n".join(f"- {c}" for c in changes_since) or "(nothing notable)"),
    )
    text = await caller.think(purpose="reground", prompt=prompt)
    if not text:
        return None, ""
    for line in text.splitlines():
        match = _STILL_VALID_LINE.match(line.strip())
        if match:
            still_valid = match.group(1).lower() == "yes"
            return still_valid, match.group(2).strip(" -")
    return None, ""


__all__ = ["check", "needs_check"]
