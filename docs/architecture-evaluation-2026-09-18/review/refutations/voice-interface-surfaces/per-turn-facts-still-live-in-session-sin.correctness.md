# refute:correctness:Per-turn facts still live in session sin

*Workflow: review · Phase: Refute · Agent id: `ad8673765dc169545` · Tool calls: 7*

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
| 1 | Bash | Locate cited symbols in voice session |  1961 simorgh/voice/session.py 577 simorgh/voice/vad.py 353 simorgh/voice/config.py 2891 total 55:class TurnClock: 131:def may_refine(*, segments, probable: boo |
| 2 | Bash | Read TurnClock, frame loop, ASK dispatch, judge and identify | class TurnClock: turn_id: int speech_start: float = 0.0 speech_end: float = 0.0 final_at: float = 0.0 reply_at: float = 0.0 first_audio_at: float = 0.0 # when t |
| 3 | Bash | Read cancel path, ask/enroll/attribute and intro paths, git history | 360: await self._cancel_outstanding(before=10**9) 473: await self._cancel_outstanding(before=action.turn_id) 579: async def _cancel_outstanding(self, *, before: |
| 4 | Bash | Read rest of ask path, guards, VAD speech counter, config, toml, memory and known findings | ----ask-rest note = slow_hearing_note(clock.final_at - clock.speech_end) if note: # beside the speaker note, never instead of it who["speaker_note"] = (who["spe |
| 5 | Bash | Read guard, ask tail, preroll fill, and turn manager ASK emission | ----guarded async def _guarded(self, coro) -> None: """A task's exception is nobody's unless somebody looks: a turn that fails while answering is logged and the |
| 6 | Bash | Check mic loop, frame size, live toml, known-voice usage and publish yielding | ----micloop self._log("warning", "voice.warmup_failed", error=repr(exc)) try: warm_stt = getattr(self._stt, "warmup", None) if callable(warm_stt): self.stats.wa |
| 7 | Bash | Find where the known-voice gate is referenced and whether barge_in off makes it moot | simorgh/voice/config.py:88: barge_in_known_voice: bool = False ---- 2026-09-17 18:47:39 -0700 52: barge_in_speech_ms: int = 650 156: if event.kind in ("speech_s |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The code shape is as claimed on both counts, but the finding overstates live impact on both.

(1) Per-turn singletons: confirmed. simorgh/voice/session.py:712-716,725 set self._last_speech_s / _last_skip / _last_pcm inside _identify(turn_id); _identify itself then awaits asyncio.to_thread(embed) (line 732) before returning, so even the introduction path (1415-1416, no await of its own between set and read) can observe another turn's values. _ask_and_speak reads _last_speech_s at :940 after `await self._attribute(...)` (:927, a to_thread diarisation when diarize=True, the default at config.py:246, and the turn >= 3.5 s); _enroll_take reads _last_pcm at :842-843 after `await self._pipeline._publish(...)` (:830), which is a real bus await (pipeline.py:565-566). Overlap of two _ask_and_speak coroutines is real and by design: the ASK branch (session.py:473-474, not :465 as cited) calls _cancel_outstanding, which only publishes TASK_CANCEL to the worker (:579-589) and never cancels the asyncio task; _ask_and_speak awaits self._pipeline.ask inline (~:1094), and turns.py:211-215 explicitly supersedes an asked turn with a new ASK. However, every read of the _last_* values sits BEFORE the long _pipeline.ask await, so the race window is only the embed/diarise/publish stretch of the previous turn, not the whole model wait. The "why it matters" also over-reaches: the creator's own memory (project_per_turn_facts_in_session_state.md) records that "the overlapping-turn theory here was wrong and one query killed it" for the speaker="" bug, and the earlier cross-family blending (0.68 vs father, 2026-09-13) is attributed in code comments (:397-401) to capturing Sim's own prompt and room silence, not to this race. So this is a latent race in the enrolment/refinement paths, not a demonstrated cause of the past incident.

(2) Unthrottled known-voice judge: confirmed as code. _only_a_voice_we_know (:655-706) is gated only by the flag, speech_ms >= barge_in_speech_ms and embedder presence; vad.py:548/556 keep incrementing _speech_ms on every speech/hangover frame, a downgraded event ("silence") leaves the state AGENT_SPEAKING so the gate at :390-391 fires again on the next frame, and _on_frame is awaited inline from the mic loop (:353), so each 30 ms frame pays a to_thread embedding of the sliding 1.2 s preroll. But it is dormant: config.py:88 defaults barge_in_known_voice=False; repo-wide grep finds no other file setting it; and ~/.simorgh/simorgh.toml has `barge_in = false`, which disables interruption entirely (turns.py:156 only treats speech during AGENT_SPEAKING as barge-in under that policy). The claim "which is when the creator enables it" has no evidence in code, config, or docs.

Not in the known-findings list; the memory names last_speaker/last_identification/recent_said/last_said, not these three attributes nor the judge. Materially new, but a lower severity than medium: a narrow-window race in a rarely-run path plus a perf bug in a feature that is off in the live config.

### evidence

- simorgh/voice/session.py:712-716,725 -- _identify sets self._last_speech_s, self._last_skip, self._last_pcm; :732 awaits asyncio.to_thread(self._embedder.embed, ...) before returning
- simorgh/voice/session.py:927 `segments = await self._attribute(turn_id, identification)` then :939-940 `may_refine(..., seconds=self._last_speech_s, ...)`; _attribute at :793-814 does `await asyncio.to_thread(attribute, ...)` when diarize is on (config.py:246 `diarize: bool = True`, :247 diarize_min_s = 3.5)
- simorgh/voice/session.py:830 `await self._pipeline._publish(topics.VOICE_TRANSCRIPT, ...)` precedes :842-843 `self._speakers.keep_take(job["name"], self._last_pcm, ..., seconds=getattr(self, "_last_speech_s", 0.0), source="enroll")`; pipeline.py:565-566 `_publish` is `await self._bus.publish(...)`
- simorgh/voice/session.py:1415-1416 introduction path `self._speakers.keep_take(intro.name, self._last_pcm, ..., seconds=getattr(self, "_last_speech_s", 0.0), source="introduce")`
- simorgh/voice/session.py:473-474 (claim cited :465) `await self._cancel_outstanding(before=action.turn_id)` then `self._ask_task = asyncio.create_task(self._guarded(self._ask_and_speak(...)))` -- no .cancel() of the previous task; :579-589 _cancel_outstanding only publishes topics.TASK_CANCEL
- simorgh/voice/session.py:1084 `self._outstanding[turn_id] = (session_id, text)` and ~:1094 `reply = await self._pipeline.ask(...)` -- the model wait is inline in _ask_and_speak, so two turns' coroutines do overlap; turns.py:211-215 `_superseded = self._asked_turn` supports a second ASK while one is outstanding
- simorgh/voice/session.py:655-706 _only_a_voice_we_know: gates at :677 (flag), :679 (speech_ms), :681 (embedder/voices); :693 `await asyncio.to_thread(self._embedder.embed, samples, 16000)` every call; :706 `return replace(event, kind="silence")` leaves turns.state AGENT_SPEAKING so :390-391 re-enters next frame
- simorgh/voice/vad.py:548 and :556 `self._speech_ms += self._frame_ms` (frame_ms default 30, vad.py:199) -- counter keeps growing across frames; reset only on speech_end (:561-564)
- simorgh/voice/session.py:349-353 `async for frame in stream: ... await self._on_frame(frame)` -- the judge's await is inline in the mic loop
- simorgh/voice/config.py:88 `barge_in_known_voice: bool = False`; `grep -rn barge_in_known_voice` over *.py/*.md/*.toml/*.sh hits only config.py:88 and session.py -- nothing enables it
- ~/.simorgh/simorgh.toml [voice]: `barge_in = false` (and no barge_in_known_voice key); turns.py:156 gates interruption on the barge-in policy, so the known-voice judge is doubly dormant in the live config
- ~/.claude/projects/-Users-saeed-ws-Simorgh/memory/project_per_turn_facts_in_session_state.md: names last_speaker/last_identification/recent_said/last_said (not _last_pcm/_last_speech_s/_last_skip) and states 'the overlapping-turn theory here was wrong and one query killed it'
- git status --short simorgh/voice/ is clean; git log shows session.py last touched by 6bd5229 / e317076 (2026-09-18), so the read code is current

**severity adjustment:** lower

**corrected claim:** `_last_speech_s`, `_last_pcm` and `_last_skip` are still session-level attributes set per turn in `_identify` (session.py:712-716,725) and read after awaits by `_ask_and_speak` (:940, after `_attribute`'s diarisation), `_enroll_take` (:842-843, after a bus publish at :830) and `_introduce_step` (:1415-1416, after `_identify`'s own embed await). Two turns' `_ask_and_speak` coroutines can overlap because the model wait is inline and ASK (:473-474) only cancels the worker chat, not the asyncio task, but all reads precede the model wait, so the race window is the embed/diarise/publish stretch of the previous turn, not the whole reply, and there is no evidence it has fired live (the creator measured the overlapping-turn theory as wrong for the 2026-09-18 speaker="" bug, and the 2026-09-13 blending was caused by capturing Sim's prompt). Separately, `_only_a_voice_we_know` (:655-706) re-runs a preroll embedding on every 30 ms speech frame while the sound continues (vad.py:548/556 keep `speech_ms` growing; a downgraded event leaves the state AGENT_SPEAKING; the await is inline in the mic loop at :353), but the feature is off by default (config.py:88), nothing in the repo turns it on, and the live simorgh.toml has `barge_in = false`, so it is a latent performance bug in a dormant feature rather than a live one.

