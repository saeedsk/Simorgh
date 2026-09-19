# refute:correctness:Language is detected twice and consumed

*Workflow: review · Phase: Refute · Agent id: `a20f78c4add99abff` · Tool calls: 4*

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
    "title": "Language is detected twice and consumed by nobody who could act on it",
    "kind": "missing",
    "severity": "low",
    "claim": "Whisper's language code is now recorded on the turn (the 2026-09-18 fix) and `lang.language_of` decides Farsi-vs-English from the reply's script for TTS, but neither value reaches the model, the percept, the STT hint for the next turn, or a per-person preference.",
    "evidence": [
      "simorgh/voice/session.py:625 `clock.language = event.language or \"\"`; :1893 `language=clock.language` only into the `voice:turns` record",
      "simorgh/voice/pipeline.py:349-366 `ask(...)` payload: channel, text, session_id, device, confidence, speaker, speaker_relation, speaker_before, room; no language field; contracts/messages/percept.py:11-28 has no `language` field",
      "simorgh/voice/lang.py:24-33 `language_of` is a script-majority test used by the planner/backchannel/TTS routing; `_transcribe` passes the static `self._config.stt_language` (session.py:601-602) every turn",
      "session.py:1040-1063 `_LANGUAGE_CODES`: nine Persian turns were discarded in half an hour on 2026-09-17 because of a code/name mismatch, i.e. this path is fragile and unobserved"
    ],
    "why_it_matters": "A bilingual house is the stated use case; the cheapest wins (bias the next turn's STT to the language this speaker used last, tell the model which language was heard so it answers in kind) need the value to travel one hop further than it does.",
    "recommendation": "Add `language` to the percept payload and to the Conversation/identity contract; keep a per-person `last_language` in the speaker book and pass it as the STT hint for that speaker's next turn; let scaffolds.who_is_here mention it.",
    "confidence": 0.7
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited session.py regions |  if frame is _END: return yield frame async def _transcribe(self, turn_id: int, queue: asyncio.Queue) -> None: try: async for event in self._stt.start_stream(se |
| 2 | Bash | Grep language usage across voice and orchestration | 37:from .lang import language_of 72: language: str = "" 146:#: Persian -- one of this house's own two languages -- was thrown away as 147:#: foreign, unheard, l |
| 3 | Bash | Check Context, language flow, scaffolds, speaker book | Exit code 1 return bool(has_vector and refine_on and not segments and not probable and seconds >= min_seconds) #: Whisper answers with a code ("fa") or with a n |
| 4 | Bash | Check speaker book, orchestration consumers, STT hint config | __init__.py __pycache__ aec.py api.py audio.py backchannel.py bench.py commands.py config.py delivery.py diarize.py fakes.py health.py introduce.py lang.py pipe |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The core claim holds against today's code. Whisper's language code lands on the turn clock (session.py:625 `clock.language = event.language or ""`), is written into the audio-keep sidecar JSON (session.py:786) and the `voice:turns` ledger record (session.py:1863 -> pipeline.py:579), and is used once as a gate (`_other_language`, session.py:570-574, discards turns not in `stt_languages`). It goes nowhere else: `VoiceService.ask()` (pipeline.py:349-366) builds the percept payload with channel/text/session_id/device/confidence/speaker/speaker_relation/speaker_before/room and no language; `PerceptTextReceived` (contracts/messages/percept.py:10-28) declares no `language` field; a grep for `language` across simorgh/orchestration, kernel, persona, worldmodel and interface returns nothing; simorgh/voice/speakers.py has no language at all; and both STT call sites pass the static `self._config.stt_language` (session.py:601-602, pipeline.py:304), whose default is "" (config.py:35), i.e. whisper auto-detects fresh every turn with no per-speaker or last-turn bias. This is not in the known-findings list (the STT item there is about latency, not language). Two corrections to the finding's evidence, neither fatal: (1) the `_LANGUAGE_CODES` table is at session.py:148-158 (with `_language_code` at :161), not :1040-1063; (2) `language_of(text)` is computed on the USER's transcript (session.py:1081) and passed into the planner `Context.language` (session.py:1127; planner.py:42 "the user's, when known; '' = judge from the reply"), so the script-derived value does reach TTS routing and backchannels via the user's text, not only "the reply's script". The 2026-09-17 nine-discarded-turns incident is history: the code/name mismatch is fixed by the table (comment at :143-149), so "fragile and unobserved" describes the past, though the gate is still a hard discard with only a log line. One softening of "why it matters": scaffolds.py:540 already instructs "Answer in the language the person spoke" and the model sees the Farsi script in the transcript itself, so telling the model the heard language is a minor gain; the real unclaimed win is the per-speaker STT hint, which the code confirms does not exist. Severity low is right; keep.

### evidence

- simorgh/voice/session.py:625 `clock.language = event.language or ""` -- only assignment of whisper's language onto the turn
- simorgh/voice/session.py:1863 `language=clock.language` into VoiceTurn; simorgh/voice/pipeline.py:579 `**({"language": turn.language} if turn.language else {})` into the voice:turns ledger event
- simorgh/voice/session.py:786 `"language": getattr(event, "language", "") or ""` written to the keep_audio sidecar JSON
- simorgh/voice/session.py:570-574 `_other_language` uses the code only as a discard gate against `stt_languages`
- simorgh/voice/pipeline.py:356-364 `ask()` payload keys: channel, text, session_id, device, confidence, speaker, speaker_relation, speaker_before, room -- no language
- simorgh/contracts/messages/percept.py:10-28 PerceptTextReceived fields: channel, text, session_id, user_id, command, steer, device, speaker, confidence, speaker_relation, room -- no language
- grep -rn '"language"|.language|language=' simorgh/orchestration simorgh/kernel simorgh/persona simorgh/worldmodel simorgh/interface -> no output
- grep -n language simorgh/voice/speakers.py -> no output (no per-person language in the speaker book)
- simorgh/voice/session.py:601-602 and simorgh/voice/pipeline.py:304 pass static `self._config.stt_language`; simorgh/voice/config.py:35 `stt_language: str = ""` (auto-detect every turn); ~/.simorgh/simorgh.toml sets no stt_language
- simorgh/voice/session.py:1081,1127 `language = language_of(text)` on the user's transcript -> `Context(user_text=text, language=language, ...)`; simorgh/voice/planner.py:42 `language: str = ""  # the user's, when known; "" = judge from the reply` (correction: script detection runs on the user text too, not only the reply)
- simorgh/voice/session.py:143-161 `_LANGUAGE_CODES` / `_language_code` with the comment 'live 2026-09-17: nine turns discarded in half an hour' -- the finding cites this at :1040-1063, which is the identity-claim/courtesy region; the incident is fixed by this table today
- simorgh/orchestration/scaffolds.py:540 'Answer in the language the person spoke.' -- the model is already told to answer in kind from the transcript's script, weakening the 'tell the model which language was heard' half of why-it-matters

**severity adjustment:** keep

**corrected claim:** Whisper's language code is recorded on the turn (session.py:625) and reaches only the voice:turns ledger record, the keep_audio sidecar, and the `_other_language` discard gate; the script-majority `lang.language_of` runs on the user's transcript (session.py:1081) and feeds the TTS planner Context and backchannels. Neither value reaches the percept payload (pipeline.py:349-366; percept.py has no `language` field), the orchestration/model side (no consumer in orchestration/kernel/persona/worldmodel), the speaker book (speakers.py has no language), or the next turn's STT hint, which is the static `stt_language` config defaulting to "" (auto-detect) at both call sites. The model can still answer in kind because it sees the script and scaffolds.py:540 tells it to; the concrete unclaimed win is a per-speaker/last-turn STT language bias. The 2026-09-17 nine-discarded-turns bug is fixed by `_LANGUAGE_CODES` (session.py:148-161, not :1040-1063).

