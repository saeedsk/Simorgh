# Post-cutover architecture review (2026-09-06)

**Who this is for:** the creator, and whoever plans the next build wave.
**What it reviews:** the v2 blueprint (`00`–`06`, `subsystems/`), the
code built against it (`simorgh/`), the live trial of the real, cutover-
live system (`docs/v2-live-trial/`), and the creator's own first hours
of hands-on CLI use (`EVOLUTION.md` milestones 116–128).
**How it was done:** four parallel read-only review passes, one per
layer (substrate; cognitive core; agency; growth + surfaces), each
checking spec against code line by line, plus the direct evidence from
the trial and the CLI sessions. Reports are merged here; the file
citations below come from those passes and were spot-checked.

The one-paragraph verdict: **the architecture is sound and does not
need to change. The blueprint was largely right; where the system
misbehaved, it was almost always because a spec'd piece was built but
never wired to its consumer, not because the design was wrong.** The
guardrails (Guardian, the action-proposal path) are the most
trustworthy part of the system — verified in code, not just prose. The
self-improvement loop, which is the *point* of the project, is the least
trustworthy part — not because it's unsafe, but because from the chat
surface it convincingly looks wired while being disconnected from every
real gate underneath. That gap, plus a handful of "built but not
connected" seams in memory and self-knowledge, is the next wave.

---

## 1. What the live evidence actually showed

Seven findings from the trial and the creator's own use, each now
root-caused to a specific seam (details in `docs/v2-live-trial/
observations.md` and the milestones cited):

| # | Symptom the creator or trial saw | Root cause (code) | Status |
|---|---|---|---|
| 1 | Sim said it was Claude Code | System-role content flattened into `-p`; identity text descriptive not directive | Fixed (m120) |
| 2 | "What did I just ask?" answered with an unrelated old memory | Working memory exists but is never fed (`memory/service.py::_on_turn_completed` writes only episodic) and never requested (`orchestration/context.py::_memory_retrieve` asks only episodic/semantic, no `session_id` filter). Spec'd correctly in `05-memory.md` §3.1 and `02` Flow 1; wired on neither side | **Open — S** |
| 3 | Intermittent instant empty reply | `_think()` swallowed Cognition's error code; real cause `context_too_large` because `allow_summarize` was never set for chat | Fixed (m122–123); residual edge case open (§3.4) |
| 4 | "What tools do you have?" answered with v1's CLI vocabulary; "propose X" in chat produced a convincing draft and did nothing | (a) `capabilities.tools/providers` in the Self Model are never populated — `tool.registered` feeds a live facet, not the persisted model the LLM reads; render shows only `areas` (`selfmodel.py:267-271`). (b) `orchestration/tools.py` routes only `tool_calls → action.proposed`; no conversational intent path exists — only the *typed* `propose <topic>` command reaches `task.create` | **Open — S (a), M (b)** |
| 5 | "I only run when you message me… nothing happens for three hours" — while `curiosity:ticks` fired every 3s | The Self Model has no section describing how Sim runs (mode, autonomous loop, sessions); the LLM filled the gap with a generic chatbot prior | **Open — M** |
| 6 | CLI: "hello" then `^M^M^M`, no reply — three separate times | Three unrelated bugs with one symptom: unthreaded `think_timeout_s` (m104); fire-and-forget REPL loop (m124); subprocesses inheriting the real terminal's stdin (m126); then no `readline` (m127) | Fixed |
| 7 | `vitals`: raw dict dump, `posture: unknown`, banner glyphs unreadable | `budget` field held raw metrics; Guardian publishes `{"mode":…}` but vitals reads `"posture"`; no handler for `guardian.posture.request`; Persian script in a centered line | Dict + glyphs fixed (m128); **posture: Open — S** |

Two cross-cutting facts matter more than any single row:

- **Every bug in rows 2, 4a, 5 is "spec'd, built, not connected."**
  `WorkingMemory` is fully implemented and even wired into `retrieve()`'s
  `working` branch — nothing calls `add()`. The Self Model schema has
  `capabilities.tools`; nothing fills it. This is the signature of a
  system built in parallel by many hands against one contract: each
  side did its half correctly, and the seam between them had no owner
  and no test. **The remedy is a testing-strategy change, not a design
  change** (§4).
- **Rows 6 and 7 were found by a human at a real terminal, not by an
  hour of automated live testing through the HTTP API.** The primary
  interface was never exercised as a terminal until the creator did
  it. Same remedy: the test strategy must include the actual front
  door, driven as a real subprocess with a real (or pseudo) tty.

## 2. Architecture verdict, layer by layer

**Substrate (bus, ledger, kernel, contracts) — sound; the most mature
layer.** No correctness bugs in delivery or durability. Real gaps are
operational: `data_dir` defaults to `~/.simorgh` (spec-correct, but it
caused four accidental writes into the creator's real home directory
during testing this session — the spec needs a warning, tooling needs
to set `SIMORGH_RUNTIME_DATA_DIR` always); `DEFAULT_RETENTION` covers
only `trace:`/`dead:`/`activity`, so `metrics:history`, `curiosity:
ticks`, `memory:episodic` grow without bound and compaction only runs
on `system.tick.sleep`, never a timer; `01-bus.md` §9 names a property-
test suite that doesn't exist; `local-multi` identity tokens are self-
issued per process (authenticates format, not a shared secret).

**Cognitive core (cognition, memory, worldmodel) — sound design,
incomplete wiring.** Besides rows 2/4a/5: two independent assemblers
(`orchestration/context.py::Assembler` and `cognition/assembler.py::
PromptAssembler`) both fetch `self.summary` and `persona.voice` — the
text reaches the provider twice per turn, doubling that token cost and
directly feeding the `context_too_large` pressure. Layer-5 auto-compact
has no cap on its own summarization input (the "residual edge case").
`MemoryEngine.retrieve()` is a full linear scan of every stream on
every call, with lexical-overlap scoring and `recency_weight=0.1` — for
a short common-word query, which item "wins" is close to arbitrary.
`compaction.py` and `memory/store.py` are the strongest code here.

**Agency (planning, execution, guardian, verification, orchestration) —
guardrails verified; self-modification-from-chat not wired.**
Confirmed directly: `cognition.think` is never gated (by design), and
every effect-producing entry point — chat `tool_calls` *and* every typed
CLI command — publishes `action.proposed` first. No bypass found.
Scoped-down pieces (`delegate.py`, full `resume.py` snapshot restore,
lease heartbeats, steer, reground) are all honestly documented in
docstrings, not silent. Two real bugs: the posture request has no
handler and the posture event key mismatches (row 7); sandbox timeouts
kill only the direct child, not its process group — the exact v1 lesson
that never landed cleanly there either. Guardian's `_tasks` dict is
never evicted.

**Growth + surfaces (learning, reflection, curiosity, persona,
interface) — persona is a genuine non-finding; the rest needs
governance.** Persona's mood nudging is wired as spec'd. The idle loop
fires every 3s after 10s idle and each tick can be a real billed
`cognition.think` call — no hourly cost target, only the 500-calls/5h
safety net; "10s of silence mid-thought" already counts as idle.
Chat completions feed `learn.outcome.recorded{succeeded: True}`
unconditionally — a floor reply and a great reply score identically, so
the `chat` competence entry is noise dressed as learning. Reflection's
critique/drift verdicts reach the Self Model only via generic Memory
retrieval (the same unreliable channel as row 2). The REPL has needed
four fixes in one day; its shape (blocking `input()` on a thread,
bridged with `run_coroutine_threadsafe(...).result()`) should be
recorded as a decision with its known limitation: Ctrl-C during a
pending reply is only caught around `input()`, and reaches the main
thread's `asyncio.run` with no handler — likely an abrupt exit, not a
graceful `system.stop`.

## 3. Decisions (what changes in the blueprint)

None of these change the sixteen-subsystem shape, the Bus/Ledger
substrate, or the structural safety topology. They are all
clarifications, wiring completions, and governance additions.

### 3.1 Conversational intent must reach the real pipeline — through Guardian
`16-orchestration.md` §12, new decision. The chat profile's tool list
gains `propose{topic}` and `patch{path, description}` as ordinary tools
in `tools.py::_TOOL_POLICY`, routed through `to_action_payload` into
`action.proposed` (`reversibility="reversible"`), gated by Guardian
exactly like `read_file`, with Execution's handler doing what
`dispatch.py`'s typed commands already do (`task.create`). **Not** a
resurrection of v1's marker-parsing text protocol. This closes the
single worst finding: a system that role-plays a capability through its
most natural surface. Until it lands, any "Sim proposed X in chat"
narrative should be treated as unverified.

### 3.2 One owner for context assembly
`04-cognition.md` §5 and `16-orchestration.md` §7: Cognition's
`PromptAssembler` is the sole fetcher of `self.summary`/`persona.voice`
(protected blocks). Orchestration's `Assembler` contributes only memory
retrieval, `session.messages`, and `user_text`. Remove lines 28–34 of
`orchestration/context.py`. Smallest diff, matches "Cognition owns the
pipeline" literally, and halves the identity/voice token cost per turn.

### 3.3 Working memory: wire both ends, as already spec'd
`05-memory.md` is already correct. `_on_turn_completed` calls
`engine.working.add(session_id, user_text, reply_text, ts)`;
`Assembler._memory_retrieve` requests `kinds=["working","episodic",
"semantic"]` with `filters={"session_id": session.task_id}`. Then add a
retrieval-side bound (`05` §5/§8): a default recency window or a real
index — `05` §9 already names an `InvertedIndex` as if built; confirm
whether it exists.

### 3.4 Self Model: fill `capabilities`, add "How I run"
`06-worldmodel.md` §4/§5: (a) ingest `tool.registered`/`.unavailable`
and `cognition.provider.status` into `capabilities.tools/providers` via
the same mutator pattern `add_skill` uses; render a real tool list in
`_render_section("capabilities")`. (b) New section **`operating`**
("How I run"): `mode`, `autonomous_loop {enabled, idle_threshold_s,
tick_cooldown_s, last_tick_ts}`, `active_sessions`, `uptime` — populated
from `system.state.changed`, `system.metrics` (Orchestration's
`workers` gauge already exists; Curiosity needs one small gauge
publish), and Kernel config. Placed in `render_summary`'s order ahead
of `capabilities`, so a question about the system's own operating
characteristics has something authoritative to cite. (c) An ingestion
row for `reflect.drift.verdict{drifting}` → `open_questions`, and
repeated critiques → `limitations` (fuzzy-match, existing mechanism).
(d) Cap layer-5 summarization input in `cognition/compaction.py`
(`04-cognition.md` §5, layer 5).

### 3.5 Autonomous-loop cost governance
`13-curiosity.md` §4.2: an explicit hourly cap on real (non-floor)
exploration `cognition.think` calls, independent of any provider's
rolling window (default conservative, e.g. 20/h), and a longer effective
idle cooldown when there is no backlog to work. Ticks stay dumb
(`03-kernel.md` §5.5 is right); Curiosity's `_run_tick` gains one gate.
`11-learning.md` §3.1: chat completions count as competence samples
only with a real quality signal (`verify_chat=true` or explicit user
feedback) — the "outcome-feedback" mechanism Sim itself described in the
trial and never built.

### 3.6 Interface: record the REPL decision; fix Ctrl-C; posture
`15-interface.md` §5/§7: thread + blocking bridge is the accepted
design; known limitation named; `system.pause/stop` are the supported
interrupts; follow-up: catch `KeyboardInterrupt` around `cli.py`'s
`asyncio.run`, publish `system.stop`, exit 0. `09-guardian.md` §3.1:
add `guardian.posture.request/.reply` to Guardian's own tables and
implement the handler; fix the `mode`/`posture` key mismatch (or
better, make the contract carry both `mode` and a `posture` alias
until callers converge — one of the two, decided in the contracts PR).

### 3.7 Substrate operations
`03-kernel.md` §5.1: warning paragraph about the `~/.simorgh` default
and `SIMORGH_RUNTIME_DATA_DIR`; also in `kernel/config.py`'s docstring.
`02-ledger.md` (retention): add `metrics:history` and `curiosity:ticks`
to `DEFAULT_RETENTION` (short), a `max_events` cap alongside duration,
and a periodic compaction trigger independent of `system.tick.sleep`.
`01-bus.md` §8: describe the opt-in `max_handler_seconds` mechanism
instead of a blanket 300s; §9: build the named property tests or
downgrade the line to backlog; §12: new open question on a shared
cross-process identity secret for `local-multi`. `08-execution.md` §8:
process-group kill on sandbox timeout as a stated requirement.

### 3.8 Command surface: 38 names → ~11 (creator's decision)
Raised by the creator during this review: "the remaining commands from
v1 are so scattered and there are too many of them with almost the same
purpose … just keep few commands that would do the job." Agreed —
`COMMAND_NAMES` is v1's whole history (38 names, five honest `_NOT_YET`
stubs, several near-duplicates, several that the dashboard or the
model's own Guardian-gated tools now cover better). Decision recorded
in full in `15-interface.md` §12 q5. **Keep:** `status` (absorbs
`vitals`, `budget`, `skills`), `tasks` / `tasks work` (absorbs `work`),
`improve <path> <desc>` | `improve <topic>` (absorbs `propose`,
`patch`, `batch`, `evolve`), `plan <goal>` (absorbs `project`, `plan
<n>`), `research <topic>`, `interests [<topic>]` (absorbs `interest`,
`curious`), `auto [on|off|now]` (absorbs `autonomous`, `discover`,
`news`, `growth`), `pause`, `resume`, `exit` (absorbs `stop`, `quit`),
`help`. Plain text, `/`-optional, and `!<shell>` unchanged. **Remove:**
`reflect`, `digest`, `pending`, `log`, `trace`, `remind`, `history`,
`run`, `use`, `fetch`. Acceptance: `help` lists ≤ 12 names, every one
does something real, the banner's "where to start" list is a subset.
This is a product decision that also removes a class of confusion the
trial hit: Sim itself recited these 38 names as its "tools" (finding 4).

### 3.9 Visibility while thinking (creator's ask; a stated philosophy)
Raised during the review from real use: a web-chat request ("create a
simple web-based maze") showed "thinking" for a long time with no sign
of what Sim was doing or whether it was doing anything; the dashboard
"practically didn't give any useful information to understand whether
the system is working or not." The creator's stated philosophy is
visibility into Sim's thinking process — and the substrate already has
it: every turn appends `task.started` → `task.step` (phase, summary,
ok) → `action.proposed`/`action.result`/`action.denied` →
`task.completed` to `task:<session_id>` in the Ledger, in real time.
Nothing surfaces it to the human while it happens. **Decisions:**
(a) **CLI narration**: while a reply is pending, Interface prints one
dim line per event for *this* session (`… thinking (step 1, gather)`,
`… proposing read_file docs/x.md`, `… approved, ran in 0.4 s`,
`… denied: <reason>`, `… done in 12.3 s`) — Interface already
subscribes to the bus; this is a subscription on `task.step`/`action.*`
filtered by the pending session id, no new contracts. (b) **Dashboard
activity feed**: a "what Sim is doing now / just did" panel — recent
turns, tasks, steps, actions with timestamps and outcomes, updating
live — served from the same `task:*`/`activity` streams the read-only
API already exposes (`/api/logs`), plus a `/api/activity` roll-up that
merges them newest-first. Gauges stay, but the feed goes first: "is it
working" is answered by events, not by counters. (c) The same feed is
what the web chat shows under its "thinking" indicator. Acceptance:
during a real multi-step turn, the CLI shows ≥ 1 narration line before
the reply, and the dashboard shows the step within 3 s of the Ledger
append.

### 3.10 Self Model goals were never fed (fixed during the review)
Reported live: `propose …` created a real task (`task created:
baf727f147ed`) and a chat "show your tasks" a moment later answered
"queue is completely clear." The World Model consumed no `task.*` event
at all, so `goals.pending_tasks` was a constant 0 — the LLM answered
truthfully from a line that could never change (`06-worldmodel.md` §5's
`task.*` → goals row, unwired). Fixed: `update_goals` mutator +
`task.created/completed/failed/blocked` handlers; `pending_tasks`,
`active_projects` (kind=project), `recent_focus_areas` now move.

## 4. The testing-strategy change (the real lesson)

Three gaps let every finding above through a 2,200-test suite:

1. **No seam tests.** Nothing crosses Orchestration → Cognition → Memory
   for a real multi-turn session, so "built on both sides, connected on
   neither" is invisible. Add one integration scenario per Flow that
   drives the *whole* flow through real subsystems (fakes only for the
   provider) and asserts the user-visible outcome: "what did I just
   say?" recalls the prior turn; "what tools do you have?" names real
   registered tools; a chat `propose` produces a Guardian event.
2. **No front-door tests.** The CLI was never driven as a real
   subprocess with a real terminal until a human did it. Add a pty-based
   REPL test (Python's `pty` module, no new dependency) for: prompt,
   reply ordering, Ctrl-C mid-turn, arrow-key input, unicode/ASCII
   banner modes. Pipes are never terminals; four of this session's bugs
   only exist on a terminal.
3. **No concurrency property tests** for the Bus, which the spec itself
   already specifies. Build `tests/simorgh/bus/test_properties.py`.

Also a process rule for anyone running the system to test it: **isolate
both axes, every time** — the repo/cwd *and* `$HOME`/`SIMORGH_RUNTIME_
DATA_DIR`. A git worktree isolates one; a `subprocess.Popen(stdin=PIPE)`
tests neither the terminal nor the home directory. This session's
history file (`docs/EVOLUTION.md` 121, 124, 126) is the argument.

## 5. Next wave, prioritized

Ordered by (user-visible value ÷ size), smallest first within a tier.

| # | Item | Size | Acceptance |
|---|---|---|---|
| 1 | Posture request handler + event key fix (§3.6) | S | `budget` renders real posture; `GUARDIAN_POSTURE_CHANGED{mode:"guarded"}` → `vitals` shows `guarded` |
| 2 | Wire working memory both ends (§3.3) | S | Same-session "what did I just say?" recalls the prior turn |
| 3 | Single-owner assembly (§3.2) | S | Provider sees exactly one copy of self-summary/voice per turn |
| 4 | Fill `capabilities.tools/providers` (§3.4a) | S | "What tools do you have?" names the registered tools |
| 5 | Process-group kill on sandbox timeout (§3.7) | S | Forked grandchild is dead after `TimeoutExpired` |
| 6 | Ctrl-C → graceful `system.stop` (§3.6) | S | SIGINT mid-turn logs `stopping`, exits 0 |
| 7 | Retention defaults + `max_events` + periodic compaction (§3.7) | S/M | Seeded overflow prunes to policy without a sleep tick |
| 8 | Idle-loop hourly cap (§3.5) | S | 2 simulated idle hours never exceed the cap; excess ticks logged `rate_capped` |
| 9 | "How I run" Self Model section (§3.4b) | M | "Would you keep working unattended?" cites real loop state |
| 10 | Conversational `propose`/`patch` through Guardian (§3.1) | M | Chat "propose a skill for X" yields a real Guardian/activity event |
| 11 | Chat competence honesty (§3.5) | M | Unverified chat turn → zero `learn.competence.updated` |
| 12 | Reflection verdicts → Self Model (§3.4c) | M | A `drifting` verdict appears in the next self-summary |
| 13 | Layer-5 input cap; retrieval window/index (§3.4d, §3.3) | M | Synthetic oversized memory item never yields second-order `context_too_large`; retrieval latency flat at 10k records |
| 14 | Seam + pty test suites; bus property tests (§4) | M | Suites exist and run on `memory` and `sqlite` |
| 15 | `delegate.py` (Flow 6), full `resume.py` snapshot (Flow 7) | L | Spec'd scenarios `test_flow_6_*`, resumed session keeps assembled context |
| 16 | Multi-session WebSocket; admin control through Guardian (`02` §6.1/§6.2) | L | Two clients hold independent turns; admin actions publish `action.proposed` |

*Added during the review at the creator's request:* **command-surface
consolidation, 38 → ~11** (§3.8, `15-interface.md` §12 q5) — S/M; slots
between items 8 and 9. Acceptance: `help` lists ≤ 12 names, each does
something real; parser/dispatch/banner tests updated.

Stage C of the cutover (deleting `src/`) stays gated exactly as
`06-migration-from-v1.md` §6 says — on living with v2 as the daily
driver. The first real day of that produced milestones 124–128; that is
the trust ramp working as intended, not a reason to accelerate it.

## 6. Assessment of the build work

The creator asked for a straight answer on the quality of the build,
so here it is, in both directions.

**What was genuinely good.** The architecture was implemented
faithfully: sixteen subsystems, one shared dependency (`contracts`),
message-only communication, an append-only Ledger, Guardian as the
sole path from proposal to effect — all verified in code, not just
claimed. Every scoped-down piece is documented in place rather than
hidden. The discipline of *root-causing rather than patching* held even
under pressure: three identical-looking CLI symptoms were traced to
three unrelated causes and each was fixed at its actual source with a
regression test confirmed to fail on the old code first.
`EVOLUTION.md` is an unusually honest engineering record — it names
its own mistakes (the four `~/.simorgh` leaks, the API-only trial, the
premature "it's fixed" claims) in the same register as its successes.
The strongest files (`guardian/service.py`, `bus/client.py`, `kernel/
service.py`, `cognition/compaction.py`, `memory/store.py`, `persona/`)
would pass review at a careful shop.

**What was not good enough.** The system was declared working for an
hour based on the one channel that was convenient to script, while the
front door was broken; the creator found that, not the tests. "Fixed"
was claimed three times for the same symptom before the real terminal
was ever used to verify — each claim was honest and each was wrong,
which is worse than one careful check. Test-process hygiene failed
repeatedly: four writes into the creator's real home directory, and
test processes left running that collided with the creator's own
session and muddied the diagnosis of a bug they were chasing. And the
most important seam of all — the one that makes this a self-improving
agent rather than a chatbot with a nice memory — was left looking wired
when it wasn't, without a test that would have said so.

**Net.** The code is good; the *verification* of the code against real
use was the weak link, and it was weak in a specific, fixable way
(§4). I would not rewrite anything. I would spend the next wave on the
sixteen items above — the first eight are all small — and I would not
believe any future "it works" that hasn't been driven through a real
terminal and a real multi-turn session first.
