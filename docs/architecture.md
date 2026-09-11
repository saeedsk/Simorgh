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
| The seventeen subsystems, layering, safety topology, package rules, deployment modes, worked message flows | [`blueprint/02-system-architecture.md`](blueprint/02-system-architecture.md) |
| The message envelope, topic taxonomy, full message catalog, Bus/Ledger/Subsystem contracts | [`blueprint/03-contracts-and-messaging.md`](blueprint/03-contracts-and-messaging.md) |
| Build phases, what's done vs. planned, acceptance criteria | [`blueprint/04-build-plan-and-roadmap.md`](blueprint/04-build-plan-and-roadmap.md) |
| One detailed spec per subsystem | [`blueprint/subsystems/`](blueprint/subsystems/) |
| What changed from v1, why, and the cutover plan itself | [`blueprint/06-migration-from-v1.md`](blueprint/06-migration-from-v1.md) |
| Every milestone, bug, and design decision as it actually happened | [`EVOLUTION.md`](EVOLUTION.md) |

## The seventeen subsystems

| Layer | Subsystems |
|---|---|
| 0 Substrate | Bus, Ledger, Kernel |
| 1 Cognitive core | Cognition, Memory, World Model (+ Self Model) |
| 2 Agency | Planning, Execution, Guardian, Verification |
| 3 Growth | Learning, Reflection, Curiosity |
| 4 Self & surfaces | Persona, Benchmark, Voice, Interface |
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
6. Sim changes its own code the way its maintainer does (since
   2026-09-11): a patch or skill task works in its own git worktree,
   commits there, and lands on main only after a rebase and a
   whole-suite gate. The live checkout is never edited by a task.
   `docs/plans/worktree-landing-design.md`.

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

## Guardian's approval gate

Every rule in Guardian's pipeline (`guardian/rules.py::DEFAULT_PIPELINE`)
still runs regardless of the setting below and can still deny outright:
paused state, mode, protected subjects (`docs/SOUL.md`, `simorgh/guardian/`,
`simorgh/execution/`, `simorgh/contracts/`, `simorgh/kernel/`,
`simorgh.toml`, ...), the code denylist, adaptive immunity (rejects
proposals too similar to a previously-rejected one), and budget
exhaustion. Only once every one of those abstains does the last rule,
`ReversibilityRule`, decide what happens to an *irreversible* action
(`apply_source_patch`, `git_commit`, `git_revert`, `propose_mcp_server`)
that nothing else objected to: escalate to a human, or auto-approve.

`sim.sh`'s own default is auto-approve (`irreversible_requires_human =
false`) -- looser than `guardian.config.Config`'s own dataclass default
(`true`, kept safe for direct/library use and unit tests). Toggle it from
a shell without touching `simorgh.toml`:

```
SIMORGH_GUARDIAN_AUTO_APPROVE=0 ./sim.sh   # require human approval again
SIMORGH_GUARDIAN_AUTO_APPROVE=1 ./sim.sh   # explicit auto-approve (already the default)
```

or set `irreversible_requires_human = true` under `[guardian]` in
`simorgh.toml` -- either one wins over the `sim.sh` baseline. With
auto-approve on, `~/.simorgh/ledger/streams/guardian:rejected.jsonl` is
the only after-the-fact signal that a proposal got that far and was
still denied by an earlier rule.

### Autonomy loosenings (2026-09-07)

The creator asked for "more freedom in autonomously working and evolving
without too much gate". Three changes, all in `guardian/config.py`:

- A critical Reflection health finding tightens posture to `guarded`
  (still working, still gated), not `locked` -- `health_critical_tightens_to`.
- A lock is a circuit breaker, not a verdict: it expires back to the
  baseline posture after `lock_ttl_s` (default 10 min; `0` restores
  wait-for-`resume`). The consecutive-failure streak that locks is 15,
  not 5.
- The patch/skill task profiles (`orchestration/profiles.py`) can call
  `apply_source_patch` / `apply_skill`, `git_commit`, `git_revert`, and
  `run_tests` directly. Previously the model could only `draft_candidate`,
  and the draft->verify->apply loop that was meant to land a draft was
  never built -- so Sim could not actually change its own code.

What did not loosen: `ProtectedRule` (Sim cannot edit `simorgh/guardian/`,
`simorgh/kernel/`, `simorgh/contracts/`, `simorgh/execution/`,
`docs/SOUL.md`, `simorgh.toml`) and `DenylistRule` (no raw sockets,
subprocesses, `eval`, `ctypes` in drafted code). Those are the two
guardrails that protect the creator rather than slow Sim down.

## External toolsets (open-source tools)

`execution/external.py` wraps tools from LangChain (`BaseTool`s such as
`DuckDuckGoSearchRun`, `WikipediaQueryRun`), pydantic_ai
`FunctionToolset`s, Composio toolsets (hosted; needs `COMPOSIO_API_KEY`),
or any plain Python callable behind Sim's own `Tool` protocol. They are
listed under `[[execution.external_tools]]` in `simorgh.toml`, imported
lazily by string, and skipped with a warning if the package is missing --
the stdlib-only floor still boots with nothing installed. The frameworks'
own agent loops are deliberately not used: only their tool
implementations, so every call still goes through Guardian like
`read_file` does. Execution announces each one on `tool.registered`
(`provider="external"`) and Orchestration's router learns its policy from
that announcement -- no per-tool edit in `orchestration/tools.py`.
