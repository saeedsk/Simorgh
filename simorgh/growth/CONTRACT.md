# growth — what Sim learns about itself, and what it does about it

## Purpose

Growth owns the loop from "this keeps going wrong" to "we do it differently now, and here is the measurement". It must never decide what counts as a pattern by asking a model: failures cluster on facts already recorded (task type, failed verify check, denied tool, the critic's unmet item), counting is deterministic and free, and the model is asked one thing only — to phrase a lesson the counting already found. It must never adopt a policy without a measurement against a stored baseline, and every policy is reversible and time-bounded. The shaping decision: a lesson that only becomes a memory record changes nothing, because the next session recalls it only if the vocabulary happens to match; a policy is the durable form, with its evidence, its baseline and a way back.

Since stage 8 item 1 (2026-09-20) Growth is also the **merge** of learning, reflection and curiosity. Those three subsystems answered the same question -- how should Sim be different tomorrow? -- separately, so a failure cluster one found never reached the estimate another kept. They are now three parts of one Subsystem, and the Kernel boots 16 rather than 18.

**Every topic is preserved.** `learn.*`, `reflect.*` and `curiosity.*` are published and subscribed exactly as before; the merge changed the owner, not the wire. The one visible difference is `source` on the bus and in the ledger: these events now come from `growth`.

## Files

| File | For |
|---|---|
| `simorgh/growth/service.py` | the Subsystem: unions the parts' manifests, starts each with its own `[growth.<part>]` section, fans out `stop`/`health` |
| `simorgh/growth/estimate/` | what Sim is good at, from outcomes (was `simorgh/learning/`): outcome recording, the competence table, strategy suggestion |
| `simorgh/growth/monitors/` | what is going wrong, watched (was `simorgh/reflection/`): drift, calibration, health findings, critique, denial analysis, pattern mining, distillation, digests |
| `simorgh/growth/explore/` | what is worth finding out (was `simorgh/curiosity/`): drives, the diversity sampler, ideas, project proposals, interests, sharing pace |
| `simorgh/growth/diagnose.py` | `Failure`, `Cluster`, `cluster()`: terminal failures grouped by what they share; `phrasing_prompt` is the only thing a model is asked |
| `simorgh/growth/policies.py` | `Policy`, `PolicyStore`: propose → adopt-with-a-measurement → retire, over `growth:policies` |

Each part keeps its own `CONTRACT.md` (`estimate/`, `monitors/`, `explore/`), its own config dataclass and its own tests, because they are separable and the merge is about ownership rather than entanglement.

## The parts, and why one part failing is not the subsystem failing

`Service.start` starts each part in order -- estimate, monitors, explore -- and a part that raises is logged (`growth.part_failed`), recorded, and skipped; the others run and `health()` reports degraded, naming which. Growth is the layer Sim can live without for an afternoon: none of it is on the path of answering a person, and taking the whole subsystem down over the explorer would stop the estimates a running task reads.

`Service(estimate=..., monitors=..., explore=...)` replaces a part, which is how a test drives one without booting the other two.

## Ledger streams

| Stream | Written by | Read by | Retention |
|---|---|---|---|
| `growth:policies` | `PolicyStore._write` | `PolicyStore.sync` | forever; one event per status change (`policy.proposed`, `policy.adopted`, `policy.refused`, `policy.retired`), never a deletion |

## Invariants

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
