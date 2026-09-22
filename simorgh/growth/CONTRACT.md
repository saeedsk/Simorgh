# growth — what Sim learns about itself, and what it does about it

## Purpose

Growth owns the loop from "this keeps going wrong" to "we do it differently now, and here is the measurement". It must never decide what counts as a pattern by asking a model: failures cluster on facts already recorded (task type, failed verify check, denied tool, the critic's unmet item), counting is deterministic and free, and the model is asked one thing only — to phrase a lesson the counting already found. It must never adopt a policy without a measurement against a stored baseline, and every policy is reversible and time-bounded. The shaping decision: a lesson that only becomes a memory record changes nothing, because the next session recalls it only if the vocabulary happens to match; a policy is the durable form, with its evidence, its baseline and a way back.

Since stage 8 item 1 (2026-09-20) Growth is also the **merge** of learning, reflection and curiosity. Those three subsystems answered the same question -- how should Sim be different tomorrow? -- separately, so a failure cluster one found never reached the estimate another kept. They are now three parts of one Subsystem, and the Kernel boots 16 rather than 18.

**Every topic is preserved.** `learn.*`, `reflect.*` and `curiosity.*` are published and subscribed exactly as before; the merge changed the owner, not the wire. The one visible difference is `source` on the bus and in the ledger: these events now come from `growth`.

## Files

| File | For |
|---|---|
| `simorgh/growth/service.py` | the Subsystem: unions the parts' manifests, starts each with its own `[growth.<part>]` section, fans out `stop`/`health` |
| `simorgh/growth/estimate/` | what Sim is good at, from outcomes: outcome recording, the competence table, strategy suggestion. The table FORGETS exponentially (`competence.HALF_LIFE_S`, `[growth.estimate] competence_half_life_days`, 30 by default, 0 to turn it off): sums are aged in place on write, so what Sim was bad at in the spring stops outvoting what it is good at now. `samples` is therefore an EFFECTIVE count and a float -- every consumer turning it into a whole number must ROUND, because five outcomes seconds apart read as 4.999997 and `int()` loses one at every boundary. `expected_calibration_error` answers "when Sim says 80%, does it happen 80% of the time" from the `calib_bins` that had been recorded and persisted since the table was written and read by nothing; it appears on an estimate as `ece`, and is ABSENT rather than 0.0 when nothing was measured, because 0.0 reads as perfectly calibrated. `provider_quality(provider, purpose=...)` and `providers()` (worst first) roll the same strategy counts up across task types -- a strategy is keyed `provider:purpose[:edit_mode]`, so "how good is together at drafting" was answerable and unaskable; a provider never used is Beta(1,1), not half the time. **On the wire `samples` is a Float** (`learn.competence.updated`, `self.estimate.reply`, `learn.strategy.suggest.reply`): it is an effective count, and an `Int` there rejected every publish the moment forgetting landed -- live in the creator's session, one ContractError per completed task, with the module tier green throughout because nothing ran what the table produces past the schema that carries it |
| `simorgh/growth/monitors/` | what is going wrong, watched (was `simorgh/growth/monitors/`): drift, calibration, health findings, critique, denial analysis, pattern mining, distillation, digests. Distillation refuses a task whose ORIGIN is in `distillation.NOT_WORTH_KEEPING` -- `benchmark` today: a GAIA question is a one-off chosen to be hard, not a job the household will ask for again, and the creator's run of 2026-09-20 left eleven skill-writing tasks queued behind it, one named after a YouTube id. An unknown origin is treated as ordinary work, because older records carry none and refusing to learn from all of them would cost more than the waste |
| `simorgh/growth/explore/` | what is worth finding out (was `simorgh/growth/explore/`): drives, the diversity sampler, ideas, project proposals, interests, sharing pace |
| `simorgh/growth/diagnose.py` | `Failure`, `Cluster`, `cluster()`: terminal failures grouped by what they share; `phrasing_prompt` is the only thing a model is asked. `Candidate.refs` (2026-09-22) is where a person reads the evidence -- `task:<id>` per member of a failure cluster, `reflect:patterns:<task_type>` for the pattern miner -- and becomes a proposed policy's `evidence_refs` |
| `simorgh/growth/propose.py` | the night's `propose` step (2026-09-22): `propose_from(candidates, store, think, cfg, agents=)` drafts one rule per new candidate with one cheap `cognition.think` and proposes it through `PolicyStore.propose`, behind the guard rails in "The night" below; `propose_config` reads the keys below; `unsafe(text)` is the not-advice / protected-path rejection |
| `simorgh/growth/policies.py` | `Policy`, `PolicyStore`: propose → adopt-with-a-measurement (or `refuse`) → retire, over `growth:policies` |
| `simorgh/growth/evaluate.py` | stage 8 item 5: `evaluate(body, run_cases, repeats=3)` runs the held-out cases with and without a candidate, majority per case; `measure_and_decide` refuses on any regressed case (even at a flat mean) and otherwise lets `adopt` apply "no regression + one motivating case fixed". An adopted `rule` is handed to `land` as `adoption_action(policy)` -- an `action.proposed(policy_adopt)` on `rules/<task_type>.md` that Guardian asks a person about. When no case counted on both sides (every case skipped: an outage, a dataset that would not load) nothing is decided and the policy stays proposed, rather than being refused for ever over an outage |
| `simorgh/growth/measure.py` | the live caller of `measure_and_decide` (stage 8 item 5, the night's `measure` step). `SuiteCases` is a real `run_cases`: one run of the task type's held-out evals suite (`[growth] held_out`) in a fresh copy of the repo's committed HEAD (`copy_repo`, via `git archive`) -- never the live checkout -- with the candidate appended to the copy's `rules/<task_type>.md` for the "with" side, run as `python -m simorgh.evals run <suite> --repeats 1 --json --paid --cases N` in a child interpreter whose cwd and `PYTHONPATH` are the copy (so `orchestration/profiles.py` reads the copy's `rules/`). Skipped cases count on neither side; each run's reported `cost_usd` is summed, and a run that reports nothing is charged `measure_usd_per_run`. `measure_one` is the step; `measure_config` reads the keys below |

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
| `cognition.think` | `messages/cognition.py::CognitionThink` | `service.py::_think_draft` (as well as the monitors' and explorer's own) | the night's `propose` step drafts a rule: `purpose: review`, `max_tokens` 200, `max_cost_usd` = `propose_usd_per_draft`, request/reply with `propose_timeout_s`. Only when `propose_policies = true` |
| `growth.policy.adopted` | `messages/growth.py::GrowthPolicyAdopted` | `policies.py::PolicyStore._announce` | a policy cleared its measurement: carries `baseline`, `result`, `evaluated_on`, `ttl_s` |
| `growth.policy.retired` | `messages/growth.py::GrowthPolicyRetired` | `policies.py::PolicyStore._announce` | a TTL ran out, or the task type got worse; carries the reason |
| `action.proposed` | `messages/action.py::ActionProposed` | `service.py::_land` (and, as before, the monitors' digest and the explorer) | the night's `measure` step ADOPTED a `rule`: `adoption_action(policy)`, tool `policy_adopt` on `rules/<task_type>.md`, `reversibility: irreversible`, `proposed_by: growth`. Only Guardian subscribes; `rules/` is an `ask_subjects` path, so a person says yes before the file is written (`execution/policyadopt.py`) |

A **refusal** is not announced. It changed nothing, and a household that hears about every rejected idea stops listening for the accepted ones; it is in `growth:policies` for whoever looks. `lesson.found` and `policy.proposed` are allow-listed announcements for the same reason: they are what Sim is thinking about, not what it has done.

`policy.adopted` and `policy.retired` have a real consumer -- the Interface prints one line with the measurement (`_on_policy_changed`). A behaviour change nobody can see is a behaviour change nobody consented to, and finding it out from a ledger stream is not being told.

## The night (stage 8 item 8)

Everything here happens when nobody is asking for anything, which is also when nobody is watching the bill. So a night is a fixed list of steps, each run **once**, in order, against one budget that caps the **day** rather than the function (`night.py::run_night`, `[growth] nightly_usd`, default $0.50).

| Step | Costs | Does |
|---|---|---|
| `evals` | free | re-reads `evals.jsonl`, so the morning's estimates rest on the latest run rather than on whatever was there at boot |
| `review` | free | retires policies whose TTL ran out or whose task type got worse (item 6) |
| `diagnose` | free | counts what keeps going wrong and writes the candidates (item 3); keeps them for `propose` |
| `propose` | `2 x propose_max x propose_usd_per_draft` ($0.08 at the defaults: every draft the night may make, each at the ceiling handed to Cognition) | OFF by default (`propose_policies`). For each of tonight's candidates, strongest first: only a candidate about a KIND OF WORK (source `failures` or `patterns`; a denial is about a tool) whose task type is an agent name (`agents/<task_type>.md` exists -- the rule lands in `rules/<task_type>.md` and `orchestration/profiles.py` reads `rules/<agent>.md`); only with evidence refs; not a cause that already has a proposed or live rule for that task type (the policy's `why` begins `cause: <what>`) -- all checked BEFORE any draft. Then ONE `cognition.think` (`purpose: review`, `max_tokens` 200, `max_cost_usd` = `propose_usd_per_draft`) asking for one or two sentences of advice to the agent that does the work. Nothing is proposed from a floor, error, non-answer, empty or `NONE` reply; a draft over 600 characters (`execution/policyadopt.py::MAX_RULE_CHARS`) or more than two-ish sentences; a draft that is not advice (tells the agent to skip, bypass, disable, ignore... tests, verification, checks, review, approval or Guardian, or calls them optional) or that mentions Guardian, a protected path, `rules/`, `agents/` or auto-approval at all -- rejected on the safe side on purpose; or a draft whose normalised text similarity to a proposed, live or REFUSED rule of the same task type is >= 0.8 (`propose.SIMILAR`): a refused text is never proposed again. What remains is proposed as a `rule` with the candidate's refs as `evidence_refs`, announced as `growth.policy.proposed`. At most `propose_max` proposals and `2 x propose_max` drafts a night. Everything passed over is in the step's `detail`. The `measure` steps are built before the night runs, so a rule proposed tonight is measured the NEXT night |
| `measure:<policy id>` | `2 x measure_repeats x measure_usd_per_run` (the worst case: each run at its cap) | item 5, OFF by default. One step per PROPOSED `rule`: its task type's held-out suite (`[growth] held_out`) with and without the candidate, `measure_repeats` (3) a side, majority per case, refused on any regressed case, adopted on "no regression + one case fixed", and an adopted rule landed as `action.proposed(policy_adopt)`. A task type with no held-out suite is not run: the step is recorded as skipped ("no held-out suite for X") and the policy stays proposed -- never adopted without a measurement. A step the remaining budget cannot cover is skipped by `run_night` before anything is spent. A non-`rule` kind is recorded as skipped (only rules can be measured today). Off, or nothing proposed, is one free `measure` step recorded as skipped with the reason |

A step can decline on its own by returning `{"skipped": why}`; `run_night` records it as skipped (not in `ran`). The day the budget counts against is the Context clock's day: `_spent_today` resets when it changes (before, it never reset, so the cap was on the process's lifetime).

**At the defaults, switching measuring on is not enough**: one rule costs up to $3.00 (2 x 3 x $0.50, the benchmark sandbox's own cap per run) and the night is $0.50. The creator raises `nightly_usd` (or lowers `measure_usd_per_run`/`measure_cases`) on purpose, as the approval for paid runs.

Cheapest first, deliberately: stopping early is the ordinary outcome, and the order means what is lost when it happens is the least important thing. The cap is checked **before** a step runs, because a model call cannot be taken back once it has been made; a step that does not report what it spent is charged its estimate rather than nothing, because guessing zero is how a budget quietly stops being one. A step that raises is recorded and the night goes on -- one bad step at 3am should not mean no evals ran.

**Where the candidates come from, live.** `monitors/service.py::_record_candidates` feeds `diagnose.candidates` the terminal failures the monitors saw within `pattern_window_seconds` (newest 200 kept in memory): each `Failure` carries the task type, the first failed mechanical check of its last failing `verify.result` ("checklist" when only the checklist failed), and the last tool Guardian denied it. Benchmark cases (`origin: benchmark`) are left out -- they are not the house's work. Plus the pattern miner's falling success rates and the denial miner's repeats (passed over by `propose`). Until 2026-09-22 the failures list was empty, so no cluster of the same failure could ever become a lesson. `unmet` (the checkpoint critic's) is not collected yet.

## Exploring (stage 8 item 7)

`explore/thompson.py`. Each target -- a repo area, a recurring question nobody answered, a stale high-query fact, a device never probed, a skill never exercised -- has a Beta posterior, one draw is taken from each, and the **lowest draw wins**: Sim goes where it is worst. Anything unmeasured gets the flat prior, which says "no idea" rather than "probably fine". Boredom still flattens by temperature, which here widens the draws rather than the softmax.

**The sampler's diversity rule is load-bearing, not decoration.** Lowest-draw-wins alone finds the worst thing rather than exploring: a target measured 80 times that always fails draws tightly around 0.01 and beats a flat prior 99 times in 100, so one hopeless area took 393 of 400 rounds in the first version and the unmeasured targets never came up. With `recent` (just-visited targets to the back until everything is recent, then a fresh lap -- `DriveWeightedSampler`'s own rule), the same 400 rounds spread 134 / 133 / 131 across the three uncertain targets and 2 to the one Sim is confidently good at. Starving that last one is correct: there is nothing left to learn there.

`DriveWeightedSampler` is unchanged and its regression test is untouched.

## Config

`[growth]` in simorgh.toml. Each part reads its own `[growth.<part>]` section (`estimate`, `monitors`, `explore`), which the composite hands it at start.

| Key | Default | Read in the package |
|---|---|---|
| `nightly_usd` | `0.50` | yes (`service.py::nightly_usd`) -- what one night may spend, counted against the day. Anything unreadable falls back to the default rather than to no cap |
| `measure_policies` | `false` | yes (`measure.py::measure_config`) -- the night measures proposed rules only when this is literally `true`: the held-out suites cost money and paid runs are approved explicitly. Anything else is off |
| `held_out` | `{}` | yes -- task type -> evals suite name (`simorgh/evals/suites.py::SUITES`), e.g. `held_out = {research = "research", chat = "tooluse"}`. A task type not listed is never measured, so never adopted. The rule lands in `rules/<task_type>.md`, which `orchestration/profiles.py` reads per AGENT name, so it only reaches a body when the task type is also an agent name (`agents/*.md`) |
| `measure_repeats` | `3` | yes -- runs per side; the majority of the repeats decides each case |
| `measure_usd_per_run` | `0.50` | yes -- what one suite run is priced at for the budget check (the sandbox's cap). Unreadable falls back to the default, never to free |
| `measure_cases` | `5` | yes -- `--cases` per run |
| `measure_timeout_s` | `1800` | yes -- one run's wall clock before the child is killed (the step then fails and is recorded; the policy stays proposed) |
| `propose_policies` | `false` | yes (`propose.py::propose_config`) -- the night drafts and proposes rules only when this is literally `true`: every draft is a paid model call. Anything else is off |
| `propose_max` | `2` | yes -- proposals per night; drafts are capped at twice this, so rejected drafts cannot spend the night |
| `propose_usd_per_draft` | `0.02` | yes -- the `max_cost_usd` handed to Cognition per draft and the price the budget check uses. Unreadable falls back to the default, never to free |
| `propose_timeout_s` | `60` | yes -- how long one draft is waited for; a timeout drafts nothing |

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
- `tests/simorgh/growth/test_the_night_proposes_a_rule.py` — with fake think replies and fake candidates: a cluster yields one proposal citing its task refs (schema-valid `growth.policy.proposed`); a duplicate is not proposed; a cause with a proposed rule is not even drafted; a refused text is never re-proposed; a floor/error/empty/NONE/non-answer proposes nothing; "skip the tests", "tests are optional", Guardian and protected paths are rejected; the length bound matches the adopt tool's; the cap holds on proposals and on drafts; a task type with no agent and a denial are passed over and recorded; off by default; over budget is refused before any draft.
- `tests/simorgh/growth/test_the_night_measures_a_proposed_rule.py` — with fakes, no paid call: a proposed rule with a held-out suite is measured and, fixing a case, published as `action.proposed(policy_adopt)` (schema-valid); no held-out suite is skipped and recorded; over budget is skipped before anything runs; off by default nothing runs; the candidate is written into the copy, never the live repo.

## Planned changes (roadmap)

- Stage 8 item 1: merge `learning`, `reflection` and `curiosity` here, every topic still published.
- Items 2 and 5-8: posteriors fed from verify-backed outcomes and eval rates; propose → evaluate on a held-out set in a worktree → adopt as a committed file through `action.proposed(policy_adopt)`; monitor and retire on regression; Thompson-sampled exploration; the nightly loop under a cost cap.

## Working on this module

Lock it first (`python tools/modlock.py claim growth --by <you> --task "..."`), commit the lock, edit only `simorgh/growth/`, `tests/simorgh/growth/` and this file. Run `python tools/modtest.py growth`; commit subject `growth: <what changed>`.
