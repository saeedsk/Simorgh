# simorgh/orchestration

The harness loop (16 section 5): `Worker` claims one `task.available`
command at a time (consumer group `workers`), runs a `SessionRunner`
through CLAIMED → GATHER → THINK → (tool_calls → PROPOSE → await result
→ GATHER | final text → VERIFY → COMPLETED), and reports the terminal
`Outcome` back onto the bus and ledger. Every subsystem call (Cognition,
Guardian/Execution, Verification, Memory, Self, Persona, World) goes
through `bus.request_or_error()` or an explicit `_EventWaiter`, and
degrades honestly (empty context block, floor outcome, or `blocked`) on
any timeout — no sibling subsystem is required to exist for this package
to run and be tested.

## What this build implements

- `Session`/`Step`/`Budget`/`Outcome`/`Profile` (`api.py`), `Profile`
  instances for chat/patch/research/plan/skill (`profiles.py`).
- `ContextAssembler` (`context.py`): self-summary + persona voice +
  memory retrieval, each independently degrading on timeout.
- The tool-call → `action.proposed` payload builder (`tools.py`) with a
  small reversibility/network policy table.
- `SessionRunner` (`session.py`): the full state machine including the
  bounded evaluator-optimizer revision loop for `patch`-kind sessions,
  and a `paused` check between steps.
- `restore_step_count` (`resume.py`): rebuilds `session.steps` and
  `budget.steps_used` from the Ledger's `task:<id>` stream so a second
  Worker resuming the same task doesn't redo completed steps.
- `Worker` (`worker.py`): the claim loop, `system.state.changed`
  tracking, and terminal reporting (`task.completed`/`.failed`/
  `.blocked` plus `turn.completed` for chat sessions).
- `Service` (`service.py`) implementing the `Subsystem` protocol so the
  Kernel can start N workers from config.

## What this build deliberately does NOT implement

Scoped down to keep this session's slice honest and testable against
fakes; each is a real gap against `16-orchestration.md`'s full spec:

- **Plan Mode artifact assembly** — Plan-mode sessions run through the
  same loop as execute-mode; they don't yet produce/store the plan
  artifact the profile implies.
- **Delegation** (fresh/fork sub-sessions, `depth`/`parent_id` beyond
  the field existing on `Session`) — not wired up.
- **Steer injection** — no mechanism yet for a running session to accept
  a mid-flight user message.
- **Reground-every-N-steps** — no periodic context restatement; context
  is assembled fresh each THINK call, but nothing re-summarizes a long
  `session.messages` list.
- **Full 14-marker conversational routing** (v1's `LogicAgent` marker
  vocabulary) — `tools.py` builds one `action.proposed` payload per tool
  call; it does not reproduce v1's full marker-based conversational
  control surface.
- **Lease heartbeat renewal / wall-clock budgets** — a Worker's claim
  does not renew its lease, and there's no wall-clock budget alongside
  the step-count budget.

## A timing note for anyone testing against the bus's `memory` backend

`Worker._on_available` runs as a *detached* task — spawned by the bus's
own dispatch loop for the `workers` consumer group, not awaited by
whatever published `task.available`. If nothing answers `self.summary`/
`persona.voice`/`memory.retrieve` in a test, `ContextAssembler` degrades
via a **real** `asyncio.wait_for` timeout (default 0.25s, `Config`urable
via `assemble_timeout_s` on `Worker`/`SessionRunner`). A test that only
yields the loop (`asyncio.sleep(0)` in a pump loop) never lets that real
timer fire and the detached task is silently cancelled when the test
coroutine returns — it looks like the handler never ran. Either give the
Worker a short `assemble_timeout_s` and let real wall-clock time pass
(`tests/simorgh/orchestration/harness.py`'s `pump(n, real_delay=...)`),
or start fakes for every subsystem the assembler queries.
