# v2 Live Trial — Observations

Real `sim.sh` (v2), booted against the real, cutover-live `~/.simorgh`,
driven via the dashboard `/api/chat` endpoint
(`session_id=fable-context-trial-2026-09-06`). Raw request/response
pairs in `transcript.jsonl`.

## 1. Identity / persona — PASS

Asked "who are you, and what makes you different from a generic
assistant?" Replied in full character as Simorgh/Sim, named its own real
code areas (agents, cognition, memory, orchestrator, sandboxing, tools),
was honest about limits ("no unprompted notifications, no 100-skill
catalog"), and pushed back on a hypothetical capability it doesn't have
(day-trading signals) rather than confabulating. No mention of
Claude/Claude Code. Confirms milestone 120's fix holds under real,
un-scripted use. ~10.4s response time.

## 2. Same-session conversational memory — PARTIAL / a real gap found

Immediately asked "what did I just ask you in my previous message?" — it
answered with an unrelated OLD memory (a "Hello, World!" Python request,
almost certainly from the real migrated v1 history) instead of the
actual immediately-prior turn ("who are you..."). It did *not* fail
honestly ("I don't have that") — it confidently answered wrong,
attributing an old episodic-memory hit to "your last message."

**Root-caused, not fixed** (traced the code path rather than guessing):
`session_id` itself threads correctly end to end (dashboard →
`httpapi.py::_chat` → `percept.text.received` payload →
`orchestration/service.py::_on_percept` → `worker.py::run_percept_chat`).
But `run_percept_chat` builds a **brand-new, ephemeral `Session` object
on every single call** (`Session(task_id=session_id, kind="chat", ...,
user_text=text)`), seeded with *only* the current message — there is no
store keyed by `session_id` that loads and re-feeds prior turns for that
session. `session_id` is used purely for *routing* (matching the eventual
`turn.completed` back to the right pending HTTP future, and refusing a
second concurrent call with the same id) — never for conversation
history.

So whatever "memory" the reply drew on ("Hello, World!") wasn't turn-by-
turn continuity at all — it's Memory subsystem's own retrieval (semantic/
episodic recall triggered inside the tool loop) surfacing *some* past
record it judged relevant, with no guarantee it's the actual last turn.
This isn't unique to the dashboard/API channel — the CLI channel goes
through the identical `run_percept_chat` path, so the same gap likely
applies there too (unmeasured in this trial; would need a live CLI probe
to confirm v1-style ShortTermMemory-equivalent behavior is genuinely
absent in v2, not just untested here).

This reads as a real, load-bearing architectural gap rather than a small
bug — "conversational continuity" as actually experienced (not just
long-term memory recall) may need an explicit per-session rolling
history the way v1's `ShortTermMemory` provided, fed into
`Session`/`_assembler` alongside the self-model's protected block.
**Deliberately not attempted as a fix in this trial** — it's a design
decision, not a one-line patch, and the creator asked for broad
probing + a written record for Fable's review, not a redesign mid-trial.

## 4. Self-model capability description is stale/drifted (v1 vocabulary
   leaking through migrated memory) — real finding, easy to fix

Asked "propose an outcome-feedback skill" — got a well-structured,
genuinely thoughtful *conversational draft* of what the skill would look
like, but **nothing real happened**: no new event on `activity`,
`learn:skills`, or `guardian:rejected`. It talked through the proposal
rather than actually invoking Guardian/Execution's real
propose-audit-apply pipeline — even after it had explicitly, unprompted,
named this exact failure mode as a pattern in itself one turn earlier
("talking through a fix instead of running it"). Directly ironic, and
worth flagging to the creator verbatim.

Then asked "what tools do you actually have access to, concretely" —
got back **v1's own CLI command vocabulary almost verbatim**
(`propose <topic>`, `batch N <topic>`, `evolve <count> <goal>`,
`pending`) as if it were v2's real current action surface. Checked
against the real Ledger: v2's actual registered tools
(`execution:tools` stream) are `git_commit`, `git_revert`,
`apply_skill`, `read_file`, `list_dir`, plus 2 more — none of which
match what it described. This is migrated v1 conversational memory
bleeding into a *capability self-description* that should instead be
grounded in the self-model's own real tool/action list. A real, well-
scoped gap: the self-model's rendered "what I can do" section should be
populated from v2's actual registered tools (Execution already tracks
this — `execution:tools`), not left open for the LLM to freely recall
from old migrated chat history.

## 5. Sim confidently misdescribes its own architecture — most
   significant finding of this trial

Asked "would you keep making real progress on a hard problem across a
few hours unattended, or go idle?" — got a long, confident, specific
answer: **"I only run when you send me a message... no daemon, no
scheduled wake-up, no persistent thread chewing on your problem...
nothing happens for three hours."**

This is flatly false about the system actually running under it, and
demonstrable from the same Ledger in the same minute: the
`curiosity:ticks` stream was firing a real background tick every ~3
seconds throughout this entire trial, with zero correlation to when I
sent messages (confirmed: two `cognition.think` calls with
`purpose=plan` and `purpose=review` fired autonomously *before* my very
first probe of this trial even reached the server). v2 has a real
autonomous loop (Curiosity/Planning/Reflection ticking continuously);
this is not a hypothetical capability, it's the process that was
running the whole time this trial ran.

This is a different, arguably more serious problem than the persona
bug milestone 120 fixed. That bug was about *identity* ("who are you").
This is about *self-knowledge of its own real operating characteristics*
— and it answered with total confidence, in convincing, specific detail
("no daemon, no scheduled wake-up"), rather than hedging or checking.
Nothing in what it said was hedged as "I think" or "as far as I know" —
it was stated as settled fact, wrong. Whatever content shaped that
answer, it wasn't the self-model's own `continuity`/`capabilities`
data (which does exist and is accurate about restarts) — it read as a
generic LLM prior about "how chatbots typically work" overriding
grounded architectural self-knowledge that was, in principle, available
to it. Worth the creator's direct attention before any further "how
does it actually behave" judgment is made about the cutover.

## 6. Intermittent instant-empty-floor reply — real bug, not fully
   root-caused, worth a dedicated follow-up

Across two live sessions, some chat calls returned `{"text": "",
"floor": true}` in ~0.04s (every successful call took 5-23s) — no
error surfaced to the HTTP client, nothing printed to the process's own
console, no Guardian denial logged, and critically **no
`task.step` event recorded at all** (confirmed via the real Ledger's
`task:<session_id>` stream: a normal turn is `task.started` →
`task.step` (phase=gather) → `task.completed`; a failed one is
`task.started` → `task.completed` with an empty `result_summary`,
skipping `task.step` entirely) — meaning `SessionRunner._think()`
(`simorgh/orchestration/session.py:121-136`) got `reply.payload.get("ok")
is False` from Cognition on the very first step and returned `None`,
which `run()` (line 88-90) converts straight to an honest-looking but
silent `Outcome(floor=True, result_summary="")` for chat sessions —
`_think()`'s own `if ...: return None` throws away *which* Cognition
error code caused it (`no_real_provider`/`budget_exceeded`/
`context_too_large`/`paused`/`invalid_request`), and nothing between
there and the HTTP response preserves it either. That swallowed-error
design is itself worth fixing regardless of the root cause, since it
turned a ~2-minute investigation into a much longer one.

Ruled out as the cause (checked directly against the running process):
- `BudgetGuard`'s per-provider rolling-window call cap
  (`cognition:budget:claude_code_cli`, 500 calls/5h default) — only 8
  real calls logged, nowhere close.
- Per-request `max_cost_usd` (chat purpose: $0.50 budgeted, $0.50 request
  cap in `session.py`'s own think request) — real costs were $0.01-0.02.
- Cognition's own internal pause flag (set from `system.state` — the
  Ledger's `system` stream shows exactly one event, boot→running, ever).
- `SELF.md`/protected-block size (615 bytes on disk — nowhere near a
  12,000-token budget).
- Permanent session degradation — ruled out directly: the exact same
  session, immediately after a failed call, answered a follow-up
  message normally (9.5s, real reply). Not a one-way "session is now
  broken" state.

Pattern actually observed: not tied to a fixed call count (failed on
call 7 of one session, call 2 and call 6/8 of a fresh-boot second
session — frequency seemed to *increase* as the trial went on, roughly
1-in-3 calls by the end), not obviously tied to message content (both a
short "just say yes" and a long technical question succeeded
elsewhere), and self-recovers on the very next call.

One more concurrency hypothesis checked and NOT confirmed but not fully
ruled out either: `curiosity:ticks` was firing a real background tick
every ~3 seconds throughout the whole trial (see finding 5), and two
autonomous `cognition.think` calls (`purpose=plan`, `purpose=review`)
fired before my very first probe even arrived — so background activity
genuinely overlaps with API-driven chat calls in wall-clock time.
Traced the two most likely shared-state collision points this session
had already found *twice* elsewhere (milestone 106's `_pending_turns`
key collision; this session's own `_pending_chats` 409 guard) looking
for a third instance: `Worker.current_task_id`/`current_kind`
(`orchestration/worker.py:38-39,98,102`) *are* shared, unguarded
instance attributes clobbered by any concurrent `run()` call, but are
only ever read for status/metrics display (`orchestration/service.py:
81,115`), not for reply correlation — ruled out as the cause of a wrong/
empty reply specifically. `_on_percept` awaits `worker.run_percept_chat`
directly inside the bus subscription callback (serializing chat
percepts through that path), and `Bus.request`/`request_or_error`
correlate replies by a fresh `message.id` per call, which should be
collision-safe even under real concurrency. Did not find the actual
mechanism in the time spent.

**Leading hypothesis, formed but not confirmed against a live error
code:** `context_too_large`, from growing *overall trial* memory/
context rather than anything specific to one session. Failure frequency
climbed steadily across the trial (roughly 1-in-8 calls early on, ~1-in-2
by the end) regardless of which `session_id` was used, including a
never-used-before random uuid — which rules out "this one task's own
accumulated history" as the sole cause (a per-task_id theory was
checked and doesn't fit: a genuinely fresh session_id failed too) but
fits a *global* growth in what `Assembler.assemble()` folds in as
context (e.g., recent Memory activity across the whole trial, not just
one session) eventually exceeding the `chat` purpose's default 12,000-
token `max_tokens_in` budget. Not confirmed directly — `_think()`
(`session.py:134-135`) discards *which* Cognition error code triggered
the `None` return before it ever reaches the Ledger or the HTTP
response, and the process's own stdout was fully block-buffered (not a
tty) so nothing was visible live either.

**Update: fixed, during this same trial, not left as an observation.**
Shipped the error-visibility fix first (`_think()` now records the real
Cognition error on the task's own Ledger stream instead of discarding
it) -- the very next occurrence named it plainly:
`context_too_large -- context still exceeds budget after all
compaction layers`. Root cause: `_think()` never set `allow_summarize`
on its `cognition.think` request, so it defaulted to `false` and layer
5 (real model summarization, Cognition's own explicit "last resort" for
exactly this situation) was never reachable for an ordinary chat turn —
despite being fully built, wired, and tested. Fixed narrowly:
`allow_summarize` is now `true` only for `kind="chat"` sessions, still
`false` for patch/research/plan/skill (summarizing away a draft's own
precise code context could silently corrupt a real code change).
**Live-verified in this same trial**: the identical rapid-fire 8-probe
sequence that had failed 2-of-6 times before the fix ran clean 8-for-8
afterward, with zero `context_too_large` errors on the task stream.
Both fixes are commits `38fe8d7` and `1295762`; full write-up in
`docs/EVOLUTION.md` milestones 122-123.

**Residual, rarer edge case, found immediately after declaring victory:**
one more `context_too_large` did occur on the very next probe after the
clean 8-for-8 run (same error text, same 0.04s instant-fail signature) —
so the fix reduced the failure rate substantially but didn't eliminate
it outright. Layer 5's own summarization call
(`_summarize_for_compaction`, `cognition/service.py:227-239`) has its
own budget (`Budget(16_000, 2_000, 0.1)`) and could itself be getting
overwhelmed if the raw retrieved content is large enough — not
confirmed, not chased further in this trial (genuinely diminishing
returns after two root-caused-and-fixed rounds on the same underlying
symptom). Whoever picks this up next: `Assembler._memory_retrieve()`
(`orchestration/context.py:71-79`) still has no per-item or aggregate
size cap on what it pulls from Memory before handing it to Cognition at
all — capping it there directly (rather than relying entirely on
downstream compaction to save an unbounded input) is probably the more
robust fix than anything in the compaction pipeline itself.

## 7. The CLI itself was broken the whole time — found only when the
   creator tried it directly, not by this trial

This entire trial, up to this point, drove Sim exclusively through the
dashboard's `/api/chat` HTTP endpoint — the channel scriptable without a
live terminal. The creator tried the actual primary interface, `./sim.sh`'s
interactive REPL, mid-trial and got nothing back: typed "hello", saw
only repeated `^M` characters, no reply, ever. When asked point-blank
whether *anything at all* had appeared, the answer was "it appears that
running sim.sh doesn't accept any text from cli at all."

Root cause (`interface/service.py`'s `_repl_main`): the REPL thread
scheduled each line's handling fire-and-forget and immediately
re-blocked on the *next* `input()` call before the previous line's
handler had even started — a real reply, printed from a different
thread while this one already sat inside a fresh `input()`, routinely
never became visible. Notably, this exact race was already known and
described in this project's own test suite before today, treated as an
accepted fact about how the REPL works rather than the bug it was.
Fixed to make the REPL thread actually wait (commit `fccee74`,
`docs/EVOLUTION.md` milestone 124) — live-verified against a real
`sim.sh` subprocess with an isolated `$HOME`, not just a unit test.

**The honest lesson, stated plainly because the creator named it
directly:** "how does the end product behave" cannot be fully answered
by driving one convenience channel for an hour, however thoroughly. The
dashboard API is real and working; the actual front door was silently
broken the entire time, and nothing in an hour of API-only probing
would ever have caught that. Any future trial like this one should
drive the CLI directly (a piped/scripted subprocess, isolated `$HOME`)
from the start, not as a fallback after a user hits a wall.
