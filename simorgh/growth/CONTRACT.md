# growth — what Sim learns about itself, and what it does about it

## Purpose

Growth owns the loop from "this keeps going wrong" to "we do it differently now, and here is the measurement". It must never decide what counts as a pattern by asking a model: failures cluster on facts already recorded (task type, failed verify check, denied tool, the critic's unmet item), counting is deterministic and free, and the model is asked one thing only — to phrase a lesson the counting already found. It must never adopt a policy without a measurement against a stored baseline, and every policy is reversible and time-bounded. The shaping decision: a lesson that only becomes a memory record changes nothing, because the next session recalls it only if the vocabulary happens to match; a policy is the durable form, with its evidence, its baseline and a way back.

Stage 8 item 1 (merging learning, reflection and curiosity into this package) is **not** done: those subsystems still run. What is here are the two halves that stand alone and that the merge keeps.

## Files

| File | For |
|---|---|
| `simorgh/growth/diagnose.py` | `Failure`, `Cluster`, `cluster()`: terminal failures grouped by what they share; `phrasing_prompt` is the only thing a model is asked |
| `simorgh/growth/policies.py` | `Policy`, `PolicyStore`: propose → adopt-with-a-measurement → retire, over `growth:policies` |

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
