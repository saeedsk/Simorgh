"""Plan review (docs/blueprint/subsystems/10-verification.md section
5.5): mechanical items are computed (ordering vs. declared dependencies,
a protected target via `guardian.review`, step count), goal-coverage and
risk-plausibility are model-reviewed. Verdict: any mechanical failure or
a "no" on goal coverage -> `revise` with feedback; a protected target ->
`reject`; unanswered -> `insufficient_evidence`; else `approve`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .parsing import parse_verdict

_COVERAGE_PROMPT = """Project goal: {goal}

Proposed steps:
{steps}

Does every real facet of the goal get addressed by at least one step,
and does each step's stated reason ("why") genuinely tie back to the
goal? Answer with exactly one word first -- YES or NO -- then one short
sentence explaining why."""


@dataclass(frozen=True)
class PlanReviewResult:
    verdict: str  # approve | revise | reject | insufficient_evidence
    checklist: list[dict]
    feedback: str | None


def _item(q: str, answer: str, evidence: str = "") -> dict:
    # plan.reviewed.checklist[] requires q/answer/evidence, all strings
    # (contracts/schema/plan.reviewed.v1.json).
    return {"q": q, "answer": answer, "evidence": evidence}


def _ordering_violations(steps: list[dict]) -> list[str]:
    index_of = {s.get("step_id"): i for i, s in enumerate(steps)}
    problems = []
    for i, step in enumerate(steps):
        for dep in step.get("depends_on") or []:
            dep_index = index_of.get(dep)
            if dep_index is not None and dep_index > i:
                problems.append(
                    f"step {step.get('step_id')} depends on {dep}, which comes later in the plan"
                )
    return problems


async def review_plan(think, review, plan_payload: dict, max_steps: int) -> PlanReviewResult:
    steps = plan_payload.get("steps") or []
    checklist: list[dict] = []

    ordering_problems = _ordering_violations(steps)
    if ordering_problems:
        checklist.append(_item("dependency order is consistent", "no", "; ".join(ordering_problems)))
        return PlanReviewResult("revise", checklist, "; ".join(ordering_problems))
    checklist.append(_item("dependency order is consistent", "yes"))

    if len(steps) > max_steps:
        reason = f"plan has {len(steps)} steps, over the configured maximum of {max_steps}"
        checklist.append(_item("step count within limit", "no", reason))
        return PlanReviewResult("revise", checklist, reason)
    checklist.append(_item("step count within limit", "yes"))

    for step in steps:
        subject = step.get("subject")
        if not subject or step.get("kind") != "patch":
            continue
        reply = await review(subject, "", step.get("kind", "patch"))
        if reply.ok and not reply.approved and "protected" in reply.layers_run:
            checklist.append(_item(f"{subject} is not protected", "no", "; ".join(reply.reasons)))
            return PlanReviewResult("reject", checklist, f"step targets a protected subject: {subject}")
    checklist.append(_item("no step targets a protected subject", "yes"))

    steps_text = "\n".join(
        f"- {s.get('step_id')} ({s.get('kind')}): {s.get('description')} -- why: {s.get('why', '')}"
        for s in steps
    )
    reply = await think(purpose="review", prompt=_COVERAGE_PROMPT.format(goal=plan_payload.get("goal", ""), steps=steps_text))
    if reply.floor or not reply.ok:
        checklist.append(_item("goal coverage", "unanswered"))
        return PlanReviewResult("insufficient_evidence", checklist, None)
    answer = parse_verdict(reply.text)
    checklist.append(_item("goal coverage", answer or "unanswered", reply.text.strip()))
    if answer is None:
        return PlanReviewResult("insufficient_evidence", checklist, None)
    if answer == "no":
        return PlanReviewResult("revise", checklist, reply.text.strip())
    return PlanReviewResult("approve", checklist, None)
