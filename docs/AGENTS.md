# Working on Simorgh with many agents at once

This is the protocol that lets several coding agents (or people) change Simorgh in parallel without stepping on each other. It rests on three things the repository already has: **one package per module** with an enforced import rule, **typed message contracts** in `simorgh/contracts`, and a **per-module contract document** (`simorgh/<module>/CONTRACT.md`) that names the tests pinning that module's interface.

The unit of ownership is the module. An agent locks a module, changes only what is inside it, proves the module's contract tests and its own tests still pass, commits with the module's name, and releases the lock. Anything that crosses a module boundary goes through `simorgh/contracts` and is announced in every consumer's contract document.

## 1. The modules

| Module | Layer | Package | Tests | Lock name |
|---|---|---|---|---|
| bus | 0 | `simorgh/bus/` | `tests/simorgh/bus/` | `bus` |
| ledger | 0 | `simorgh/ledger/` | `tests/simorgh/ledger/` | `ledger` |
| kernel | 0 | `simorgh/kernel/` | `tests/simorgh/kernel/` | `kernel` |
| telemetry | 0 | `simorgh/telemetry/` | `tests/simorgh/telemetry/` | `telemetry` |
| contracts | shared | `simorgh/contracts/` | `tests/simorgh/contracts/` | `contracts` |
| cognition | 2 | `simorgh/cognition/` | `tests/simorgh/cognition/` | `cognition` |
| memory | 2 | `simorgh/memory/` | `tests/simorgh/memory/` | `memory` |
| worldmodel | 2 | `simorgh/worldmodel/` | `tests/simorgh/worldmodel/` | `worldmodel` |
| planning | 3 | `simorgh/planning/` | `tests/simorgh/planning/` | `planning` |
| guardian | 3 | `simorgh/guardian/` | `tests/simorgh/guardian/` | `guardian` |
| execution | 3 | `simorgh/execution/` | `tests/simorgh/execution/` | `execution` |
| verification | 3 | `simorgh/verification/` | `tests/simorgh/verification/` | `verification` |
| learning | 4 | `simorgh/learning/` | `tests/simorgh/learning/` | `learning` |
| reflection | 4 | `simorgh/reflection/` | `tests/simorgh/reflection/` | `reflection` |
| curiosity | 4 | `simorgh/curiosity/` | `tests/simorgh/curiosity/` | `curiosity` |
| persona | 5 | `simorgh/persona/` | `tests/simorgh/persona/` | `persona` |
| benchmark | 5 | `simorgh/benchmark/` | `tests/simorgh/benchmark/` | `benchmark` |
| voice | 5 | `simorgh/voice/` | `tests/simorgh/voice/` | `voice` |
| interface | 5 | `simorgh/interface/` | `tests/simorgh/interface/` | `interface` |
| orchestration | X | `simorgh/orchestration/` | `tests/simorgh/orchestration/` | `orchestration` |
| simloader | boot | `simloader.py`, `sim.sh` | `tests/simorgh/test_simloader.py` | `simloader` |
| tools | dev | `tools/` | `tests/tools/` | `tools` |
| shared | tests | `tests/simorgh/test_*.py`, `tests/simorgh/integration/` | themselves | `shared` |
| docs | docs | `docs/` (except `docs/SOUL.md`) | — | `docs` |

Each module's `CONTRACT.md` says what it consumes, produces, owns and promises, which tests pin that, and what the roadmap will change in it. Read it before the code.

## 2. The loop, every time

```
python tools/modlock.py status                                  # who holds what
python tools/modlock.py claim memory --by <you> --task "stage 5 item 3: persist vectors"
git add docs/modules/locks.toml && git commit -m "locks: memory -> <you>" && git push
# ... work inside simorgh/memory, tests/simorgh/memory, simorgh/memory/CONTRACT.md ...
python tools/modtest.py memory                                  # module tier, tens of seconds
python tools/modlock.py check --by <you>                        # nothing outside my locks changed
git add <explicit paths> && git commit -F msg && git push
python tools/modlock.py release memory --by <you>
git add docs/modules/locks.toml && git commit -m "locks: release memory" && git push
```

- **The lock is the commit.** Two agents claiming the same module collide on the push; the second one rebases, sees the lock, and picks another item. Locks expire (default 8 h) so an abandoned claim does not block anyone; a stale lock may be taken over with `release --force`.
- **Scope is the lock.** `modlock check` maps every changed path to a module and refuses if any is locked by someone else. Use `--strict` to also refuse paths you did not lock at all.
- **Proof is the tier.** `modtest <module>` is the minimum before any commit. `--tier core` (the boot gate, ~45 s) is required when the change touched `bus`, `ledger`, `kernel` or `contracts`. `--tier full` is required before a bless (`python simloader.py bless`) and runs nightly; it is not a per-commit cost. See `docs/testing.md`.
- **Naming.** Commit subject: `<module>: <what changed>`; body: why, and which catalogue id or plan item it closes. The plan files in `docs/plan/` are numbered so that "stage 0 item 4" is unambiguous.

## 3. Changing a contract

A contract is anything another module depends on: a topic and its schema (`simorgh/contracts/topics.py`, `simorgh/contracts/messages/`), a ledger stream name (`simorgh/contracts/streamnames.py`), a config key another module reads, a protocol in `simorgh/contracts/protocols.py`, or a Guardian rule's expectation of a proposal's shape.

1. Lock `contracts` in addition to your module.
2. Prefer **additive** changes: a new optional field, a new topic, a new stream. A breaking change (renaming, removing, changing a field's meaning) needs the creator's yes and a plan item.
3. Update `simorgh/contracts/` and the JSON schema, then every consumer's `CONTRACT.md` table that mentions the thing, in the same commit.
4. Add or extend a contract test (`tests/simorgh/contracts/`) and run `python tools/modtest.py contracts --tier core`.
5. The "unconnected wire" is this project's dominant bug: a topic declared and published that nobody subscribes to, or subscribed and never published. `tests/simorgh/contracts/test_topics_have_both_sides.py` (stage 0 adds it) fails the build on a one-sided topic; if you add a topic, add both sides or add it to the allow-list with a reason.

## 4. What an agent must not do

- Edit `docs/SOUL.md`. The creator amends it by hand.
- Let Sim's own tasks edit Guardian-protected paths (`simorgh/guardian/`, `simorgh/execution/`, `simorgh/contracts/`, `simorgh/kernel/`, `simloader.py`, `sim.sh`, `docs/SOUL.md`). A human-run agent may, with a lock, because a person is accountable for the commit.
- Boot Sim from this checkout while others hold locks. `sim.sh` boots from the working tree; a half-done edit gets gated and blocks rollback. Test behaviour with `python tools/trial.py` in a repository copy.
- Run the full suite as a habit. It is the bless gate. If the module tier is not enough to prove your change, the contract tests for that module are incomplete: fix that first.
- Write to `~/.simorgh` from a test. `conftest.py` strips `SIMORGH_*` from the environment for this reason; keep it that way.
- Leave a dated incident comment where a test belongs. If you learnt something from a live failure, write the test that would have caught it, and a line in `docs/findings/`.

## 5. Splitting work across agents

A stage in `docs/plan/` lists its action items with the lock each needs. Items on different modules run in parallel; items on the same module run in sequence under one lock. A coordinator (a person, or an orchestrating agent) hands out items, and each worker follows section 2. When a worker finishes an item it updates the stage file's status line for that item (`docs` lock is shared and cheap: keep those commits tiny).

Two items that both need `contracts` serialise on that lock. That is deliberate: the contracts package is where parallel work turns into conflict, so it should be the bottleneck, not a free-for-all.

## 6. Where things are

| Need | Look at |
|---|---|
| What the system is and how it runs today | `docs/ARCHITECTURE.md` |
| What is wrong with it, with evidence | `docs/reviews/2026-09-18/architecture-evaluation.md` (section 13 is the catalogue) |
| What changes next, in order, with action items | `docs/plan/README.md` and `docs/plan/stage-N-*.md` |
| One module's interface, promises, tests and planned changes | `simorgh/<module>/CONTRACT.md` |
| Tests: tiers, markers, how to run | `docs/testing.md` |
| Measured results, dated | `docs/findings/` |
| Sim's constitution | `docs/SOUL.md` (read-only for agents) |
| How to run Sim, voice setup | `README.md` |
