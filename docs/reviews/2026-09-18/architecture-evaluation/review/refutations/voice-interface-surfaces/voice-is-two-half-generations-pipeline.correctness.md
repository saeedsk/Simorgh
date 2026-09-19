# refute:correctness:Voice is two half-generations: Pipeline

*Workflow: review · Phase: Refute · Agent id: `accd8ae0bfcda8403` · Tool calls: 6*

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
    "title": "Voice is two half-generations: Pipeline still owns the plumbing VoiceSession runs on, AEC is dead in the live path, and barge-in is off in production",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "`VoiceSession` (the live loop) reaches into the legacy `Pipeline` 29 times for bus, ledger, lock and echo-memory, the default-on NLMS echo canceller is wired only into `Pipeline.run_loop` which `VoiceSession` never runs, and the live config disables barge-in entirely, so the EchoTracker, known-voice gate and stop-word paths cannot run while Sim speaks.",
    "evidence": [
      "`grep -c 'self._pipeline\\._' simorgh/voice/session.py` -> 29 (each marked `# noqa: SLF001`); voice/service.py:270-300 builds `Pipeline(...)` then `VoiceSession(pipeline=pipeline, microphone=pipeline._mic, recogniser=pipeline._stt, synthesiser=pipeline._tts, detector_factory=pipeline._detector_factory)`",
      "simorgh/voice/pipeline.py:465-503 is the only place `EchoCanceller`/`EchoCancellingDetector` are constructed (`if self._config.aec and _aec_available()`); `grep -n 'aec' simorgh/voice/session.py` -> no matches; voice/config.py:96 `aec: bool = True`; voice/README.md says '`aec.py`, off by default'",
      "~/.simorgh/simorgh.toml `[voice] barge_in = false`; turns.py:128-131 in AGENT_SPEAKING `if not self.policy.interrupt_on_user_speech: return []`, so no CAPTURE_START while Sim talks and session.py's `if self._player.playing and opens_with_stop(text)` can never be reached during playback",
      "Size and knobs: session.py 1,961 lines; `_ask_and_speak` 248 lines (session.py:887-1135); 39 distinct `self._config.*` knobs read in session.py out of 99 fields in voice/config.py; 127 awaits in session.py; 11 heuristic exits (`_courtesy_aside`, `_bystander`, `_continuation`, `_unplaced`, TV-audio, echo, repeat, who-said, identity-claim, whois, enrol) each ending in a direct `turns.state = LISTENING`"
    ],
    "why_it_matters": "The README and config describe a barge-in and echo-cancellation system that the running house does not have; the creator has, in effect, given up on interrupting Sim by voice after three approaches, and the code that would let him is unreachable or off. The addressed-to-Sim policy (is this for me?) is the real product logic of a room assistant and it is spread across ~1,000 lines of heuristics plus a prompt scaffold, with each rule bolted on after a live incident, which is why they keep contradicting each other (the docstrings at session.py:1040-1063 say so).",
    "recommendation": "(1) Finish the migration: move `_publish/_record/speech_lock/recent_said/_pending` into a ~150-line `VoiceBus` owned by VoiceSession and delete `Pipeline.run_loop`/`listen_once`; then either wire `EchoCanceller` into `VoiceSession._play`/`_on_frame` or delete aec.py and the flag. (2) Extract the addressed-to-Sim rules into one pure `addressing.decide(TurnFacts) -> Decision(answer|quiet(reason)|aside)` where `TurnFacts` is a frozen dataclass built once per turn (speaker, score, text, names_sim, sim_spoke_ago, tv_playing, room window, last_asked_speaker); the 11 exits become one call and one TurnManager transition, and the rules become a table you can test from the 842 kept turns. (3) Decide barge-in honestly: either fix the level gate on the laptop speakers with the kept audio or document that headphones/TV-output are required and remove the dead config.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check pipeline coupling, AEC wiring, config, and README claims | --- pipeline._ count 29 --- distinct attrs 1 self._pipeline._bus 27 self._pipeline._publish 1 self._pipeline._record --- wc 1961 simorgh/voice/session.py 596 si |
| 2 | Bash | Check pipeline attrs, AEC in pipeline, service wiring, turns policy | --- pipeline public attrs used by session 21 1002:self._pipeline.last_said 1 self._pipeline._bus 27 self._pipeline._publish 1 self._pipeline._record 1 self._pip |
| 3 | Bash | Check barge-in gating, function sizes, knob counts, heuristic exits, docstrings | --- interrupt_on_user_speech simorgh/voice/config.py:102: # `tts_speed`, `interrupt_on_user_speech` is `barge_in`, `end_of_turn_ simorgh/voice/session.py:253: i |
| 4 | Bash | Check AGENT_SPEAKING branch, stop-word reachability, prior review mentions | --- turns 146-162 return [] if self.state == THINKING: if event.kind == "speech_start": # The person went on before the answer came. The answer, # when it comes |
| 5 | Bash | Check frame handling during playback, stale turn guards, AEC wiring in pipeline | --- _on_frame 373-410 async def _on_frame(self, frame: bytes) -> None: assert self._vad is not None now = self._now() set_echo = getattr(self._detector, "set_ec |
| 6 | Bash | Check which pipeline method owns AEC and whether session reaches it | --- pipeline defs 276: async def listen_once(self, *, max_seconds: float \| None = None, respond: bool = True, 349: async def ask(self, text: str, *, session_id: |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core of the finding holds against the code today, with three precision corrections. (1) Coupling: `grep -c 'self\._pipeline\._' session.py` is 29, but those are 27x `_publish`, 1x `_bus`, 1x `_record` (bus/ledger only); the lock and echo-memory are reached through PUBLIC attributes (`speech_lock` x4, `recent_said` x4, `last_said` x6, `speaking` x5, `last_heard`, `ask`) — total ~50 references, so the dependency is if anything larger than stated, just not all via private access. (2) AEC dead in the live path: confirmed. `EchoCanceller`/`EchoCancellingDetector` are constructed only inside `Pipeline._play_stream_interruptibly` (pipeline.py:442-503); `VoiceSession` has its own `_play` (session.py:1915-1928) on `self._player.play_stream` and never calls that method; `grep -n aec session.py` returns nothing. service.py:290-303 uses VoiceSession whenever the mic has `stream` (both real mics in audio.py:112,187 do), so `run_loop` is only the fallback. AEC is still reachable via `pipeline.speak()` (service.py:736, when no session) — a nuance, not a refutation. README.md:29 says "off by default" while config.py:96 has `aec: bool = True` — the contradiction is real. (3) Barge-in off in production: `~/.simorgh/simorgh.toml` line 2 `barge_in = false`; session.py:253 maps it to `interrupt_on_user_speech`; the gate is turns.py:153-155 (the finding cites 128-131, which is `_new_turn`; wrong line, right code). Overstatement: the EchoTracker (`_on_frame` session.py:378-386) and the known-voice gate (`_only_a_voice_we_know`, session.py:390) DO execute while Sim speaks — their results are simply discarded because `handle_vad` returns [] in AGENT_SPEAKING. Also, "stop-word can never be reached during playback" is nearly but not strictly true: turns.py:148-151 opens a new turn on speech while THINKING, so a later turn's final text could arrive while the earlier answer plays; a rare edge. Sizes verified: session.py 1961 lines, `_ask_and_speak` 887-1135 (248 lines), 39 distinct `self._config.*` knobs, 101 (not 99) annotated Config fields, 127 awaits, 15 direct `state = LISTENING` assignments, four named heuristic exits at 545/1182/1232/1261. The 2026-09-1x incident docstrings at session.py:1036-1063 read as quoted. Not in the known-findings list: `grep -i 'barge|aec'` over architecture-audit-2026.md, architecture-review-2026-09-18.html and the third-opinion doc returns nothing. Classification "right-design-undermined" is apt; severity medium is proportionate for a one-family laptop assistant.

### evidence

- `grep -o 'self\._pipeline\.[a-zA-Z_]*' simorgh/voice/session.py | sort | uniq -c` -> 1 _bus, 27 _publish, 1 _record, 1 ask, 1 last_heard, 6 last_said, 4 recent_said, 5 speaking, 4 speech_lock
- simorgh/voice/service.py:270-303: builds `Pipeline(...)`, then if `hasattr(mic, 'stream')` builds `VoiceSession(pipeline=pipeline, microphone=pipeline._mic, recogniser=pipeline._stt, synthesiser=pipeline._tts, detector_factory=pipeline._detector_factory)`; else `pipeline.run_loop`
- simorgh/voice/pipeline.py:442 `_play_stream_interruptibly`, 465-475 `if self._config.aec and _aec_available(): ... EchoCanceller(...); EchoCancellingDetector(...)`, 503 `feed = _feed_reference if ...`; only construction site (grep over simorgh/voice)
- `grep -n 'aec\|EchoCancel' simorgh/voice/session.py` -> no output; session.py:1915-1928 `_play` uses `self._player.play_stream(..., on_play=_reference)` (EchoTracker reference, not AEC)
- simorgh/voice/config.py:96 `aec: bool = True`; simorgh/voice/README.md:29 'Echo cancellation (`aec.py`, off by default, `voice barge aec on`)'
- ~/.simorgh/simorgh.toml:1-2 `[voice]` / `barge_in = false`; session.py:253 `interrupt_on_user_speech=config.barge_in`; turns.py:153-155 `if self.state == AGENT_SPEAKING: if not self.policy.interrupt_on_user_speech: return []` (finding's cited 128-131 is `_new_turn`, wrong line)
- session.py:378-391: `_echo.observe`/`set_echo` and `_only_a_voice_we_know(event)` run in AGENT_SPEAKING before `handle_vad` discards the event — the gates execute, their effect is inert
- session.py:1014 `if self._player.playing and opens_with_stop(text)` sits inside `_ask_and_speak` (defs at 887 and 1135; 248 lines); turns.py:148-151 'speech while thinking' is the one path that can open a turn that finishes during playback
- `wc -l simorgh/voice/session.py` -> 1961; `grep -o 'self\._config\.[a-zA-Z_]*' | sort -u | wc -l` -> 39; ast count of Config AnnAssign -> 101; `grep -c 'await '` -> 127; `grep -c 'state = LISTENING'` -> 15
- session.py:1036-1063 docstrings cite live incidents dated 2026-09-13/14 for `_take_correction`, `_courtesy_aside`, `_background`, `_continuation`, `_unplaced`, `min_confidence`
- `grep -in 'barge\|aec\|echo cancel' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md` -> no matches (not in known list)

**corrected claim:** VoiceSession (the live loop, used whenever the mic has `stream`, i.e. every real mic) references the legacy Pipeline ~50 times: 29 through private members (27 `_publish`, `_bus`, `_record`) and ~20 through public state (`speech_lock`, `recent_said`, `last_said`, `speaking`, `last_heard`, `ask`). The NLMS echo canceller is constructed only in `Pipeline._play_stream_interruptibly` (pipeline.py:442-503), which VoiceSession never calls (it plays through its own `_play`, session.py:1915); AEC is therefore dead in the live loop, reachable only via `pipeline.speak()`/`run_loop` fallbacks, while config.py:96 defaults it on and README.md:29 says off. The live toml sets `barge_in = false`, so turns.py:153-155 discards every speech event during AGENT_SPEAKING; the EchoTracker and known-voice gate (session.py:378-391) still execute but their output is inert, and the stop-word path (session.py:1014) is reachable during playback only through the rare 'speech while thinking' turn (turns.py:148-151).

**severity adjustment:** keep

