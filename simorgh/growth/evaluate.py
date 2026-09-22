"""Measure a proposed policy before it is adopted (stage 8 item 5).

`PolicyStore.adopt` refuses without a measurement; this is what makes
one. A candidate is run on its task type's held-out cases, `repeats`
times, beside the same cases without it, and the store decides:

- **no regression** -- no case that passed without the policy fails with
  it. Per case, not only on the mean: a rule that fixes one case and
  breaks another has the same mean and is not an improvement anybody
  asked for;
- **at least one motivating case fixed** -- a case that failed without
  it passes with it. A change that makes nothing worse and nothing
  better is not adopted.

"Passes" is a majority of the repeats, so one lucky run neither fixes
nor breaks anything. How the cases are run is the caller's:
`run_cases(rules)` returns `{case: passed}` for one pass over the
held-out set with `rules` in the agent's body (None for the baseline)
-- in production a suite in a repo copy with `rules/<task_type>.md`
written, in a test a table. Nothing here writes the rule: an adopted `rule`
becomes an `action.proposed(policy_adopt)` through `land`, and Guardian
asks a person before `rules/` changes (the creator's choice, 2026-09-22).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

RunCases = Callable[[str | None], Awaitable[dict[str, bool]]]

#: Repeats per side. Three is the least that has a majority.
DEFAULT_REPEATS = 3


@dataclass(frozen=True)
class Evaluation:
    baseline: float          # share of cases passing without the policy
    result: float            # ...and with it
    evaluated_on: int        # cases measured on both sides
    fixed: tuple[str, ...]   # failed without, pass with
    regressed: tuple[str, ...]  # passed without, fail with


def _majority(runs: list[dict[str, bool]]) -> dict[str, bool]:
    cases = set().union(*runs) if runs else set()
    return {c: sum(1 for r in runs if r.get(c)) * 2 > len(runs) for c in cases}


async def evaluate(body: str, run_cases: RunCases, *, repeats: int = DEFAULT_REPEATS) -> Evaluation:
    """Both sides, `repeats` times each, interleaved so a provider having
    a slow hour costs both sides alike."""
    repeats = max(1, int(repeats))
    without: list[dict[str, bool]] = []
    with_it: list[dict[str, bool]] = []
    for _ in range(repeats):
        without.append(dict(await run_cases(None)))
        with_it.append(dict(await run_cases(body)))
    base, cand = _majority(without), _majority(with_it)
    cases = sorted(set(base) & set(cand))
    if not cases:
        return Evaluation(0.0, 0.0, 0, (), ())
    return Evaluation(
        baseline=sum(base[c] for c in cases) / len(cases),
        result=sum(cand[c] for c in cases) / len(cases),
        evaluated_on=len(cases),
        fixed=tuple(c for c in cases if cand[c] and not base[c]),
        regressed=tuple(c for c in cases if base[c] and not cand[c]),
    )


def adoption_action(policy) -> dict:
    """The `action.proposed` payload that lands an adopted rule: the
    `policy_adopt` tool on `rules/<task_type>.md`. Guardian asks a
    person before it runs (`ask_subjects`), and only then does the rule
    reach the agent body."""
    import uuid

    path = f"rules/{policy.task_type}.md"
    return {
        "action_id": f"growth-adopt-{policy.id}-{uuid.uuid4().hex[:6]}",
        "tool": "policy_adopt",
        "args": {"task_type": policy.task_type, "rule": policy.body, "policy_id": policy.id, "path": path,
                 "why": policy.why},
        "scope": {"paths": [path], "network": False},
        "reversibility": "irreversible",
        "rationale": f"adopt a measured lesson for {policy.task_type} work: {policy.why}",
        "proposed_by": "growth",
    }


async def measure_and_decide(store, policy_id: str, run_cases: RunCases, *,
                             repeats: int = DEFAULT_REPEATS, samples_now: int = 0, land=None):
    """Evaluate a proposed policy and record the store's verdict.

    Returns `(policy, evaluation)`. A regressed case refuses it whatever
    the mean says; otherwise `adopt` applies its two conditions.
    """
    policy = next((p for p in store.all() if p.id == policy_id), None)
    if policy is None or policy.status != "proposed":
        return None, None
    ev = await evaluate(policy.body, run_cases, repeats=repeats)
    if ev.regressed:
        refused = await store.refuse(policy_id, baseline=ev.baseline, result=ev.result,
                                     evaluated_on=ev.evaluated_on,
                                     why=f"regressed {', '.join(ev.regressed[:3])}")
        return refused, ev
    decided = await store.adopt(policy_id, baseline=ev.baseline, result=ev.result, evaluated_on=ev.evaluated_on,
                                fixed_a_motivating_case=bool(ev.fixed), samples_at_adoption=samples_now)
    if decided is not None and decided.status == "adopted" and land is not None and decided.kind == "rule":
        # Adoption is a verdict; landing is an action a person approves.
        await land(adoption_action(decided))
    return decided, ev


__all__ = ["DEFAULT_REPEATS", "Evaluation", "adoption_action", "evaluate", "measure_and_decide"]
