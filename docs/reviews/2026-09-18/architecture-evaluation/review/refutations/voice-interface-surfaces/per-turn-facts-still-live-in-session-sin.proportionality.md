# refute:proportionality:Per-turn facts still live in session sin

*Workflow: review · Phase: Refute · Agent id: `ad7fe708f35819459` · Tool calls: 8*

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
    "title": "Per-turn facts still live in session singletons and are read across awaits; the known-voice barge-in judge is unthrottled",
    "kind": "bug",
    "severity": "medium",
    "claim": "`_last_speech_s`, `_last_pcm` and `_last_skip` are set per turn in `_identify` and read after later awaits by `_ask_and_speak`, `_enroll_take` and the introduction path, while a second `_ask_and_speak` for the next turn can overwrite them (ASK never cancels the previous ask task); separately, `_only_a_voice_we_know` runs a speaker embedding of the 1.2 s pre-roll on every 30 ms frame while a non-family sound continues over Sim's voice.",
    "evidence": [
      "simorgh/voice/session.py:712-716, 725 set `self._last_speech_s`, `self._last_pcm`, `self._last_skip` inside `_identify(turn_id)`",
      "session.py `_ask_and_speak`: `segments = await self._attribute(turn_id, identification)` (a `to_thread` diarisation) precedes `may_refine(..., seconds=self._last_speech_s, ...)` at session.py:940; `_enroll_take` reads `self._last_pcm` at :842-843 after `await self._pipeline._publish(...)` at :830; introduction path reads it at :1415-1416",
      "session.py:465 `self._ask_task = asyncio.create_task(self._guarded(self._ask_and_speak(...)))` with no cancel of the previous `_ask_task`, so two turns' `_ask_and_speak` overlap",
      "session.py:655-706 `_only_a_voice_we_know`: gated only by `barge_in_known_voice`, `speech_ms >= barge_in_speech_ms` and embedder presence, then `await asyncio.to_thread(self._embedder.embed, samples, 16000)` with no memo; vad.py:548 `self._speech_ms += self._frame_ms` keeps the condition true on every subsequent frame; the await sits inline in the mic loop (`_on_frame`, session.py:373-385). Default off: voice/config.py:88 `barge_in_known_voice: bool = False`",
      "The same shape was fixed for `speaker` on 2026-09-18 (session.py:955-968 comment: '23 of 122 named turns reached voice:turns with speaker=\"\"')"
    ],
    "why_it_matters": "The first is the same bug class the creator just paid for, still present for the enrolment and refinement paths: a take can be kept with another turn's audio/length, which is exactly how one family member's voice was blended into another's before. The second, when enabled, saturates the frame loop (one embedding per frame) precisely while the TV is on, which is when the creator enables it.",
    "recommendation": "Move `speech_s`, `pcm`, `skip` onto `TurnClock` (already keyed by turn id) and pass the clock into `_enroll_take`/`_introduce_step`; cancel or fence the previous `_ask_task` at ASK (or make `_ask_and_speak` bail if `turn_id != turns._asked_turn` after each await). Throttle `_only_a_voice_we_know` to one judgement per barge-in candidate (cache the verdict until `speech_end`) and run it off the frame loop.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Locate cited symbols in voice session code |  1961 simorgh/voice/session.py 577 simorgh/voice/vad.py 353 simorgh/voice/config.py 2891 total 55:class TurnClock: 131:def may_refine(*, segments, probable: boo |
| 2 | Bash | Read TurnClock, state init, frame loop and ASK dispatch | class TurnClock: turn_id: int speech_start: float = 0.0 speech_end: float = 0.0 final_at: float = 0.0 reply_at: float = 0.0 first_audio_at: float = 0.0 # when t |
| 3 | Bash | Read cancel_outstanding, barge-in judge, identify, enroll_take, ask_and_speak start | 299: self._outstanding: dict[int, tuple[str, str]] = {} 360: await self._cancel_outstanding(before=10**9) 473: await self._cancel_outstanding(before=action.turn |
| 4 | Bash | Read cancel path, rest of ask_and_speak, outstanding registration, introduce, vad counter and config |  if not allowed or not code or code in ("au", "un"): # auto / unknown return "" return "" if code in allowed else code async def _cancel_outstanding(self, *, be |
| 5 | Bash | Read may_refine, preroll handling, publish, and turn-manager state rules | def may_refine(*, segments, probable: bool, refine_on: bool, seconds: float, min_seconds: float, has_vector: bool) -> bool: """Whether this turn may be kept as  |
| 6 | Bash | Check turn-manager THINKING rules, tests, live config, git history, embedder shape |  def handle_vad(self, event: VadEvent) -> list[Action]: if self.state in (IDLE, ERROR): return [] if self.state == LISTENING: if event.kind == "speech_start": r |
| 7 | Bash | Check tests, live config, git history, embedder, and the mic loop shape | simorgh/voice/config.py simorgh/voice/session.py ---- tests/simorgh/voice/test_a_voice_is_enrolled_once.py:70: self.assertIn("_last_pcm = bytes(pcm)", inspect.g |
| 8 | Bash | Check STT serialisation, barge-in policy derivation, thresholds and live voice config |  previous = self._stt_task if previous is not None and not previous.done(): # A transcription still waiting on the old queue would never # end: nothing feeds th |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The code facts check out: `_identify` writes `_last_speech_s/_last_pcm/_last_skip` on the session (session.py:712-716,725); ASK never cancels the previous `_ask_task` (session.py:473-474 only calls `_cancel_outstanding`, which publishes TASK_CANCEL to the Worker at :579-589 and touches no asyncio task); the turn manager deliberately opens a new turn while THINKING (turns.py:147-151 "speech while thinking"), so two `_ask_and_speak` coroutines do overlap by design; and `_only_a_voice_we_know` (session.py:655-706) has no memo and is re-entered on every frame because vad.py:548 grows `speech_ms` per frame and the judge is called inline from `_on_frame` (:392-393). But the finding overstates the harm on three of its four legs. (1) Introduction path: between `_identify` returning and `keep_take` at :1415 there is no await on the normal path (`_note_score`, sync command/TV checks, then `_introduce_step` calls `intro.feed` synchronously) -- the "read after later awaits" claim is false there. (2) Refine path: `may_refine(seconds=self._last_speech_s)` at :939-941 is guarded by `has_vector`, and `_identify` only returns a vector when that turn's own `_last_speech_s >= MIN_SECONDS` (:726-730, speakers.py:77 MIN_SECONDS=0.8) -- the same threshold `may_refine` applies. So an overwrite by a later turn can only suppress a legitimate refine, never admit a blended one; the "blended one family member into another" consequence does not follow for this path (the vector is a local, turn-correct). (3) Enrol path: the window is one bus publish (:830) plus one embed inside `_identify`; the overwriting turn arrives via `_ask_and_speak(N+1)` which, with `_enrolling` still set, is by construction another take of the SAME enrolling name (:823, :842). The realistic damage is a take filed with the next take's audio under the previous take's text/seconds -- a data-quality smudge within one person's enrolment, not cross-person blending. Reaching it needs two STT finals to land within sub-second of each other, which the STT serialisation at :425-433 (previous transcription cancelled on new capture) makes unlikely but not impossible under slow hearing. (4) Barge-in judge: genuinely unthrottled and inline, but `barge_in_known_voice` defaults False (config.py:88), has no live toggle (only config.py/session.py mention it), and the creator's live ~/.simorgh/simorgh.toml has `barge_in = false` outright, so the judge is dormant in the house today; when both are on it is a real per-frame CPU cost (one 1.2 s embedding per 30 ms frame, `_preroll` re-filled every frame at :406 so pcm-memo would not help). No test exercises `_only_a_voice_we_know` at all (grep hits only config.py and session.py; commit 4db7d38 is one day old), which is the more useful observation. On the lens question: this is category (c) genuine-but-small bugs, not architecture; the proportionate fix is a few lines (return `(pcm, seconds)` from `_identify` or key them by turn like `_audio`/`_named` already are; cache the barge verdict per candidate until `speech_end`). One part of the recommendation is actively wrong for this design: cancelling the previous `_ask_task` at ASK would regress the intentional superseded-turn behaviour (turns.py:211-215, `reply_ready` :228-236 "asked, then superseded, answered first: said now, late"), which is why `_cancel_outstanding` cancels the Worker's chat and not the coroutine.

### evidence

- simorgh/voice/session.py:707-737 `_identify` sets `self._last_speech_s`, `self._last_skip`, `self._last_pcm` then `await asyncio.to_thread(self._embedder.embed, ...)`; returns (None, None) unless `_last_speech_s >= MIN_SECONDS`
- simorgh/voice/speakers.py:77 `MIN_SECONDS = 0.8`; :79 `ENROLL_MIN_SECONDS = 1.5`
- simorgh/voice/session.py:131-140 `may_refine(... seconds >= min_seconds ...)` with `has_vector` -- a vector already implies the turn passed the same 0.8 s bar in `_identify`
- simorgh/voice/session.py:473-474 ASK: `await self._cancel_outstanding(before=action.turn_id)` then `self._ask_task = asyncio.create_task(...)` -- no cancel of the previous task
- simorgh/voice/session.py:579-589 `_cancel_outstanding` publishes `topics.TASK_CANCEL` to the Worker only
- simorgh/voice/turns.py:147-151 THINKING + speech_start -> `_new_turn("speech while thinking")`; turns.py:211-215 `_superseded` bookkeeping; turns.py:228-236 superseded turn answered first is still spoken late
- simorgh/voice/session.py:1409-1416 `_introduce_step`: `intro.feed(...)` is synchronous and `keep_take(intro.name, self._last_pcm, ...)` follows with no await since `_identify`
- simorgh/voice/session.py:816-843 `_enroll_take`: `await self._pipeline._publish(...)` at :830 precedes `keep_take(job["name"], self._last_pcm, ...)` at :842; `job` is the single `_enrolling` record, so any overlapping turn is a take of the same name
- simorgh/voice/session.py:425-433 CAPTURE_START cancels the previous `_stt_task` -- STT finals are serialised per capture
- simorgh/voice/session.py:392-393 `_only_a_voice_we_know` awaited inline in `_on_frame` when `before == AGENT_SPEAKING and event.kind in ("speech_start","speech")`; :677-703 gated only by `barge_in_known_voice`, `speech_ms >= barge_in_speech_ms`, embedder present; no cache
- simorgh/voice/session.py:405-406 `_preroll.append(frame)` on every non-USER_SPEAKING frame (deque maxlen `_PREROLL_FRAMES = 40`, :51), so the judged pcm changes each frame
- simorgh/voice/vad.py:545-552 `self._speech_ms += self._frame_ms` on every speech frame
- simorgh/voice/config.py:88 `barge_in_known_voice: bool = False`; config.py:76 `barge_in_speech_ms: int = 350`
- ~/.simorgh/simorgh.toml `[voice]` section: `barge_in = false` (line 2), no `barge_in_known_voice` key -- barge-in itself is off in the live house
- `grep -rln "_only_a_voice_we_know\|barge_in_known_voice\|barge_in_ignored" tests simorgh` -> only simorgh/voice/config.py and simorgh/voice/session.py: no test covers the judge
- tests/simorgh/voice/test_a_voice_is_enrolled_once.py:70 asserts `"_last_pcm = bytes(pcm)" in inspect.getsource(VoiceSession._identify)` -- a source-shape test, the only test touching these fields
- git log: 4db7d38 'Only a voice the house knows may cut Sim off' (the judge, one commit before e317076 'A turn's record carries its own speaker')

**severity adjustment:** lower

**corrected claim:** `_last_speech_s`, `_last_pcm`, `_last_skip` are session-level singletons written per turn in `_identify` (session.py:712-725) while overlapping `_ask_and_speak` coroutines are permitted by design (turns.py:147-151; ASK at session.py:473-474 cancels only the Worker's chat). The only reader with a real await between write and read is `_enroll_take` (bus publish at :830, `keep_take` at :842): under back-to-back STT finals a take can be filed with the next take's audio, but because `_enrolling` holds one name it is the same person's audio under the wrong text/length, not a cross-person blend. The `may_refine` read at :940 can only suppress a refine (the vector is turn-local and already passed the same 0.8 s bar in `_identify`), and the introduction path (:1415) has no await between write and read. Separately `_only_a_voice_we_know` (:655-706) re-embeds the 1.2 s pre-roll on every 30 ms frame, inline in the mic loop, for as long as an unknown sound is called speech over Sim's voice; it is off by default, `barge_in = false` in the live config, and has no test. Both are small implementation bugs (a per-turn return value from `_identify`; a per-candidate verdict cache), not architectural faults; cancelling the previous `_ask_task` would regress the intentional superseded-turn behaviour and should not be done.

