# refute:proportionality:Language is detected twice and consumed

*Workflow: review · Phase: Refute · Agent id: `a2d1efd56c0296341` · Tool calls: 6*

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
| 2 | Bash | Read pipeline ask payload, percept contract, lang.py, and grep language usage |  self.turns += 1 await self._record(VoiceTurn( session_id=session_id, device=self._config.device, speaker=speaker_name, heard=utterance.text, confidence=utteran |
| 3 | Bash | Trace where heard language flows after transcription |  "hungarian": "hu", "czech": "cs", "romanian": "ro", "ukrainian": "uk", "vietnamese": "vi", "thai": "th", "indonesian": "id", "malay": "ms", "bengali": "bn", "p |
| 4 | Bash | Check STT hint config, speaker book fields, and model-side language handling | simorgh/voice/settings.py:83: ("Hearing the words", ("stt", "stt_stream_model", "stt_language", "stt_languages", "min_confidence")), simorgh/voice/config.py:35: |
| 5 | Bash | Read STT auto comment, who_is_here scaffold, model-side language mentions, and fix commit |  return FakeRecogniser(config.fake_transcript), "" # The server before the CLI: same model, same words, 2.5 s less per # turn (whisper_server.py has the measure |
| 6 | Bash | Confirm model prompt line, the 2026-09-17 incident history, whisper auto default, and contract strictness | space, then the words. It shapes how you sound and is never spoken. Choose it from the moment, not from habit: warm for a hurt, a worry, a kindness; bright for  |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** Whisper's detected language code is recorded on the turn (session.py:625, :1863) and in the kept-audio sidecar (:786) but travels no further: the percept contract has no `language` field (contracts/messages/percept.py:11-28), `pipeline.ask` sends none (pipeline.py:356-365), and `Person` in the speaker book has no language field (speakers.py:155-165). However, the model is NOT blind to language: it receives the transcript text itself and the voice scaffold already instructs "Answer in the language the person spoke" (orchestration/scaffolds.py:540); and `language_of(text)` at session.py:1081 IS computed from the heard text and consumed by the backchannel/still-thinking/planner path. STT is not statically biased either: `stt_language` defaults to "" (voice/config.py:35), which whisper_cli.py:164 and faster_whisper.py:20 turn into auto-detect per turn; ~/.simorgh/simorgh.toml sets no override. The "nine Persian turns discarded" incident is historical: `_language_code` (session.py:161) with a name-to-code map now normalises whisper's output. The creator's own commit 6bd5229 states "Nothing behavioural changed. This is the discriminator the language router will need", i.e. the finding restates a planned next step rather than an oversight.

**reasoning:** Verified against code: the language code really does stop at the turn record and sidecar; percept payload and contract lack a language field; speaker book has none. So the "does not travel further" part is accurate. But three of the four evidence lines are overstated or historical. (1) "neither value reaches the model": the model gets the transcript in the language's script plus an explicit prompt rule at scaffolds.py:540 to answer in the language spoken, so the intended behaviour (answer in kind) already exists; an explicit code adds little because in the real failure mode (Farsi decoded as English nonsense) whisper reports "en" anyway. (2) "consumed by nobody": session.py:1081 computes language_of(heard text) and feeds Context(language=...) at :1127, the still-thinking ack at :1082 and backchannel at :1454/:1697; that is a consumer acting on the heard language. (3) "static stt_language every turn": the default is "" which both whisper backends map to auto, so each turn is already language-adaptive; the recommended sticky per-speaker hint would actively hurt the documented code-switching case (session.py:1045-1055 comment: the creator talking Farsi to a guest across the room and English to Sim), and the stt/__init__.py:27-29 comment shows the creator already guards Farsi understanding deliberately. (4) The 2026-09-17 discard incident is fixed by _language_code at :161. Scale lens: adding one optional field to the percept is cheap (a one-line contract change), but it would not fix the real bilingual failure and the creator's own commit message shows it is a known, deliberately deferred step. Not an architectural problem; at most a small follow-through item.

### evidence

- simorgh/voice/session.py:625 `clock.language = event.language or ""`; :1863 `language=clock.language` into VoiceTurn; :786 language written to kept-audio sidecar -- confirmed, value goes no further
- simorgh/voice/pipeline.py:356-365 ask() payload keys: channel,text,session_id,device,confidence,speaker,speaker_relation,speaker_before,room -- no language; simorgh/contracts/messages/percept.py:11-28 PerceptTextReceived has no language field -- confirmed
- simorgh/voice/speakers.py:155-165 `class Person` fields: name, relation, say_as, embeddings, enrolled_at, last_heard, heard -- no language -- confirmed
- simorgh/orchestration/scaffolds.py:540 `Answer in the language the person spoke.` -- the model already carries the rule; it infers language from the transcript text it receives
- simorgh/voice/session.py:1081 `language = language_of(text)` (heard text) -> :1082 _still_thinking(turn_id, language), :1127 Context(user_text=text, language=language, ...) -- the heard language IS consumed by the voice side
- simorgh/voice/config.py:35 `stt_language: str = ""`; simorgh/voice/stt/whisper_cli.py:164 `self._language = config.stt_language or "auto"`; faster_whisper.py:20 `config.stt_language or None`; `grep -n stt_lang ~/.simorgh/simorgh.toml` -> no output -- STT auto-detects every turn, not statically biased
- simorgh/voice/session.py:161-166 `_language_code` maps whisper names to codes via _LANGUAGE_CODES -- the 2026-09-17 code/name mismatch is fixed, historical
- git log -1 6bd5229: 'Nothing behavioural changed. This is the discriminator the language router will need' -- the creator planned the next hop explicitly
- simorgh/voice/session.py:1045-1055 comment: creator and a guest talking Farsi across the room while turns to Sim are English -- a sticky per-speaker STT hint would mis-decode this documented code-switching case
- simorgh/voice/stt/__init__.py:27-29: sherpa excluded from auto because 'Auto must not quietly stop understanding Farsi' -- bilingual hearing is already a guarded design concern

**severity adjustment:** lower

