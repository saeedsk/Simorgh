# refute:proportionality:Voice is two half-generations: Pipeline

*Workflow: review · Phase: Refute · Agent id: `aa07000ef1579f535` · Tool calls: 8*

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
| 1 | Bash | Verify counts and grep evidence for voice finding | 29 1961 simorgh/voice/session.py 596 simorgh/voice/pipeline.py 353 simorgh/voice/config.py 182 simorgh/voice/aec.py 272 simorgh/voice/turns.py 3364 total ---aec |
| 2 | Bash | Read cited service, pipeline, turns and session lines |  if cfg.speaker == "fake": from .fakes import FakeSpeaker spk = FakeSpeaker() else: from .audio import open_speaker spk, why = open_speaker(cfg.speaker) if spk  |
| 3 | Bash | Read turns state machine and session barge-in paths | 33:AGENT_SPEAKING = "agent_speaking" 36:STATES = (IDLE, LISTENING, USER_SPEAKING, THINKING, AGENT_SPEAKING, INTERRUPTED, ERROR) 49: interrupt_on_user_speech: bo |
| 4 | Bash | Read frame handling and echo tracker usage in session | =====turns 230-270 # Asked, then superseded, answered first: said now, late; # the newer turn's answer follows. self._superseded = 0 self._late_playing = True s |
| 5 | Bash | Check mic classes, live config, aec toggle, run_loop callers and size metrics | =====mics with stream simorgh/voice/fakes.py:26:class FakeMicrophone: simorgh/voice/fakes.py:51: async def stream(self, *, max_seconds: float = 0.0): simorgh/vo |
| 6 | Bash | Check run_loop callers, aec toggle handler, contradiction docstring, pipeline attribute usage | =====run_loop/listen_once callers simorgh/voice/service.py:303: self._loop_task = asyncio.create_task(pipeline.run_loop(self._loop_stop), name="voice-loop") sim |
| 7 | Bash | Check whether live barge-in toggle reaches the session and what tests cover | =====service _session refs 152: self._session = None 295: self._session = VoiceSession( 301: self._loop_task = asyncio.create_task(self._session.run(self._loop_ |
| 8 | Bash | Check remaining session references in service and barge-in test coverage | =====service 318,330 def _state(self) -> dict: p = self._pipeline session = self._session listening = bool(p and p.listening and not self._muted) turns = p.turn |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core thesis survives and is stronger than stated in one respect, but three of the mechanistic sub-claims are overstated or wrong.

CONFIRMED: (a) VoiceSession reaches into Pipeline 29 times (27 `_publish`, plus `_record`, `_bus`, `speech_lock`, `recent_said`, `last_said`, `speaking`, `ask`); service.py:270-301 builds Pipeline then hands its private engines to VoiceSession. (b) AEC is dead in the live path: `EchoCanceller` is constructed only in pipeline.py:465-475 inside the `_speak` path that `run_loop` uses; session.py has zero references to `aec`; every shipped microphone (SounddeviceMicrophone audio.py:112, FfmpegMicrophone audio.py:187, FakeMicrophone fakes.py:51) has `stream`, so the `run_loop` fallback at service.py:303 is unreachable in practice. config.py:96 says `aec: bool = True` while voice/README.md:29 says "off by default" -- a documentation/code contradiction. (c) Live toml has `barge_in = false`; turns.py:153-155 returns [] in AGENT_SPEAKING when `interrupt_on_user_speech` is false. (d) Size numbers check out: 1,961 lines, `_ask_and_speak` 887-1135 = 248 lines, 127 awaits, 39 distinct `self._config.*` knobs, 15 direct `self.turns.state = LISTENING` assignments.

MATERIALLY NEW (strengthens the finding): the live `voice barge on|off` and `aec on|off` commands (service.py:380-396) update `self.config` and `self._pipeline._config` but never `self._session._config`, unlike the `_set` path at service.py:543-550 which does push into the session. And even if they did, the TurnManager `Policy` is a frozen dataclass built once at session.py:250-254 with `interrupt_on_user_speech=config.barge_in`, so the running session cannot pick up a barge-in toggle at all. The test that claims to cover this, `test_barge_off_then_on_flips_the_live_config` (test_barge_in.py:411), builds a `Pipeline` (line 460), i.e. it tests the dead path. That is exactly the "two half-generations" shape: tests and toggles exercise Pipeline, production runs VoiceSession.

OVERSTATED / WRONG: (1) "EchoTracker ... cannot run while Sim speaks" is false: session.py:376-388 feeds EchoTracker on every frame whenever playback is active regardless of `barge_in`, sets the detector's echo bar, and gates speaker-audio keeping (line 402). What barge_in=false disables is only the turn-start transition. (2) The known-voice gate is off by its own default (`barge_in_known_voice: bool = False`, config.py:88; not set in toml), independent of barge_in -- not a consequence of it. (3) "the stop-word path can never be reached during playback" is too absolute: session.py:1014 is reachable whenever the turn began before playback started -- e.g. the backchannel ack playing while state is USER_SPEAKING (turns.py:252-254 only transitions THINKING->AGENT_SPEAKING on playback start), or "speech while thinking" (turns.py:146-150), or a late reply. (4) Recommendation to delete `listen_once` is wrong: service.py:655 uses it live for one-shot listening; only `run_loop` is effectively dead. (5) Cited line turns.py:128-131 is `_new_turn`; the actual check is turns.py:153-155.

LENS (scale/proportion): calling the Pipeline/VoiceSession split "architecture" is a stretch for one laptop -- it is 29 call sites, 27 of them one method, and a VoiceBus extraction is a half-day job, not a redesign. But the concrete consequences are not cosmetic: a default-on flag that does nothing, a README saying the opposite, a live toggle that reports success and changes nothing, and a barge-in test suite that exercises the path production does not run. Those breach the project's own honesty rule (a tool must never succeed while saying nothing true) and are cheap to fix. Recommendation (2), the addressing-rule table, is the larger lift and its payoff is plausible but not verifiable from the code; recommendation (3) is a decision, not work. Severity stays medium: right design, undermined implementation, plus one genuine bug (toggles not reaching the session).

### evidence

- grep -c 'self._pipeline\._' simorgh/voice/session.py -> 29; per attribute: 27 _publish, 6 last_said, 5 speaking, 4 speech_lock, 4 recent_said, 1 last_heard, 1 ask, 1 _record, 1 _bus
- simorgh/voice/service.py:270-301: `self._pipeline = Pipeline(...)`; `VoiceSession(pipeline=pipeline, ..., microphone=mic, recogniser=pipeline._stt, synthesiser=pipeline._tts, detector_factory=pipeline._detector_factory)`; line 303 `pipeline.run_loop` only when mic lacks `stream`
- simorgh/voice/audio.py:112 and :187, simorgh/voice/fakes.py:51: all three microphone classes define `async def stream` -> run_loop fallback unreachable with any shipped mic
- simorgh/voice/pipeline.py:465-475: `if self._config.aec and _aec_available(): ... EchoCanceller(taps=..., mu=...); EchoCancellingDetector(...)` -- only construction site; `grep -n aec simorgh/voice/session.py` -> no output
- simorgh/voice/config.py:96 `aec: bool = True`; simorgh/voice/README.md:29 'Echo cancellation (`aec.py`, off by default, `voice barge aec on`)'
- ~/.simorgh/simorgh.toml [voice]: `barge_in = false`, no `aec` key, no `barge_in_known_voice` key
- simorgh/voice/turns.py:153-155: `if self.state == AGENT_SPEAKING: if not self.policy.interrupt_on_user_speech: return []` (finding cited 128-131, which is `_new_turn`)
- simorgh/voice/session.py:250-254: `self.turns = TurnManager(Policy(... interrupt_on_user_speech=config.barge_in, ...))` -- Policy is `@dataclass(frozen=True)` (turns.py:41), built once
- simorgh/voice/service.py:380-396: barge_on/off and aec_on/off do `self.config = replace(self.config, ...)` and `self._pipeline._config = self.config` but never touch `self._session`; contrast service.py:543-550 where `_set` does `session._config = self.config`
- tests/simorgh/voice/test_barge_in.py:411 `test_barge_off_then_on_flips_the_live_config` and :460 `pipe = Pipeline(...)` -- the barge-in live-toggle test exercises Pipeline, not VoiceSession
- simorgh/voice/session.py:376-388: `if self._echo.active(now): rms = ...; self._echo.observe(rms, now); set_echo(self._echo.expected(now))` runs in `_on_frame` on every frame irrespective of barge_in -> EchoTracker does run while Sim speaks
- simorgh/voice/config.py:88 `barge_in_known_voice: bool = False`; session.py:677 `if not self._config.barge_in_known_voice: return event` -> known-voice gate off by default, independent of barge_in
- simorgh/voice/turns.py:146-150 (speech while THINKING starts a new turn) and :252-254 (playback 'started' only moves THINKING->AGENT_SPEAKING) -> a turn that began before playback keeps capturing, so session.py:1014 `if self._player.playing and opens_with_stop(text)` is reachable during the ack or a late reply
- simorgh/voice/service.py:655 `utterance, said = await pipeline.listen_once(...)` -> listen_once is live-used; deleting it as recommended would break the one-shot listen command
- wc -l simorgh/voice/session.py -> 1961; `_ask_and_speak` spans 887-1135 (next def at 1135) = 248 lines; grep -c 'await ' -> 127; distinct `self._config.*` in session.py -> 39; fields in config.py -> 99; `self.turns.state = LISTENING` -> 15 occurrences

**severity adjustment:** keep

**corrected claim:** VoiceSession (the only loop production runs, since every shipped mic has `stream`) still borrows bus publishing, ledger recording, the speech lock and echo-memory from the legacy Pipeline (29 private reaches, 27 of them `_publish`). The NLMS echo canceller is constructed only in Pipeline's speak path, so with `aec: bool = True` as the code default and the README saying "off by default", the flag and the `voice barge aec on` command have no effect on the live loop. Barge-in is off in the live toml, and the runtime `voice barge on|off` toggle does not reach the running VoiceSession either (it updates service and pipeline config only; the TurnManager Policy is frozen at construction), while the test that covers the live toggle exercises Pipeline. What barge_in=false actually disables is only the turn-start transition in AGENT_SPEAKING: the EchoTracker still runs on every frame while Sim speaks, the known-voice gate is off by its own separate default, and the stop-word path remains reachable when a turn began before playback (ack, speech-while-thinking, late reply). `listen_once` is still used live and should not be deleted; only `run_loop` is dead in practice.

