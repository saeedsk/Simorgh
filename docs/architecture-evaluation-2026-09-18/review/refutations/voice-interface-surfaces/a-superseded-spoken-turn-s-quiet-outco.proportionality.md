# refute:proportionality:A superseded spoken turn's 'quiet' outco

*Workflow: review · Phase: Refute · Agent id: `a7d98a1743dba3239` · Tool calls: 9*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 2 | Bash | Find trigger chain in session.py | 261: self._ask_task: asyncio.Task \| None = None 360: await self._cancel_outstanding(before=10**9) 361: for task in (self._stt_task, self._ask_task, self._speak_ |
| 3 | Bash | Read quiet branch, pipeline cancel path, tests |  speaker_name=speaker, speaker_relation=relation, room=room, speaker_before=before) finally: self._outstanding.pop(turn_id, None) still.cancel() with contextlib |
| 4 | Bash | Inspect turns.py types and existing tests | 161: # answer the person waited for: said now, late; the second follows. 162: late = tm.reply_ready(1) 163: self.assertEqual(_kinds(late), [Actions.SPEAK]) 164: |
| 5 | Bash | Read the existing superseded test and handle_playback_state |  self.assertEqual(tm.handle_vad(_speech(900)), []) def test_a_reply_to_an_old_turn_is_dropped(self) -> None: tm = TurnManager(Policy(min_speech_ms=200, end_of_t |
| 6 | Bash | Run reproduction against real TurnManager | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/repro.py", line 1, in < |
| 7 | Bash | Run reproduction with repo on PYTHONPATH | after two asks: state=thinking asked=2 superseded=1 _stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')] state after fake 'finished' |
| 8 | Bash | Read reply handling, THINKING write, cancel chain, history |  self._talking_with[speaker] = self._now() took = clock.reply_at - clock.final_at if clock.final_at else 0.0 context = Context(user_text=text, language=language |
| 9 | Bash | Check cancel reason constant and reply-loop exit | simorgh/orchestration/session.py:60:CANCELLED_REASON = "the task was cancelled" "text": text, "seconds": 0.0, "engine": getattr(self._tts, "last_engine", "") or |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is as the finding says, and the chain is live in the current checkout, not historical. `_stay_quiet` (simorgh/voice/session.py:1621-1632) calls `reply_ready(turn_id)`, feeds a fake `PlaybackState("finished")` to the manager (which is a no-op on state because the manager is THINKING, not AGENT_SPEAKING, turns.py:255-266), then flips `THINKING -> LISTENING` with no check that `turn_id` is the turn whose answer is owed. `reply_ready` (turns.py:206-219) then refuses the newer turn's real answer with `DROP_REPLY 'the session is listening'`, and `_speak_reply` (session.py:1775-1778) dispatches that and returns, so the newer answer is never spoken. The trigger is the ordinary path, not an edge: every ASK with an older turn outstanding calls `_cancel_outstanding` (session.py:473), the worker returns `Outcome("failed", reason="the task was cancelled")` at the next step boundary (orchestration/session.py:60, 887), the pipeline matches the substring "cancelled" and cancels the future (voice/pipeline.py:271-274), `ask` returns "" (pipeline.py:370-372), and the empty reply takes the `_stay_quiet` branch (session.py:1106-1115). The older turn's "" therefore arrives within one step-time, well before the newer turn's multi-second answer. I reproduced it against the real TurnManager with the session's lines copied verbatim (output quoted in evidence). The grep count of 17 direct `self.turns.state =` writes is exact. On the skeptic lens: this is a genuine bug (kind c) on the primary voice path at this system's scale (one family talking to Sim; asking a second question before the first is answered is normal use), and it defeats the very `_superseded`/late-answer mechanism the creator added on 2026-09-13 (turns.py test at tests/simorgh/voice/test_turns.py:142-174 covers the manager alone and so passes). The recommendation is proportionate: the minimal fix is two guards (`_stay_quiet` and `_guarded` only leave THINKING when `turn_id == turns._asked_turn`), and the fuller "TurnManager is the sole writer of state" refactor is a one-file change for one developer that removes the class of bug the project has already recorded three times. I would not lower severity.

### evidence

- simorgh/voice/session.py:1621-1632 `_stay_quiet`: `actions = self.turns.reply_ready(turn_id)` ... `if self.turns.state == THINKING: self.turns.state = LISTENING if self.turns.auto_listen else self.turns.state` -- no comparison of turn_id against the asked turn
- simorgh/voice/turns.py:206-219 `reply_ready`: superseded branch returns SPEAK 'late; the newer turn is still owed' without changing state; then `if self.state != THINKING: return [Action(Actions.DROP_REPLY, ..., reason=f"the session is {self.state}")]`
- simorgh/voice/turns.py:255-266 `handle_playback_state('finished')`: only changes state when `self.state == AGENT_SPEAKING`; the fake 'finished' sent by `_stay_quiet` leaves THINKING untouched, so the unconditional flip that follows is the only state change
- Reproduction (PYTHONPATH=/Users/saeed/ws/Simorgh python3 scratchpad/repro.py, session.py:1625-1631 copied verbatim): `after two asks: state=thinking asked=2 superseded=1` / `_stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')]` / `state after fake 'finished': thinking` / `state after _stay_quiet(1): listening, asked=2` / `reply_ready(2) -> [('drop_reply', 'the session is listening')]`
- Trigger chain live: session.py:473-474 every ASK calls `_cancel_outstanding(before=turn_id)` then creates a new `_ask_task` without cancelling the old coroutine; session.py:579-590 publishes TASK_CANCEL; orchestration/worker.py:218 subscribes `_on_cancel`; orchestration/session.py:60 `CANCELLED_REASON = "the task was cancelled"`, :887 returns it at the next step boundary; voice/pipeline.py:208-209 subscribes TASK_FAILED, :271-274 `if "cancelled" in reason: fut.cancel()`; pipeline.py:370-372 `if fut.cancelled(): return ""`; session.py:1106-1115 empty reply -> `await self._stay_quiet(turn_id)`
- session.py:1775-1778 `_speak_reply`: when no SPEAK action, `for action in actions: await self._dispatch(action)` then `return` -- DROP_REPLY is terminal; session.py:478-485 dispatch of DROP_REPLY only logs and publishes VOICE_SPOKEN dropped
- `grep -n 'self.turns.state = ' simorgh/voice/session.py` -> 17 lines (498, 650, 850, 988, 1009, 1212, 1257, 1330, 1362, 1406, 1426, 1560, 1631, 1769, 1828, 1891, 1907); session.py:487-500 `_guarded` flips THINKING/AGENT_SPEAKING -> LISTENING on any exception with no turn check
- tests/simorgh/voice/test_turns.py:142-174 tests the superseded/late path against TurnManager alone, never through `_stay_quiet`; `grep -rn '_stay_quiet\|stayed_quiet' tests/simorgh/voice` -> no matches
- git log -5 -- simorgh/voice/session.py simorgh/voice/turns.py shows the latest commits (6bd5229, e317076) do not touch this path; docs/EVOLUTION.md has no entry for `_stay_quiet`/superseded, so this is current state, not a fixed historical bug

**severity adjustment:** keep

