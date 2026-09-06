# 05 — Build Instructions for AI Agents (and humans)

> Part of the Simorgh v2 blueprint. You are (probably) a Claude Code
> agent or another AI coding agent that has been asked to build one
> subsystem of Simorgh v2. This file tells you exactly how to work so
> that your subsystem fits with fifteen others being built in parallel.
> Read it fully before touching code.

## 0. Your one-paragraph orientation

Simorgh v2 is a modular, message-driven agent. Sixteen subsystems live
in `simorgh/<name>/`, talk only through typed messages on a Bus
(`simorgh/bus`), persist only through an append-only Ledger
(`simorgh/ledger`), and share exactly one dependency: `simorgh/contracts`.
The Guardian sits structurally on the action path; nothing executes
without its cryptographic approval. Your job is one package. Its spec is
`docs/blueprint/subsystems/NN-<name>.md`. The system map is
`docs/blueprint/02-system-architecture.md`; the interface definition is
`docs/blueprint/03-contracts-and-messaging.md`; the principles are
`docs/blueprint/01-vision-and-principles.md`. The knowledge base that
grounds the design is `docs/KnowledgeBase/` — read `harness-01`,
`harness-05`, and `AGI-04` at minimum.

## 1. Before you write code

1. Read your subsystem spec end to end. Then read §3 (Interfaces) again.
2. Read `contracts/topics.py` and the `contracts/messages/<domain>.py`
   modules for every type you consume or produce. Do not invent message
   types. If you need one that doesn't exist, stop and file a contracts
   change (see §6).
3. Read the v1 code your spec's "migrates here" line points at. You are
   porting working, tested behavior with live-caught lessons in
   `docs/EVOLUTION.md`; keep the lessons.
4. Run the whole test suite once so you know the baseline is green:
   `python3 -m unittest discover -s tests -t .`
5. State your plan in your package README under "Build log" (a dated
   bullet per session) before starting. This is how the next agent — or
   you after a context reset — knows what happened.

## 2. Package conventions

```
simorgh/<name>/
  README.md      purpose · link to spec · how to run tests · build log · open questions
  __init__.py    from .service import Service
  service.py     class Service(Subsystem): name, version, consumes, produces, start/stop/health
  api.py         Protocols/ABCs used inside this package (and any the contracts declare for you)
  config.py      @dataclass(frozen=True) Config with defaults + from_mapping()
  ...            internals, one responsibility per module, no module over ~500 lines
tests/simorgh/<name>/
  test_contracts.py   every produced type validates; every consumed type has a handler test
  test_<component>.py unit tests
tests/simorgh/integration/test_flow_<n>_<name>.py   the scenario(s) your spec names
```

- Python ≥ 3.12, standard library only in the core. Optional adapters
  guard imports (`try: import boto3 except ImportError: boto3 = None`)
  and register themselves only when available.
- `from __future__ import annotations`; dataclasses for data; `Protocol`
  for interfaces; type hints everywhere; no global mutable state.
- Async: handlers are `async def`; never block the event loop (use
  `asyncio.to_thread` for subprocesses/IO-heavy work); every background
  loop is a task the `Service` cancels in `stop()`.
- Time comes from `ctx.clock`, never `time.time()` directly, so tests
  can control it.
- Logging is `ctx.logger` (structured; the Kernel routes it to the
  Ledger). No `print` in subsystems (Interface owns the terminal).
- Docstrings explain *why* (the design decision and the lesson behind
  it), matching the existing codebase's voice. A future agent should be
  able to reconstruct the reasoning from the docstring alone.

## 3. The rules you must not break

1. **Import boundary.** Your package imports `simorgh.contracts`,
   `simorgh.bus.client`, `simorgh.ledger.client`, stdlib, and itself.
   Never another subsystem. `tests/simorgh/test_module_boundaries.py`
   will fail your build otherwise. If you think you need another
   subsystem's code, you need a message instead.
2. **No side effects outside the action path.** If your subsystem wants
   to write a file, run a command, touch the network, or change code, it
   publishes `action.proposed` and waits for `action.result`. Only
   Execution performs actions; only Guardian approves them. (Ledger
   appends and your own data-dir caches are not "actions.")
3. **Idempotent handlers.** Assume every message may arrive twice. Use
   `idempotency_key`/`id` against your Ledger stream before side effects.
4. **Never raise across the bus.** Catch, log via `ctx.logger`, reply with
   an error payload or nack. A crash in your handler must not take the
   Kernel down (it won't — but it will mark you `degraded`).
5. **Honest floors.** When a provider is unavailable or budget is
   exhausted, return the deterministic floor and say so (`floor: true`,
   `insufficient_evidence`, `verdict: unknown`). Never fabricate success.
   Never treat a non-answer as a failure.
6. **State lives in the Ledger.** Anything you would lose on restart
   that matters must be an appended event with a projection that can
   rebuild from the log. Caches are fine; truth is not.
7. **Don't edit `simorgh/contracts/` casually.** See §6.
8. **Don't edit another agent's package.** If their behavior blocks you,
   write a fake in your tests that speaks the contract, note it in your
   README's open questions, and move on.
9. **Keep v1 green.** Until cutover, `src/` tests must still pass. Where
   you port a v1 module, leave a thin adapter in `src/` that delegates to
   your package (see `06-migration-from-v1.md`) rather than deleting.
10. **Commit small, commit often, never push force, never push
    automatically from Sim's own runtime.** Human/agent pushes are fine;
    the system pushing itself is not (Guardian policy, SOUL).

## 4. How to build a subsystem, step by step

Follow your spec's §10, which will look like this:

1. **Skeleton.** Package layout above; `Service` with `consumes`/`produces`
   copied from spec §3; `start()` subscribes to each consumed pattern
   with a handler stub that logs and acks; `health()` returns `ok`.
   Register the package in `kernel/registry.py`. Run the boundary test
   and the contracts test. Commit: `"<name>: skeleton"`.
2. **Streams and projections.** Implement spec §4: append helpers,
   projection classes with `apply(event)` and `rebuild(ledger)`. Unit
   tests: rebuild from an empty log, from a log with duplicates, from a
   snapshot + tail. Commit.
3. **One flow at a time.** Take the first scenario in spec §6. Implement
   the handlers it needs. Write the contract test for each produced
   message (valid payload) and the handler test for each consumed one
   (valid + invalid). Write the integration scenario with fakes for
   other subsystems. Commit per flow.
4. **Port v1.** Move the functions your spec names into your package,
   adapting signatures to messages; keep their tests (moved under
   `tests/simorgh/<name>/`) and leave a delegating adapter in `src/`.
   Commit.
5. **Failure modes.** Implement spec §8: pause/stop behavior, duplicate
   messages, provider down, ledger unavailable, malformed payloads. Tests
   for each. Commit.
6. **Docs.** README build log, config table, spec status → `building` →
   `done`, `EVOLUTION.md` milestone (one entry per subsystem, in the
   repository's established voice: what, why, what was live-caught).
7. **Self-check.** `python -m simorgh --self-check` exits 0 with your
   subsystem loaded. Full suite green. Push.

## 5. Testing standards

- Every produced message: a test that builds it through the dataclass,
  validates against the JSON Schema, round-trips through canonical JSON.
- Every consumed message: a handler test with a valid payload asserting
  the exact messages/ledger events produced, and an invalid payload
  asserting a nack/error reply and no side effects.
- Integration scenarios use `simorgh.bus.memory` and `simorgh.ledger.memory`,
  a `FakeClock`, and `FakeProvider`/`FakeTool` helpers from
  `tests/simorgh/helpers.py`. They assert on the *sequence of messages*
  (types and key payload fields), not on internals.
- Property/invariant tests where the spec states an invariant
  (e.g. "rollup is a pure function of children", "no two candidates in
  one tick exceed the similarity threshold", "an unapproved action never
  reaches a tool").
- Tests never call a real LLM or the network. `tests/simorgh/helpers.py`
  provides fakes; the suite must pass offline.
- Name tests after the behavior and the lesson: `test_non_answer_defers_to_mechanical_gates`.

## 6. Changing the contracts

The catalog in `simorgh/contracts/` is the API everyone is building
against. To change it:

1. Open a proposal in `docs/blueprint/contracts-changes/<date>-<slug>.md`:
   what type, why, who consumes/produces it, backward compatibility.
2. Add the message dataclass + schema **with a new `schema_version`** if
   the change is breaking; add a translator in `contracts/compat.py`.
3. Update `03-contracts-and-messaging.md` §4 and the affected subsystem
   specs' §3.
4. Get it reviewed by the Phase 0 owner (or, if you are alone, re-read
   §8 of `03` and make sure the compat tests pass).
5. Only then use it.

Adding an *optional* payload field is non-breaking and needs only steps
2–3.

## 7. Working alongside other agents

- Claim your package by setting `Owner (build)` in the spec header and
  adding yourself to `00-README.md`'s ownership table. One owner per
  package at a time.
- Coordinate through files, not chat: README build logs, spec open
  questions, contracts proposals. Assume the other agents can only see
  the repository.
- If you need a message another subsystem doesn't emit yet, build
  against a fake and record the dependency in your README under
  "Waiting on."
- Rebase often; conflicts are almost always in `contracts/` or shared
  test helpers — which is why those are single-owner.

## 8. When you are stuck

- A design question the spec doesn't answer: check `01` principles,
  then the KB file the spec cites, then choose the option that keeps the
  floor honest and the Guardian in the path, write it down in the spec's
  §12 with your reasoning, and continue. Do not stop to ask if a
  reasonable default exists.
- A contradiction between documents: `01` > `02`/`03` > subsystem spec >
  code comments. Fix downward, note it in `00-README.md`'s changelog.
- Something in v1 seems wrong: it may be a live-caught fix — search
  `docs/EVOLUTION.md` for the function name before "simplifying" it.

## 9. Definition of done (copy into your README and tick it)

- [ ] Spec status `done`; README links spec; build log complete
- [ ] `consumes`/`produces` declared and verified by contracts test
- [ ] Boundary test passes
- [ ] Contract tests for every produced/consumed type
- [ ] Unit tests for every §5 component and every §8 failure mode
- [ ] Integration scenario(s) named in spec §9 pass on `memory` (and `sqlite` if durable)
- [ ] v1 tests still green; adapters in place
- [ ] `python -m simorgh --self-check` exits 0
- [ ] No new third-party dependency in the core
- [ ] `EVOLUTION.md` milestone written
