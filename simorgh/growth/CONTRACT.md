# growth — what Sim learns about itself, and what it does about it

## Purpose

Growth owns the loop from "this keeps going wrong" to "we do it differently now, and here is the measurement". It must never decide what counts as a pattern by asking a model: failures cluster on facts already recorded (task type, failed verify check, denied tool, the critic's unmet item), counting is deterministic and free, and the model is asked one thing only — to phrase a lesson the counting already found. It must never adopt a policy without a measurement against a stored baseline, and every policy is reversible and time-bounded. The shaping decision: a lesson that only becomes a memory record changes nothing, because the next session recalls it only if the vocabulary happens to match; a policy is the durable form, with its evidence, its baseline and a way back.

Since stage 8 item 1 (2026-09-20) Growth is also the **merge** of learning, reflection and curiosity. Those three subsystems answered the same question -- how should Sim be different tomorrow? -- separately, so a failure cluster one found never reached the estimate another kept. They are now three parts of one Subsystem, and the Kernel boots 16 rather than 18.

**Every topic is preserved.** `learn.*`, `reflect.*` and `curiosity.*` are published and subscribed exactly as before; the merge changed the owner, not the wire. The one visible difference is `source` on the bus and in the ledger: these events now come from `growth`.

## Files

| File | For |
|---|---|
| `simorgh/growth/service.py` | the Subsystem: unions the parts' manifests, starts each with its own `[growth.<part>]` section, fans out `stop`/`health` |
| `simorgh/growth/estimate/` | what Sim is good at, from outcomes (was `simorgh/growth/estimate/`): outcome recording, the competence table, strategy suggestion |
| `simorgh/growth/monitors/` | what is going wrong, watched (was `simorgh/growth/monitors/`): drift, calibration, health findings, critique, denial analysis, pattern mining, distillation, digests |
| `simorgh/growth/explore/` | what is worth finding out (was `simorgh/growth/explore/`): drives, the diversity sampler, ideas, project proposals, interests, sharing pace |
| `simorgh/growth/diagnose.py` | `Failure`, `Cluster`, `cluster()`: terminal failures grouped by what they share; `phrasing_prompt` is the only thing a model is asked |
| `simorgh/growth/policies.py` | `Policy`, `PolicyStore`: propose → adopt-with-a-measurement → retire, over `growth:policies` |

Each part keeps its own `CONTRACT.md` (`estimate/`, `monitors/`, `explore/`), its own config dataclass and its own tests, because they are separable and the merge is about ownership rather than entanglement.

## The parts, and why one part failing is not the subsystem failing

`Service.start` starts each part in order -- estimate, monitors, explore -- and a part that raises is logged (`growth.part_failed`), recorded, and skipped; the others run and `health()` reports degraded, naming which. Growth is the layer Sim can live without for an afternoon: none of it is on the path of answering a person, and taking the whole subsystem down over the explorer would stop the estimates a running task reads.

`Service(estimate=..., monitors=..., explore=...)` replaces a part, which is how a test drives one without booting the other two.

## What is worth a lesson (stage 8 item 3)

Three things used to notice that something keeps going wrong, in three shapes nobody could compare: `diagnose.cluster` over terminal failures, the denial miner (the same tool refused for the same reason, again and again) and the pattern miner (a task type whose success rate has fallen). They make the same claim, so they now arrive as one shape -- `diagnose.Candidate{source, subject, what, count, evidence}` -- through one entry point, `diagnose.candidates(failures, denials=, patterns=)`. The monitors keep watching; what counts as a pattern is decided in one place, by counting, so all three are held to the same bar.

The bar for a failure cluster is three things at once: at least `MIN_MEMBERS` (3) members, a share above the baseline for other task types, and **not** seen at strength across `GENERAL_ACROSS` (3) kinds of work. The last one exists because the share test alone does not catch it: a task type whose only failures are timeouts scores a share of 1.0 and looks specific to itself, when "patch tasks time out" is advice nobody can act on.

A model is asked exactly one thing, after the counting, about something already on the list: `candidate_prompt` asks for one sentence of advice and says "nothing you cannot see below".

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `growth.lesson.found` | `messages/growth.py::GrowthLessonFound` | `diagnose` through the monitors' pass | something keeps happening and the counting says it is specific enough to name. Not a decision |
| `growth.policy.proposed` | `messages/growth.py::GrowthPolicyProposed` | `policies.py::PolicyStore._announce` | a policy is written down. It has changed nothing yet |
| `growth.policy.adopted` | `messages/growth.py::GrowthPolicyAdopted` | `policies.py::PolicyStore._announce` | a policy cleared its measurement: carries `baseline`, `result`, `evaluated_on`, `ttl_s` |
| `growth.policy.retired` | `messages/growth.py::GrowthPolicyRetired` | `policies.py::PolicyStore._announce` | a TTL ran out, or the task type got worse; carries the reason |

A **refusal** is not announced. It changed nothing, and a household that hears about every rejected idea stops listening for the accepted ones; it is in `growth:policies` for whoever looks. `lesson.found` and `policy.proposed` are allow-listed announcements for the same reason: they are what Sim is thinking about, not what it has done.

`policy.adopted` and `policy.retired` have a real consumer -- the Interface prints one line with the measurement (`_on_policy_changed`). A behaviour change nobody can see is a behaviour change nobody consented to, and finding it out from a ledger stream is not being told.

## The night (stage 8 item 8)

Everything here happens when nobody is asking for anything, which is also when nobody is watching the bill. So a night is a fixed list of steps, each run **once**, in order, against one budget that caps the **day** rather than the function (`night.py::run_night`, `[growth] nightly_usd`, default $0.50).

| Step | Costs | Does |
|---|---|---|
| `evals` | free | re-reads `evals.jsonl`, so the morning's estimates rest on the latest run rather than on whatever was there at boot |
| `review` | free | retires policies whose TTL ran out or whose task type got worse (item 6) |
| `diagnose` | free | counts what keeps going wrong and writes the candidates (item 3) |

Cheapest first, deliberately: stopping early is the ordinary outcome, and the order means what is lost when it happens is the least important thing. The cap is checked **before** a step runs, because a model call cannot be taken back once it has been made; a step that does not report what it spent is charged its estimate rather than nothing, because guessing zero is how a budget quietly stops being one. A step that raises is recorded and the night goes on -- one bad step at 3am should not mean no evals ran.

Not built yet: the drafting step (a lesson phrased by the skill-writer agent) and the proposal step. They are the ones that cost money, and they would go last.

## Exploring (stage 8 item 7)

`explore/thompson.py`. Each target -- a repo area, a recurring question nobody answered, a stale high-query fact, a device never probed, a skill never exercised -- has a Beta posterior, one draw is taken from each, and the **lowest draw wins**: Sim goes where it is worst. Anything unmeasured gets the flat prior, which says "no idea" rather than "probably fine". Boredom still flattens by temperature, which here widens the draws rather than the softmax.

**The sampler's diversity rule is load-bearing, not decoration.** Lowest-draw-wins alone finds the worst thing rather than exploring: a target measured 80 times that always fails draws tightly around 0.01 and beats a flat prior 99 times in 100, so one hopeless area took 393 of 400 rounds in the first version and the unmeasured targets never came up. With `recent` (just-visited targets to the back until everything is recent, then a fresh lap -- `DriveWeightedSampler`'s own rule), the same 400 rounds spread 134 / 133 / 131 across the three uncertain targets and 2 to the one Sim is confidently good at. Starving that last one is correct: there is nothing left to learn there.

`DriveWeightedSampler` is unchanged and its regression test is untouched.

## Config

`[growth]` in simorgh.toml. Each part reads its own `[growth.<part>]` section (`estimate`, `monitors`, `explore`), which the composite hands it at start.

| Key | Default | Read in the package |
|---|---|---|
| `nightly_usd` | `0.50` | yes (`service.py::nightly_usd`) -- what one night may spend, counted against the day. Anything unreadable falls back to the default rather than to no cap |

## Ledger streams

| Stream | Written by | Read by | Retention |
|---|---|---|---|
| `learn:*`, `reflect:*`, `reflection:*`, `curiosity:*` | the parts, under their pre-merge names | as before | forever; the prefixes were kept so nothing written before the merge is orphaned, and `contracts/streamnames.py::WRITERS` names **growth** as their writer (it still named the three removed subsystems until 2026-09-20, and a bound ledger therefore refused every one of these writes) |
| `growth:candidates` | `monitors/service.py::_record_candidates` | nothing yet (a person, and item 4's adoption) | forever; one `candidate{source, subject, what, count, evidence}` per pass per candidate |
| `growth:policies` | `PolicyStore._write` | `PolicyStore.sync` | forever; one event per status change (`policy.proposed`, `policy.adopted`, `policy.refused`, `policy.retired`), never a deletion |

## Invariants

`BacklogCounter.count(now=)` is the backlog Curiosity gates exploration on: open tasks, minus ones blocked until a time that has not arrived. A retry time that HAS arrived puts its task back in the count -- before 2026-09-20 one block with any future retry discounted a task for ever, so a queue of them read as empty and Curiosity explored on top of it. `now` is always passed in; `effective_count` remains as a wall-clock shim for callers without one.

1. A cluster needs `MIN_MEMBERS` (3) failures **and** a share above the baseline for other task types: "patch tasks fail" is not a lesson, and neither is a failure mode every kind of work has equally.
2. A cluster whose cause nobody recorded is not a pattern; it is dropped rather than phrased.
3. `adopt` refuses without a measurement (`evaluated_on > 0`), refuses a result below the stored baseline, and refuses a policy that fixed none of the failures it came from — a change that makes nothing worse and nothing better is not an improvement.
4. A policy is retired, never deleted; a retirement is another event.
5. A policy whose measurement is older than its TTL (28 days) is retired: the world it was measured in was four weeks ago.

## Contract tests

- `tests/simorgh/growth/test_diagnose_and_policies.py` — thirty failures with two planted clusters and nothing else found; the three refusals; retirement and expiry.

## Planned changes (roadmap)

- Stage 8 item 1: merge `learning`, `reflection` and `curiosity` here, every topic still published.
- Items 2 and 5-8: posteriors fed from verify-backed outcomes and eval rates; propose → evaluate on a held-out set in a worktree → adopt as a committed file through `action.proposed(policy_adopt)`; monitor and retire on regression; Thompson-sampled exploration; the nightly loop under a cost cap.

## Working on this module

Lock it first (`python tools/modlock.py claim growth --by <you> --task "..."`), commit the lock, edit only `simorgh/growth/`, `tests/simorgh/growth/` and this file. Run `python tools/modtest.py growth`; commit subject `growth: <what changed>`.
