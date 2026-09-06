# Simorgh Architecture

> **Cutover complete (2026-09-06, Phase 5 Stage B,
> `docs/blueprint/06-migration-from-v1.md` section 6).** `sim.sh` now
> runs v2 by default. The single-process v1 implementation this document
> used to describe is archived at
> [`archive/architecture-v1.md`](archive/architecture-v1.md); its code
> (`src/`) is retired but not yet deleted -- that's the plan's Stage C,
> gated on living with v2 as the real daily driver first.

Simorgh v2 is sixteen small, message-driven subsystems -- one package
each under `simorgh/` -- composed by a Kernel and talking only through
typed, traceable messages on an async Bus, with all state kept as an
append-only Ledger of events. The full design is in
[`docs/blueprint/`](blueprint/00-README.md); this page is a map into it,
not a restatement.

See `docs/SOUL.md` for identity/values, `docs/EVOLUTION.md` for the
running history of what's been built and every live-caught lesson along
the way, and `docs/BIOMIMICRY.md` for the biological grounding behind
several design choices.

## Where things live

| Want to know... | Read |
|---|---|
| The sixteen subsystems, layering, safety topology, package rules, deployment modes, worked message flows | [`blueprint/02-system-architecture.md`](blueprint/02-system-architecture.md) |
| The message envelope, topic taxonomy, full message catalog, Bus/Ledger/Subsystem contracts | [`blueprint/03-contracts-and-messaging.md`](blueprint/03-contracts-and-messaging.md) |
| Build phases, what's done vs. planned, acceptance criteria | [`blueprint/04-build-plan-and-roadmap.md`](blueprint/04-build-plan-and-roadmap.md) |
| One detailed spec per subsystem | [`blueprint/subsystems/`](blueprint/subsystems/) |
| What changed from v1, why, and the cutover plan itself | [`blueprint/06-migration-from-v1.md`](blueprint/06-migration-from-v1.md) |
| Every milestone, bug, and design decision as it actually happened | [`EVOLUTION.md`](EVOLUTION.md) |

## The sixteen subsystems

| Layer | Subsystems |
|---|---|
| 0 Substrate | Bus, Ledger, Kernel |
| 1 Cognitive core | Cognition, Memory, World Model (+ Self Model) |
| 2 Agency | Planning, Execution, Guardian, Verification |
| 3 Growth | Learning, Reflection, Curiosity |
| 4 Self & surfaces | Persona, Interface |
| X Cross-cutting | Orchestration |

Full package paths and specs: [`blueprint/00-README.md`](blueprint/00-README.md#the-subsystems).

## The design in short

1. Sixteen small subsystems, one package each, share exactly one
   dependency (`simorgh/contracts`) and communicate only through typed,
   traceable messages on an async Bus (in-memory, SQLite, or AWS SNS/SQS).
2. All state is an append-only Ledger of events; every status, rollup,
   competence estimate, and the Self Model itself are projections that
   can be rebuilt from the log.
3. Safety is structural, not a checklist: every action is *proposed*,
   and only the Guardian can turn a proposal into an effect. Nothing
   else in the system holds that authority.
4. Continuity survives a crash: real work is resumable from the Ledger,
   not held only in a process's memory (proven live -- `EVOLUTION.md`
   milestone 119, a SIGKILLed worker resumed by another without redoing
   the step).
5. Guaranteed floors under any richer/networked layer -- a real LLM
   provider being unreachable degrades to a deterministic fallback, never
   a hang or a crash.

## Running it

```
./sim.sh                      # boots the v2 Kernel, interactive REPL
./dash.sh                     # opens the admin dashboard in Chrome
python -m simorgh run         # equivalent to sim.sh
python -m simorgh status      # one-shot system.status snapshot
python -m simorgh --self-check
```

`python -m src.main` (v1's own entry point) still runs, but now prints a
retirement notice and hands off into v2 -- see `src/main.py`'s
`__main__` guard.
