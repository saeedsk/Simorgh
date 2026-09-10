"""Combine mechanical checks + semantic checklist + trajectory into one
verdict (docs/blueprint/subsystems/10-verification.md section 5.1,
"verdict.combine"). Any failed mechanical check (cheapest-first, so an
expensive check like the isolated suite never runs for a draft that was
already going to fail on something free) is `fail`. Otherwise: any
required checklist item answered "no" is `fail`; too many items
unanswered (`insufficient_evidence`, milestone 92 -- never `fail`);
`denied_actions` over the configured max is `fail` (the task kept
proposing things it wasn't allowed to do); else `pass`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .api import CheckResult, Feedback, FailedItem
from .checklist import AnsweredItem
from .config import VerificationConfig
from .trajectory import TrajectoryMetrics

Verdict = str  # "pass" | "fail" | "insufficient_evidence"


def _checklist_item_payload(a: AnsweredItem) -> dict:
    # verify.result.checklist[] requires q/answer/evidence, all strings
    # (contracts/schema/verify.result.v1.json) -- None becomes "unanswered"
    # rather than a null the schema would reject.
    return {"q": a.question, "answer": a.answer or "unanswered", "evidence": a.evidence, "required": a.required}


def feedback_to_wire(feedback: Feedback) -> dict:
    """`verify.result.feedback` is `{items: [{what, why, suggested_fix}]}`
    on the wire (contracts/schema/verify.result.v1.json) -- narrower than
    this module's own richer `Feedback` dataclass. `retryable`/`revise_hint`
    ride along as additional properties (the schema allows them) since
    Orchestration's evaluator-optimizer loop reads them too.
    """
    items = [
        {"what": i.question, "why": i.evidence, "suggested_fix": i.suggestion}
        for i in feedback.failed_items
    ]
    items.extend({"what": "mechanical check failed", "why": err, "suggested_fix": ""} for err in feedback.mechanical_errors)
    return {
        "items": items,
        "retryable": feedback.retryable,
        "revise_hint": feedback.revise_hint,
    }


@dataclass(frozen=True)
class CombinedResult:
    verdict: Verdict
    checklist: list[dict]
    feedback: Feedback | None
    mechanical: dict


# Phrases that mean "this did not happen because the system correctly
# refused", as opposed to "this did not happen because the work is bad".
#
# Every phrase here has to NAME the refuser or the protected target.
# The loose ones read a real defect as a refusal and passed it:
#
#   "the attribute is protected by a lock so the model skipped it"  -> pass
#   "there is no workaround visible in the steps"                   -> pass
#   "It refused to add a docstring? No, it never edited the file."   -> pass
#
# all three observed 2026-09-10. `no workaround` is gone entirely: it
# is a remark about the evidence, never evidence of a refusal.
#
# And `refused:`, added by that same commit, made the hole bigger rather
# than smaller. It is `pathsafety.py`'s prefix for EVERY argument a tool
# dislikes -- `refused: 'foo(' is not a valid regex`, `refused: 'x' is
# not a file`, `refused: path is 5000 chars`, `refused: no 'node'
# executable found on this machine`. None of those is the system
# protecting anything; they are a tool saying the arguments were wrong,
# which is the ordinary shape of a task failing. Quoting one into the
# evidence dropped a required "no" and passed the task (observer,
# 2026-09-10). It names neither a refuser nor a target, so it does not
# belong here. Guardian's own denial reaches a step as `denied:
# <reasons>` (orchestration/session.py:887), and path safety's
# PROTECTIVE refusals say what they protected -- those are listed
# instead, by their own words.
_REFUSAL_EVIDENCE = (
    "guardian denied", "was denied", "denied by", "denied (policy)", "denied:",
    "guardian refused", "guardian declined", "guardian blocked",
    "protected path", "protected file", "is a protected", "protected by guardian",
    "only the creator",
    "outside the readable areas", "looks like a credentials path",
    "resolves outside the repository", "is not a safe relative path",
)


def _refused_rather_than_failed(evidence: str) -> bool:
    lowered = (evidence or "").lower()
    return any(phrase in lowered for phrase in _REFUSAL_EVIDENCE)


def _all_refusals(answered_items) -> bool:
    negatives = [a for a in answered_items if a.answer == "no"]
    return bool(negatives) and all(_refused_rather_than_failed(a.evidence) for a in negatives)


def combine(
    mechanical_results: list[tuple[str, CheckResult]],
    answered_items: list[AnsweredItem],
    trajectory: TrajectoryMetrics,
    config: VerificationConfig,
) -> CombinedResult:
    mechanical_payload: dict = {name: {"status": r.status, "detail": r.detail} for name, r in mechanical_results}
    mechanical_payload["ledger"] = trajectory.available
    suite = next((r for name, r in mechanical_results if name == "isolated_suite" and r.evidence), None)
    if suite is not None:
        mechanical_payload["baseline"] = suite.evidence.get("baseline")
        mechanical_payload["patched"] = suite.evidence.get("patched")
        mechanical_payload["tests_passed"] = suite.evidence.get("passed")

    for name, result in mechanical_results:
        if result.status == "failed":
            return CombinedResult("fail", [], result.feedback, mechanical_payload)

    checklist_payload = [_checklist_item_payload(a) for a in answered_items]

    # An item whose evidence is "Guardian denied it" is not a defect in
    # the work: the scaffold tells the model "a denial is an answer, not
    # an error", and the system then scored that answer as a failure and
    # paid for revisions. A refusal cost MORE provider budget than a
    # success (observer, 2026-09-08).
    required_no = [
        a for a in answered_items
        if a.required and a.answer == "no" and not _refused_rather_than_failed(a.evidence)
    ]
    if required_no:
        failed_items = tuple(
            FailedItem(question=a.question, evidence=a.evidence, suggestion=f"address: {a.question}")
            for a in required_no
        )
        feedback = Feedback(
            failed_items=failed_items,
            revise_hint="; ".join(f"{i.question}: {i.evidence}" for i in failed_items),
            retryable=True,
        )
        return CombinedResult("fail", checklist_payload, feedback, mechanical_payload)

    # Proposing something and being denied, then stopping, is the
    # behaviour we ask for. Only count it against the task when the work
    # itself also failed on its merits.
    if trajectory.denied_actions >= config.max_denied_actions and not _all_refusals(answered_items):
        reason = f"the task proposed {trajectory.denied_actions} disallowed action(s) -- it did not understand its constraints"
        feedback = Feedback(mechanical_errors=(reason,), revise_hint=reason, retryable=True)
        return CombinedResult("fail", checklist_payload, feedback, mechanical_payload)

    if answered_items:
        answered_fraction = sum(1 for a in answered_items if a.answer is not None) / len(answered_items)
        if answered_fraction < config.checklist_min_answered_fraction:
            return CombinedResult("insufficient_evidence", checklist_payload, None, mechanical_payload)

    return CombinedResult("pass", checklist_payload, None, mechanical_payload)
