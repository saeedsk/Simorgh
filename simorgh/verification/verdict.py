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

    required_no = [a for a in answered_items if a.required and a.answer == "no"]
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

    if trajectory.denied_actions >= config.max_denied_actions:
        reason = f"the task proposed {trajectory.denied_actions} disallowed action(s) -- it did not understand its constraints"
        feedback = Feedback(mechanical_errors=(reason,), revise_hint=reason, retryable=True)
        return CombinedResult("fail", checklist_payload, feedback, mechanical_payload)

    if answered_items:
        answered_fraction = sum(1 for a in answered_items if a.answer is not None) / len(answered_items)
        if answered_fraction < config.checklist_min_answered_fraction:
            return CombinedResult("insufficient_evidence", checklist_payload, None, mechanical_payload)

    return CombinedResult("pass", checklist_payload, None, mechanical_payload)
