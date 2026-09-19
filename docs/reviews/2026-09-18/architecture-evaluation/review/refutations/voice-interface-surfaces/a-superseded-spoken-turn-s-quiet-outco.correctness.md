# refute:correctness:A superseded spoken turn's 'quiet' outco

*Workflow: review · Phase: Refute · Agent id: `ab7e8cbdd93bfdb3a` · Tool calls: 7*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "A superseded spoken turn's 'quiet' outcome flips the floor and drops the newest turn's real answer",
    "kind": "bug",
    "severity": "high",
    "claim": "`_stay_quiet(turn_id)` unconditionally sets `turns.state = LISTENING` when the state is THINKING, even when THINKING belongs to a NEWER asked turn, so the newer turn's answer is then refused by `reply_ready` as 'the session is listening' and never spoken.",
    "evidence": [
      "simorgh/voice/session.py:1621-1632 (`_stay_quiet`): `actions = self.turns.reply_ready(turn_id)` ... `if self.turns.state == THINKING: self.turns.state = LISTENING if self.turns.auto_listen else self.turns.state`",
      "simorgh/voice/turns.py:206-219 (`reply_ready`): the `_superseded` branch returns SPEAK 'late; the newer turn is still owed' and does not change state; then `if self.state != THINKING: return [Action(Actions.DROP_REPLY, ..., reason=f\"the session is {self.state}\")]`",
      "Trigger chain is live: session.py:579-590 `_cancel_outstanding` publishes `task.cancel` for the old turn's session id; orchestration/worker.py:218 subscribes; orchestration/session.py:887 ends the session with CANCELLED_REASON at the next step boundary; voice/pipeline.py:264-272 `_on_task_event` does `fut.cancel()` when 'cancelled' in reason; pipeline.py:370-372 `ask` returns \"\"; session.py (in `_ask_and_speak`, after `reply = await self._pipeline.ask(...)`): `if not _strip_tone(reply).strip() or is_quiet(...): ... await self._stay_quiet(turn_id)`. A model answering QUIET to the older turn is a second trigger with no cancel needed.",
      "Reproduction against the real TurnManager (python3 script in scratchpad, replicating session.py:1621-1632 verbatim): `after two asks: state=thinking asked=2 superseded=1` / `_stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')]` / `state after _stay_quiet(1): listening, asked=2` / `reply_ready(2) for the NEW turn's real answer -> [('drop_reply', 'the session is listening')]`",
      "`grep -c 'self.turns.state = ' simorgh/voice/session.py` -> 17 direct writes; `_guarded` (session.py:487-500) does the same flip on any exception in an older turn's task; ASK at session.py:465 creates a new `_ask_task` without cancelling the previous one, so two `_ask_and_speak` coroutines run concurrently."
    ],
    "why_it_matters": "This is the exact live complaint recorded in turns.py's own comments ('a 15 s answer was dropped because the creator spoke meanwhile ... Sim was blamed for silence', 2026-09-13): ask one thing, ask another before the first is answered, and the second answer appears on screen as 'reply dropped' and is never spoken. It is also the general form of the 'per-turn fact in a session singleton read across an await' bug: the singleton here is the state machine's `state`.",
    "recommendation": "Make TurnManager the only writer of `state`. Add `TurnManager.reply_quiet(turn_id)` (and `reply_failed(turn_id)`) that leave THINKING only when `turn_id == self._asked_turn` (and clear `_superseded` when it matches), then delete all 17 `self.turns.state = ...` writes in session.py, replacing each with a named TurnManager method. Add the reproduction above as a unit test in tests/simorgh/voice (48 test files exist; none reference `_superseded`).",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read _stay_quiet and reply_ready |  # command is exactly what this asks for. await self._pipeline._publish(topics.UI_COMMAND_REQUEST, { # noqa: SLF001 "line": "restart", "requested_by": f"{speake |
| 2 | Bash | Read playback state handler and grep callers |  if owed: self._go(THINKING, f"playback {state.state}; the newer turn's answer is still owed") else: self._go(LISTENING if self.auto_listen else IDLE, f"playbac |
| 3 | Bash | Read ASK handling, cancel path, ask-and-speak, pipeline cancel |  for c in self._clocks.values(): if c.turn_id == self.turns.turn_id - 1 or c.turn_id == self.turns.turn_id: c.interrupted_at = frame_time c.stopped_at = self._n |
| 4 | Bash | Inspect TurnManager constructor and event types | 27:from .api import PlaybackState, TranscriptEvent, VadEvent 42:class Policy: 57:class Action: 65:class Actions: 78:class TurnManager: 80: auto_listen: bool = T |
| 5 | Bash | Read TurnManager init, _go, _new_turn, vad handling | class TurnManager: policy: Policy = field(default_factory=Policy) auto_listen: bool = True state: str = IDLE turn_id: int = 0 response_id: int = 0 partial: str  |
| 6 | Bash | Reproduce the state flip against real TurnManager | ['kind', 'speech_ms', 'silence_ms', 'level'] after two asks: state=thinking asked=2 superseded=1 _stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn |
| 7 | Bash | Verify cancel chain, test coverage, and known-findings overlap |  # budget, think/tool timeouts and lease heartbeat are the bound. self._subs.append(await self._bus.subscribe( topics.TASK_AVAILABLE, self._on_available, group= |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** I read the cited code and re-ran the reproduction against the real TurnManager; the claim is true of the code today. `_stay_quiet` (simorgh/voice/session.py:1621-1632) calls `reply_ready(turn_id)`, and when `turn_id` is the superseded turn and state is THINKING, `reply_ready` (turns.py:206-215) clears `_superseded`, mints a SPEAK 'late' action and does NOT change state. `_stay_quiet` then feeds a synthetic `PlaybackState("finished")` (turns.py:255-266: state is THINKING, not AGENT_SPEAKING, so it only clears `_late_playing`) and then unconditionally writes `self.turns.state = LISTENING` because state is THINKING -- but THINKING at that moment belongs to the NEWER asked turn (`_asked_turn` is still 2). The newer turn's real answer then hits `reply_ready(2)`: `turn_id == _asked_turn`, state is LISTENING, so turns.py:219 returns DROP_REPLY 'the session is listening'. Both triggers are live: (1) session.py:473 `_cancel_outstanding` publishes TASK_CANCEL before each new ask; worker.py:218 subscribes; orchestration/session.py:60/888 reports `CANCELLED_REASON = "the task was cancelled"`; pipeline.py:264-272 `fut.cancel()`s on 'cancelled'; pipeline.py:370-372 `ask` returns ""; session.py:1106-1115 routes an empty reply to `_stay_quiet(turn_id)`. (2) A model answering QUIET to the older turn takes the same path with no cancel involved. ASK at session.py:474 creates a new `_ask_task` without cancelling the previous coroutine, so both `_ask_and_speak` run concurrently, which is what lets the older turn's quiet outcome land while the newer turn is owed. `_guarded` (session.py:487-500) has the same unconditional flip on exception. This is a genuine bug (category c), not in the known-findings list (the audit/review docs mention nothing about `_superseded`, late replies or `_stay_quiet`), and no test in tests/simorgh/voice (48 files) references `_superseded`. Severity 'high' is fair: the user-visible symptom is exactly the 2026-09-13 complaint the code's own comments record (answer dropped, Sim blamed for silence), and it recurs whenever a second question is asked before the first is answered and the first ask is cancelled or answered QUIET.

### evidence

- simorgh/voice/session.py:1621-1632 -- `_stay_quiet`: `actions = self.turns.reply_ready(turn_id)` ... `if self.turns.state == THINKING: self.turns.state = LISTENING if self.turns.auto_listen else self.turns.state` (no check that turn_id is the asked turn)
- simorgh/voice/turns.py:206-215 -- `reply_ready`: superseded branch sets `self._superseded = 0`, `_late_playing = True`, returns SPEAK 'late; the newer turn is still owed' without touching state; turns.py:218-219 `if self.state != THINKING: return [Action(Actions.DROP_REPLY, ..., reason=f"the session is {self.state}")]`
- simorgh/voice/turns.py:255-266 -- `handle_playback_state('finished')` only transitions when state is AGENT_SPEAKING or INTERRUPTED; from THINKING it just clears `_late_playing`
- Reproduction (python3 against real TurnManager, _stay_quiet body copied verbatim): `after two asks: state=thinking asked=2 superseded=1` / `_stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')]` / `state after _stay_quiet(1): listening asked=2 superseded=0 late=False` / `reply_ready(2) -> [('drop_reply', 'the session is listening')]`
- simorgh/voice/session.py:473-474 -- ASK: `await self._cancel_outstanding(before=action.turn_id)` then `self._ask_task = asyncio.create_task(self._guarded(self._ask_and_speak(...)))` (previous _ask_task not cancelled)
- simorgh/voice/session.py:579-590 -- `_cancel_outstanding` publishes `topics.TASK_CANCEL` with reason 'the person went on to a new turn' for every outstanding turn < before
- simorgh/orchestration/worker.py:218 -- `self._subs.append(await self._bus.subscribe(topics.TASK_CANCEL, self._on_cancel))`; simorgh/orchestration/session.py:60 `CANCELLED_REASON = "the task was cancelled"`, used at :888 and :1727
- simorgh/voice/pipeline.py:264-272 -- `_on_task_event`: `if "cancelled" in reason: fut.cancel(); return`; pipeline.py:370-372 `except asyncio.CancelledError: if fut.cancelled(): return ""`
- simorgh/voice/session.py:1106-1115 -- `if not _strip_tone(reply).strip() or is_quiet(_strip_tone(reply)): ... await self._stay_quiet(turn_id); return`
- simorgh/voice/session.py:487-500 -- `_guarded` on any Exception: `if self.turns.state in (THINKING, AGENT_SPEAKING): self.turns.state = LISTENING` (same unconditional flip)
- `grep -c 'self.turns.state = ' simorgh/voice/session.py` -> 17
- `grep -rln '_superseded' tests/simorgh/voice | wc -l` -> 0 (of 48 test files); `grep -n '_superseded\|late\|quiet' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html` shows no overlap with this finding
- simorgh/voice/turns.py:95-101 -- comment records the live 2026-09-13 complaint this path reproduces ('a 15 s answer was dropped because the creator spoke meanwhile ... Sim was blamed for silence')

**severity adjustment:** keep

