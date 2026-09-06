# <NN> — <Subsystem Name> (`simorgh/<package>/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** <0 Substrate | 1 Cognitive core | 2 Agency | 3 Growth | 4 Self & surfaces | X Cross-cutting>
**Owner (build):** <unassigned | agent/team name>
**Status:** <draft | reviewed | building | done>
**Depends on (contracts only):** <list of message types consumed>
**v1 code that migrates here:** <paths under `src/`>

## 1. Purpose and responsibilities

One paragraph: what this subsystem is *for*, in the system's own terms.

**Responsibilities (owns):**
- …

**Explicit non-responsibilities (belongs elsewhere):**
- … (name the subsystem that owns it)

**Principles this subsystem is the primary enforcer of** (from `01` §4): …

## 2. Position in the architecture

Where it sits (layer), which flows from `02-system-architecture.md` §5
it participates in, and what it must never import (everything except
`simorgh.contracts`, `simorgh.bus` types, `simorgh.ledger` types, stdlib).

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics (event/command/request) | What this subsystem does with it |
|---|---|---|---|

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers (informational) |
|---|---|---|---|

### 3.3 Request/reply APIs served
For each: request type, reply type, timeout expectations, failure replies.

### 3.4 Python protocol (`api.py`)
The in-process interface other code in *this* package uses, plus any
`Protocol` classes the contracts package declares for this subsystem
(e.g. a provider adapter interface). Code, not prose.

### 3.5 Configuration
Table of config keys (`simorgh.toml` section), types, defaults, and what
each controls. Include environment-variable overrides if any.

## 4. Data model and Ledger streams

Streams this subsystem appends to (names, event types, payload schemas),
projections it maintains (and how they are rebuilt from the log), and any
files it owns in the data directory. State that is *not* in the Ledger
must be justified (caches only).

## 5. Internal design

Components/modules inside the package, their responsibilities, key
algorithms and state machines (draw them as text diagrams), concurrency
model (asyncio tasks, background loops, locks), and how the subsystem
starts, stops, and reports health.

## 6. Key behaviors — worked scenarios

At least three concrete, end-to-end scenarios written as message
sequences ("receives X → does Y → emits Z"), including at least one
failure/degradation scenario. Reference the flow numbers in
`02-system-architecture.md` §5 where applicable.

## 7. Design considerations and tradeoffs

Grounded in the knowledge base (`docs/KnowledgeBase/`): cite the specific
file/section for each tradeoff. Cost, latency, safety, complexity.
Alternatives considered and why rejected.

## 8. Safety, degradation, and failure modes

What happens when: a provider is down, budget is exhausted, a message is
malformed, a handler crashes, the process restarts mid-operation, a
duplicate message arrives, the Ledger is unavailable. The guaranteed
floor for this subsystem. Corrigibility: how `system.pause`/`system.stop`
affect it.

## 9. Testing strategy

- Contract tests (message schema conformance, both directions).
- Unit tests (list the classes/behaviors and the tricky cases).
- Integration scenario(s) this subsystem must pass in
  `tests/simorgh/integration/` (name them).
- Property/invariant tests where relevant (e.g. "rollup is a pure function
  of children").
- What must be mocked (providers, clock) and how.

## 10. Build steps (an agent picks this up here)

Ordered, each with an acceptance check. Typical shape:
1. Create package skeleton, `README.md`, `config.py`, `service.py` stub registering consumed/produced topics; boundary test passes.
2. Implement Ledger streams + projections; unit tests.
3. Implement message handlers one flow at a time; contract tests.
4. Port v1 code listed above; keep v1 tests green via adapter.
5. Integration scenario passes.
6. Docs: README, config table, update `02` §5 flow if changed.

State the estimated size (S/M/L) and what can be parallelized within the
subsystem.

## 11. Migration notes

Exactly which v1 modules/functions map to which components here, what
changes in behavior (if any), and how v1's tests are preserved or
replaced.

## 12. Open questions

Numbered. Each with a recommended default so a builder is never blocked.
