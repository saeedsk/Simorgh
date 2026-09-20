# Stage 8 -- Growth merge and the policy loop

Status: **in progress** (2026-09-20: items 1, 2 and 3 done; item 4 in part) · Depends on: stages 4, 6, 7 (it consumes the eval sets and the Self Model they build) · Estimated: 3 weeks · Modules touched: learning, reflection, curiosity (merged into growth), guardian, orchestration, contracts, evals

## Outcome

Learning, Reflection and Curiosity become one `growth/` package whose only output is a proposal through the gate. Experience changes future behaviour, and only when a held-out eval shows it helps: a typed policy artifact (task-type rule, skill, routing change, code patch) is proposed with evidence, evaluated on a tagged case set in a worktree with repeats, adopted as a committed file under a Guardian-protected root, monitored, and retired on TTL or posterior drop. Competence is fed from verified outcomes and eval pass rates, never from self-reports. Idle exploration is Thompson-sampled over posteriors and household unknowns. The loop cannot loosen its own gate.

## Why

Evaluation C1/C2/C14 (the open loop), section 8.1 growth row, section 9.5. The judges' resolution: the policy store is the container, eval pass rate is the promotion signal, "only a proposal through the gate" is the safety property, and rules land only as committed protected files A/B'd before active, never as a live-mutable prompt store.

## Before you start

Every task type that a policy could target must have a held-out case set with a stored baseline in `simorgh/evals/` (stage 4). Read `learning/competence.py`, `learning/strategy.py`, `reflection/` (pattern mining, `distillation.py`, denial analysis), `curiosity/sampler.py` (diversity by construction; keep it and its regression test verbatim), `curiosity/drives.py`.

## Action items

Done 2026-09-19 (items 3-4, in part): the `growth` package exists with the two halves that stand alone. `diagnose.py` clusters terminal failures deterministically by (task type, failed check, denied tool, the critic's unmet item), needs three members and a share above the baseline for other task types, drops clusters whose cause nobody recorded, and asks a model only to phrase what the counting found. `policies.py` is the durable record: propose, adopt only against a stored baseline with at least one motivating case fixed, retire (never delete), and expire with the measurement's TTL. Not started: item 1's merge of learning, reflection and curiosity -- those subsystems still run -- and items 2, 5-8.

1. **The merge, topics preserved.** *Lock `learning`, `reflection`, `curiosity`, `growth` (new), `kernel`, `shared`, `docs`.* `simorgh/growth/{estimate,diagnose,policies,explore,monitors,service}.py`; every `learn.*`, `reflect.*`, `curiosity.*` topic still published so no consumer changes; `sampler.py` moved verbatim; LAYERS layer 4 becomes `("growth",)`; boundary test, AGENTS.md table, locks updated. Acceptance: the boot test lists 16 subsystems; every previous topic still has both sides.
2. **Estimate.** *Lock `growth`.* Posteriors from stage 6's Self Model, fed from two weighted sources: verify-backed task outcomes and eval pass rates; chat self-reports never count. Acceptance: a seeded outcome stream plus an eval history yields the expected posterior.
3. **Diagnose.** *Lock `growth`.* Deterministic clustering of terminal failures by `(task_type, failed verify check, denied tool, critic unmet-item hash)`; a cluster with ≥ 3 members above the type's baseline becomes a lesson candidate; the model is asked only to phrase it. Reflection's pattern and denial miners fold in. Acceptance: a fixture of 30 failures yields the two planted clusters and no others.
4. **The policy store.** *Lock `growth`, `contracts`.* `growth:policies` with `{id, kind: rule|skill|routing|patch, task_type|purpose, body, evidence_refs, evaluated_on, baseline, result, adopted_at, ttl, status}`; topics `growth.policy.proposed/adopted/retired`, `growth.lesson.found`. Acceptance: schema tests; both-sides test.
5. **Propose → evaluate → adopt.** *Lock `growth`, `guardian`, `execution`, `orchestration`.* A candidate is run on its task type's held-out set in a worktree, ≥ 3 repeats, against the stored baseline; adopted only on no regression plus at least one motivating case fixed; adoption lands as a committed file through `action.proposed(policy_adopt)`: `rules/<task_type>.md` rendered into the agent body; skills as `SKILL.md` in `simorgh_skills/`; routing as a config change; patches through worktree landing. `rules/`, `simorgh_skills/`, `agents/`, the hooks list and the evals gate config join Guardian's protected subjects, so the loop can never loosen its own gate. Acceptance: a planted lesson that fixes a held-out case is adopted; one that regresses another is refused; an adoption that touches `guardian/` is denied at `protected`.
6. **Monitor and retire.** *Lock `growth`.* A policy's task type is watched after adoption; TTL expiry or a posterior drop below the pre-adoption baseline retires it with bounded rollback (the loader's shape: revert the file, land through the gate). Acceptance: a policy whose type regresses is retired within the window.
7. **Explore.** *Lock `growth`.* Thompson sampling over posteriors and world-model unknowns (draw per area, pick the lowest draw) with the sampler's diversity kept; the target space extends from repo areas to unanswered recurring questions, stale high-query facts, devices never probed, skills never exercised; boredom still flattens by temperature. Acceptance: the sampler regression test unchanged; a seeded posterior set produces the expected exploration order.
8. **The nightly loop.** *Lock `growth`, `kernel`.* On `system.tick.sleep`, budget-capped on the cheap tier: run evals and benchmarks, mine failed traces, draft skills with the skill-writer agent, extract facts, propose routing/prompt/config changes; a daily cost cap. Acceptance: a fake-clock night runs each step once and stops at the cap.
9. **Routine mining (only once HA history exists).** *Lock `growth`, `execution`.* Histograms and windowed episode mining over HA history, person-conditioned; suggestions with a proposed → shown → accepted|declined lifecycle, installed as HA automations through tier-3 tools. Deferred until four weeks of history exist.
10. **Findings entry** with policies adopted vs retired and surviving 30 days, eval delta per adoption, regressions attributed to a policy (target 0), exploration yield, nightly cost.

## Measurements after

| Number | Target |
|---|---|
| Benchmark and eval trend per week per model | rising or flat, never a regression attributed to a policy |
| Policies surviving 30 days vs retired | recorded |
| Learning-driven changes that reached the house without a person | 0 |
| Exploration yield (curiosity tasks that raised a posterior) | recorded |

## Risks and mitigations

- The highest risk in the plan: a self-modifying loop with weak evals adopts overfitted rules. No policy kind is adoptable until its task type has a held-out set with a stored baseline; rules and skills are files, never a live store; every adoption is a revertible ledger event and a commit; the loop cannot touch its own gate.
- Nightly cost: capped by budget; the cheap tier only.

## Definition of done

- [ ] Items 1-8 with tests; `growth/CONTRACT.md` written; the three old contracts removed.
- [ ] Guardian protects `rules/`, `simorgh_skills/`, `agents/`, hooks, evals config.
- [ ] Findings entry.
