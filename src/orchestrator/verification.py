"""Independent verification of a completed Task -- the "quality control"
half of the creator's ask, distinct from AuditGate (safety: does the
code do anything dangerous) and the isolated test suite (regression: did
anything break). Neither of those asks whether a change actually
addresses what the task set out to do; a mechanically clean apply that
misses the point should not silently count as DONE.

A second, independently-prompted LLM call reviews the applied result
against the task's own description -- author and reviewer are different
calls, the same separation ordinary software practice already relies on.
This never gates whether code gets *written* (that stays exactly
AuditGate's and the test suite's job) -- it only ever downgrades an
already-successful apply to BLOCKED for a human to look at, when the
result looks like it missed the point.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.cognition.provider import CognitionRouter
from src.orchestrator.tasks import Task

_VERIFY_PROMPT = """A change was just applied to address this task:

Task: {description}

Result reported by the pipeline that applied it:
{result}

Does this genuinely address the task, or does it look like a
non-answer, a placeholder, or something that missed the point? Answer
with exactly one word first -- YES or NO -- then, on a new line, one
short sentence explaining why."""


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    explanation: str


def verify_task_completion(
    cognition: CognitionRouter, task: Task, result: str
) -> VerificationResult:
    """With no real provider reachable, this can't meaningfully judge
    anything -- it defers to the mechanical gates alone (passed=True)
    rather than blocking completion on a question nothing can actually
    answer. `passed=False` means "looks wrong" from the reviewer's read,
    not a security or correctness proof; it exists to catch a plausible-
    sounding but off-target change, not to replace the real gates.
    """
    response = cognition.complete(
        _VERIFY_PROMPT.format(description=task.description, result=result)
    )
    if response.provider_name == "deterministic_fallback" or not response.text.strip():
        return VerificationResult(
            True, "no real reviewer available -- deferring to the audit/test gates alone"
        )
    first_line = response.text.strip().splitlines()[0].strip().upper()
    passed = first_line.startswith("YES")
    return VerificationResult(passed, response.text.strip())
