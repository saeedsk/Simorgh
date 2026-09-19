# read:voice-interface-surfaces

*Workflow: review · Phase: Read · Agent id: `a51ac0007f1773faf` · Tool calls: 79*

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
  
  
  CONCERN: the human surfaces -- Voice pipeline and Interface (CLI/TUI, HTTP API + dashboard, Telegram/WhatsApp), Persona, and how a turn's identity (who is speaking, which session, which language) flows.
  Read simorgh/voice/ (session.py, turns.py, vad.py, speakers.py, stt/, tts/, planner.py, playback.py, service.py) and simorgh/interface/ (service.py, cli.py, tui.py, render.py, httpapi.py, telegram.py, whatsapp.py), simorgh/persona/.
  Questions: Is the voice pipeline's state machine sound -- where is per-turn state kept and is it read across awaits (a known bug shape: per-turn fact in a session singleton read across an await)? How is the mic/echo/barge-in problem handled and is it robust? Why is voice 11k lines -- what is in there, and is it the right decomposition? Interface subscribes to 30 topics and is 10.7k lines: is it a god-module, and is the HTTP API a security exposure (0.0.0.0 host in live config; auth only if SIM_API_TOKEN set; what routes can trigger actions; CSRF; camera/HLS serving)? Is there one session/identity model across CLI, voice, Telegram, WhatsApp, or several ad-hoc ones? Does Persona do anything observable? Evaluate the surfaces layer design.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines in voice subsystem files |  7 simorgh/voice/__init__.py 29 simorgh/voice/resample.py 41 simorgh/voice/stt/faster_whisper.py 45 simorgh/voice/lang.py 48 simorgh/voice/stt/__init__.py 53 si |
| 2 | Bash | Count lines in interface and persona subsystems | (eval):1: no matches found: simorgh/interface/*/*.py --- 0 simorgh/persona/__init__.py 15 simorgh/persona/api.py 57 simorgh/persona/sharing.py 59 simorgh/person |
| 3 | Bash | List subsystem directories and show live config | simorgh/interface: __init__.py __pycache__ activity.py api.py benchmarkchart.py benchmarkview.py config.py dashfeeds.py dispatch.py httpapi.py live_status.py pa |
| 4 | Bash | List interface file sizes, static dir, and voice README |  0 simorgh/interface/__init__.py 8 simorgh/interface/api.py 87 simorgh/interface/splash_art.py 160 simorgh/interface/vitals.py 191 simorgh/interface/config.py 1 |
| 5 | Bash | Read module map orientation doc | # Simorgh — Module Map and System Blocks **What this is.** One picture of every major building block, what each one owns, and how they interact — written so a s |
| 6 | Bash | Scan prior audit for already-known findings on these areas | 8:1. **Guardian's HMAC Verification:** The separation of proposal and execution via HMAC tokens is a stellar security pattern. Every effect is published as `act |
| 7 | Bash | Extract prior review's findings mentioning voice/interface/persona | Resource contention degrades voice latency the HMAC token before touching a tool. HTTP server. simorgh/interface/cartoon_splash.py max_output_tokens=16_000 magn |
| 8 | Bash | Read the start of voice session.py | """The spoken conversation: microphone frames in, speech out, with the floor changing hands the way it does between people. frames -> FrameVad -> TurnManager -> |
| 9 | Bash | Read the start of interface service.py | """Interface as a `Subsystem` (docs/blueprint/subsystems/15-interface.md): the CLI REPL, command dispatch, vitals, and console rendering. Layer 5 (registry.py). |
| 10 | Bash | Read the start of httpapi.py | """A minimal, stdlib-only HTTP server for Interface's live dashboard. Pulled forward from roadmap Phase 5's "HTTP/WebSocket API in Interface" item, scoped to th |
| 11 | Bash | Map HTTP routes, auth, CSRF and origin handling in httpapi.py | 45:import ipaddress 71:#: Routes that answer without a token even when one is configured. 72:#: `/` is the page that *carries* the token to the browser, so gati |
| 12 | Bash | Find every place that registers HTTP routes across subsystems | (eval):1: no matches found: --include=*.py |
| 13 | Bash | Read voice session init and state fields |  self._overheard_dir = getattr(config, "overheard_dir", "workspace/voice/overheard") #: when the model stayed quiet on a voice it could not place (voice/session |
| 14 | Bash | Read the voice TurnManager state machine | """The turn manager: who has the floor, and when it changes hands. A voice session is a small state machine -- idle -> listening -> user_speaking -> thinking -> |
| 15 | Bash | Read persona service entirely | """Persona as a `Subsystem` (docs/blueprint/subsystems/14-persona.md): continuous mood, a rule-based emotion floor, voice composition, the user model, and proac |
| 16 | Bash | Find who consumes persona state outside the persona package | (eval):1: no matches found: --include=*.py |
| 17 | Bash | Read the Telegram connector | """Sim over Telegram: the same brain, reached from a phone. The creator, 2026-09-16, by voice: "sometimes instead of bringing my macbook to my car to talk to yo |
| 18 | Bash | Read the WhatsApp connector | """Sim over WhatsApp: the sanctioned route, and only for the family. The creator, 2026-09-16, by voice: "maybe i can connect you to a whatsapp application so ba |
| 19 | Bash | Find HTTP route registration across subsystems | simorgh/interface/service.py:273: self._http = HttpApi( simorgh/interface/service.py:379: self._http.register_route("GET", "/api/whatsapp", _whatsapp_verify, au |
| 20 | Bash | List every registered route and every POST route | simorgh/interface/httpapi.py:224: def register_route(self, method: str, path: str, handler: RouteHandler, *, auth: bool = True, simorgh/interface/httpapi.py:289 |
| 21 | Bash | Read route registration, HLS, and auth in httpapi.py |  self._remote_page = (_STATIC_DIR / "remote.html").read_text(encoding="utf-8") # Sim's logo (the creator's, 2026-09-12; keyed and shrunk from # images/logo/Sim- |
| 22 | Bash | Read request dispatch, dash token injection, and CSRF guard |  # in-flight answer to a fixed 10s (the exact class of bug # `chat_reply_timeout_s`/`think_timeout_s` had elsewhere). try: await asyncio.wait_for(self._handle_o |
| 23 | Bash | Find every consumer of persona outputs outside persona | simorgh/interface/service.py:113: topics.PERSONA_STATE_CHANGED, topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_METRICS, simorgh/interface/service.py:234: await ctx. |
| 24 | Bash | Read voice session dispatch and ask path |  self._frames.put_nowait(frame) self._preroll.clear() self._capturing = action.turn_id if self._embedder is not None and self._speakers is not None: self._audio |
| 25 | Bash | Trace session_id through interface and orchestration | 162: self.session_id = str(uuid.uuid4()) 166: self._turn_started: dict[str, float] = {} # session_id -> monotonic start, for narration timing 390: ctx.logger.in |
| 26 | Bash | Locate identity fields in orchestration | __init__.py __pycache__ api.py claims.py config.py context.py profiles.py progress.py README.md resume.py scaffolds.py service.py session.py tools.py worker.py  |
| 27 | Bash | Read channels contract and interface config keys | """Every way a person can reach Sim, named once. The creator, 2026-09-16: "CHANGE THE CONTRACT AND INTRODUCE EXTERNAL VOICE/TEXT CHANNELS LIKE WHATSAPP AND TELE |
| 28 | Bash | List secret key names only, not values | 6 SIM_API_TOKEN REOLINK_HOST REOLINK_USERNAME REOLINK_PASSWORD RING_TOKEN RING_USERNAME |
| 29 | Bash | Read dash, camera, hooks and prefix route handlers in httpapi.py |  names = sorted(f.name for f in root.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif") and not f.name.startswith(".")) return 200, js |
| 30 | Bash | Read chat route and static file serving in httpapi.py |  this decides only what the message means.""" try: parsed = json.loads(body or b"{}") text = str(parsed.get("text", "")).strip() client_session_id = parsed.get( |
| 31 | Bash | List VoiceSession methods by size | 887: async def _ask_and_speak(self, turn_id (248 lines) 878: def whois_next(self) -> str (9 lines) 865: def enroll(self, name (13 lines) 853: def _open_embedder |
| 32 | Bash | Read the voice ask-and-speak path |  self._log("debug", "voice.barge_in_by", who=who.name, score=round(who.score, 3)) return event self._log("info", "voice.barge_in_ignored", score=round(getattr(w |
| 33 | Bash | Read the voice speaker identification path |  # recently -- a long reply returns as fragments, each too short # for the run matcher and each landing after `last_said` moved on. recents = list(self._pipelin |
| 34 | Bash | Trace how a percept's session_id becomes a chat task id |  async def run(self, session: Session, *, user_text: str = "") -> Outcome: self.current_task_id, self.current_kind = session.task_id, session.kind try: return a |
| 35 | Bash | Read persona voice, emotion, user model and the prompt assembler hook | """`mood_phrase` (v1 port, `src/agents/logic/base.py`) and a minimal `VoiceComposer` -- a condensed identity block plus the natural-language mood phrase, for Co |
| 36 | Bash | Check whether Interface fetches external feeds directly and how it triggers actions | 49:from __future__ import annotations 51:import asyncio 52:import html 53:import json 54:import re 55:import time 56:import urllib.parse 57:import urllib.reques |
| 37 | Bash | Map voice service, pipeline and how a spoken turn is published | 133:class Service: 270: self._pipeline = Pipeline( 295: self._session = VoiceSession( 356: async def _on_status(self, message) -> None: 359: async def _on_contr |
| 38 | Bash | Measure state-machine bypasses and per-turn singleton reads in voice session | direct state writes: 17 498: self.turns.state = LISTENING 650: self.turns.state = LISTENING 850: self.turns.state = LISTENING 988: self.turns.state = LISTENING  |
| 39 | Bash | Read the stay-quiet path in voice session | 1429: async def _acknowledge(self, turn_id: int, partial: str) -> None: 1542: async def _obey(self, turn_id: int, command: str, *, speaker: str = "", clock=None |
| 40 | Bash | Read the speak-reply path in voice session |  async def _speak_reply(self, turn_id: int, reply: str, clock: TurnClock, context: Context) -> None: actions = self.turns.reply_ready(turn_id) while any(a.kind  |
| 41 | Bash | Read how voice service composes Pipeline and VoiceSession, and the mood handler |  spk, why = open_speaker(cfg.speaker) if spk is None: problems.append(why) detector_factory = lambda: open_detector(cfg.vad, threshold=cfg.vad_threshold)[0] # n |
| 42 | Bash | Read interface service start, subscriptions and connector wiring |  self._telegram = None self._whatsapp = None async def start(self, ctx: Context) -> None: self._ctx = ctx self._loop = asyncio.get_running_loop() # A config pas |
| 43 | Bash | Compare declared consumes/produces with actual subscriptions and check enforcement | subscribe calls: 23 consumes 16 produces 12 --- selfcheck consumes enforcement --- |
| 44 | Bash | Check whether a reused session id collides with task stream or resume logic | 1:"""What a Session inherits from the `task:<id>` stream before it runs. 112: events = await ledger.read(f"task:{session.task_id}") 125: session.resumed_from_st |
| 45 | Bash | Check persona identity awareness, assembler timeout, feed fetch sites, and webhook token use | persona reads speaker: simorgh/persona/api.py:0 simorgh/persona/config.py:0 simorgh/persona/emotion.py:0 simorgh/persona/__init__.py:0 simorgh/persona/sharing.p |
| 46 | Bash | Read how interface routes voice transcripts and turn completions |  self._out(render_mod.style(f"🎤 {name}: {str(seg.get('text') or '').strip()}", "cyan", enabled=self._color)) if p.get("speaker_note"): self._out(render_mod.styl |
| 47 | Bash | Check resume logic and whether chat sessions with a reused id inherit prior steps |  summary = str(step.get("summary") or "") summary = summary if len(summary) <= cap else summary[:cap] + "…" mark = {True: "ok", False: "FAILED"}.get(step.get("o |
| 48 | Bash | Check how memory groups by session and whether household links handles to voices | 184: session_id = (payload.get("tags") or [None])[0] or "default" 185: self.engine.working.add(session_id, "", payload["content"], ts=self._ctx.clock.now()) 245 |
| 49 | Bash | Read spoken command recognition and the obey path | """The few things a person says TO the voice itself, not to Sim: "stop", "be quiet", "voice off". Handled on the spot, never sent to the model -- the creator sa |
| 50 | Bash | Characterise dispatch.py size and check for cross-subsystem imports from Interface | dispatch.py defs: 59 274 lines _skills_command (line 1879) 226 lines dispatch (line 181) 151 lines _tv (line 833) 94 lines _voice (line 454) 77 lines _mcp_comma |
| 51 | Bash | Read how dispatch runs a tool via Guardian on the page's behalf |  """Run any registered tool, from the terminal, through Guardian. Fifty tools and sixteen commands: adding a command per tool would make the help screen unreada |
| 52 | Bash | Confirm Interface performs its own outbound HTTP fetches for dashboard feeds | from datetime import datetime, timedelta, timezone from email.utils import parsedate_to_datetime from html.parser import HTMLParser from pathlib import Path fro |
| 53 | Bash | List live voice and camera workspace artefacts | blobs heads idem index.json LOCK snapshots streams audio engines kokoro-sample.wav models overheard references samples speakers venvs Backyard_Door_Left-2026091 |
| 54 | Bash | Check which sessions call restore_session and whether recall filters by session |  # busy (`planning/scheduler.py::better_ready`). Everything below # -- the session, the heartbeat, cancel tracking -- belongs to # the task actually claimed. ta |
| 55 | Bash | Read the bus-driven command request handler and its publish policy |  async def _on_command_request(self, message: Message) -> None: """Sim running one of its own CLI commands (`sim_command`). The creator, 2026-09-15: "it should  |
| 56 | Bash | Check whether the CLI shell command bypasses Guardian | 28:import subprocess 170: result = subprocess.run( # noqa: S602 -- the human's own shell authority, run by Interface (spec section 7) 173: except subprocess.Tim |
| 57 | Bash | Read how the VAD accumulates speech_ms and how the echo reference is built | 13:531- self._speech_ms = 0 14:532- self._silence_ms = 0 16:534- self._quiet_run = 0 22:540- def process(self, frame: bytes): 28:546- self._quiet_run = 0 29:547 |
| 58 | Bash | Measure kept voice audio and overheard transcripts on disk |  68M workspace/voice/audio 0 842 313: keep_audio: bool = False 314: audio_dir: str = "workspace/voice/audio" --- gitignore --- 31:# never committed or reviewed. |
| 59 | Bash | Check feed loop start, TUI dependency, and household member fields | 180: self._feeds = feeds 305: if self._feeds is None: 308: body = self._feeds.snapshot() 467: if self._feeds is None: 470: body = {"now": self._now(), "streams" |
| 60 | Bash | Measure voice, persona and task streams in the live ledger | 66: barge_in: bool = True 102: # `tts_speed`, `interrupt_on_user_speech` is `barge_in`, `end_of_turn_ --- voice:turns stream size --- -rw-r--r--@ 1 saeed staff  |
| 61 | Bash | Read the pipeline's turn-completed, task-event and ask paths |  what = str(state.get("title") or state.get("url") or "something") where = f"in its {state['native']} app" if state.get("native") else "full screen" return f"TV |
| 62 | Bash | See what text a cancelled chat publishes on turn.completed | 486: # TASK_COMPLETED/TURN_COMPLETED publishes below -- and the finished 523: topics.TURN_COMPLETED, source=self._bus.source, 17: if outcome.floor: 18: payload[ |
| 63 | Bash | Measure persona state stream composition and check defaults | persona:state events 47784 size MB 17.8 [('decay', 44444), ('task.completed', 2516), ('task.blocked', 328), ('percept.text', 288), ('health.reset', 141), ('task |
| 64 | Bash | Check whether consumes/produces manifests are enforced and where sim_command lives | consumes read anywhere: 0 --- sim_command --- simorgh/interface/live_status.py:44: ("act", "sim_command"): "Running", simorgh/contracts/toolargs.py:33: "sim_com |
| 65 | Bash | Check whether skills/mcp CLI commands have direct side effects outside Guardian | 89: home.parent.mkdir(parents=True, exist_ok=True) 91: shutil.rmtree(home) 92: shutil.copytree(folder, home) 152: cache_path.parent.mkdir(parents=True, exist_ok |
| 66 | Bash | Check TTS subprocess servers, retention of overheard and audio, and language detection | __init__.py __pycache__ chatterbox_server.py miso_server.py styletts2_server.py 8:`workspace/voice/venvs/<engine>/`, started on first use, kept warm, and 22:Hon |
| 67 | Bash | Check pipeline pending map and the percept channel contract | 174: self._pending: dict[str, asyncio.Future] = {} 185: # `_pending`, which is emptied the instant the reply arrives. 231: fut = self._pending.get(str(payload.g |
| 68 | Bash | Confirm chat tasks honour cancel and what text a cancelled turn carries | --- _turn_text --- 57:_CANCEL_REASONS = frozenset({"the task was cancelled", "the turn was cancelled before it finished"}) 58- 59- 60-def _turn_text(outcome, ca |
| 69 | Bash | Reproduce the stay-quiet clobber against the real TurnManager | after two asks: thinking asked 2 superseded 1 ['ask'] _stay_quiet(5) reply_ready -> [('drop_reply', 'a later turn was asked')] state after _stay_quiet(5): liste |
| 70 | Bash | Read the skills command's disk effects and which profiles offer sim_command | async def _skills_command(args: str, *, ledger: LedgerClient, clock, clone=_clone_at, fetch=_fetch_tree) -> Outcome: """Agent Skills: what is here, what a skill |
| 71 | Bash | Check AEC wiring and test coverage around the voice state machine | 186: async def stop(self) -> None: --- aec use in session --- 89: # Acoustic echo cancellation for barge-in (voice/aec.py). When on, 95: # gate above is the saf |
| 72 | Bash | Re-run the stay-quiet clobber reproduction with correct turn ids | after two asks: state=thinking asked=2 superseded=1 _stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')] state after _stay_quiet(1): |
| 73 | Bash | Find who subscribes to task.cancel and whether chat tasks can be cancelled | simorgh/benchmark/service.py:134: topics.TASK_CANCEL, source=self._ctx.source, partition_key=f"task:{t['task_id']}", simorgh/benchmark/runner.py:235: topics.TAS |
| 74 | Bash | Check pipeline subscriptions, AEC reachability from the live loop, and echo reference feed |  async def start(self) -> None: # The answer to a chat turn arrives as `turn.completed{session_id, # text}` -- exactly what the REPL waits for (`interface/servi |
| 75 | Bash | Read Planning's task.cancel handler to see if chat ids are acted on |  async def _on_task_cancel(self, message: Message) -> None: """Stop a task nobody is waiting for any more. Both halves are needed. The Worker stops its session  |
| 76 | Bash | Count config knobs, regexes and subscriptions in the surfaces layer | session.py distinct config knobs read: 39 voice/config.py fields: 99 session.py compiled regexes: 5 session.py awaits: 127 httpapi subscribes: 6 interface pkg s |
| 77 | Bash | Quote the unauthenticated camera URL construction and measure what the user model learnt |  try: at = f.stat().st_mtime except OSError: continue if at > newest.get(safe, 0.0): newest[safe] = at now = self._clock() for safe, at in newest.items(): if no |
| 78 | Bash | Check how a running session learns it was cancelled | simorgh/orchestration/worker.py:55:#: the two reasons a turn ends because it was cancelled -- exact, so a simorgh/orchestration/worker.py:57:_CANCEL_REASONS = f |
| 79 | Bash | Confirm the runner ends a cancelled chat session with a cancelled reason |  self._subs.append(await self._bus.subscribe(topics.TASK_CANCEL, self._on_cancel)) async def stop(self) -> None: for s in self._subs: await s.unsubscribe() self |

## Structured reply

**concern:** Human surfaces: Voice pipeline, Interface (CLI/TUI, HTTP API + dashboard, Telegram/WhatsApp), Persona, and how a turn's identity (speaker, session, language) flows.

**summary of what is actually there:** Voice (10,930 lines) is two generations stacked: `voice/pipeline.py` (596 lines) is the older loop that still owns the bus publish/record helpers, the `speech_lock`, `recent_said` and the pending-reply futures, and `voice/session.py` (1,961 lines, class `VoiceSession`) is the live loop that `voice/service.py:295` builds from the Pipeline's private engines (`pipeline._mic  # noqa: SLF001`) and drives via `_on_frame` -> `FrameVad` -> `TurnManager` (`turns.py`, a pure state machine idle/listening/user_speaking/thinking/agent_speaking/interrupted) -> `_ask_and_speak` (248 lines) -> `StreamingSynthesiser` -> `StreamingPlayer`. Per-turn timing lives in a `TurnClock` dataclass keyed by turn id (`_clocks[turn_id]`), and since the 2026-09-18 fix the speaker name is also per-turn (`_named[turn_id]`), but the session still keeps `_last_speech_s`, `_last_pcm`, `_last_skip`, `partial`, `last_speaker` as singletons and writes `self.turns.state = ...` directly in 17 places, bypassing the state machine it delegates to. A spoken turn becomes `percept.text.received{channel:"voice", session_id:<fresh uuid>, speaker, speaker_relation, room, speaker_before}` (`pipeline.py:349-367`); Orchestration turns that `session_id` into the chat `Session.task_id` (`orchestration/service.py:267`, `worker.py:401`), so a chat's task id is its session id on every surface. Echo/barge-in is a level gate whose bar comes from the playback reference (`vad.EchoTracker`), optionally gated by a speaker-embedding check of the pre-roll (`_only_a_voice_we_know`); an NLMS AEC (`aec.py`) exists but is wired only into the legacy `Pipeline._play_stream_interruptibly`, and the live config has `barge_in = false`, so in production nothing can interrupt Sim by voice. Interface (10,747 lines) is one `Service` (1,504 lines, 23 bus subscriptions vs. a declared `consumes` of 16) that owns the REPL/prompt_toolkit TUI, a 2,234-line command router (`dispatch.py`), a hand-rolled asyncio HTTP server (`httpapi.py`, 1,264 lines, ~30 routes and 5 prefix routes), a 1,110-line feed scraper (`dashfeeds.py`: CNBC bars, RSS, YouTube search via `urllib` in a thread pool) and the Telegram (long-poll) and WhatsApp (signed webhook) translators. The HTTP server binds `0.0.0.0` in the live config with `SIM_API_TOKEN` set; bearer or `?token=` gates most routes, but `/`, `/tv`, `/dash`, `/api/dash/*` reads, `/cameras/snap/*`, `/tv/hls/*`, `/tv/media/*` and `/wallpapers/*` are deliberately open so the Cast receiver (which sends no headers) can fetch them. Dashboard side effects (`/api/dash/cameras/*`, `/api/dash/youtube`, `/api/dash/ring/live`) go through `dispatch._run_tool`, which publishes `action.proposed` like a Worker, so Guardian does see page clicks. Session identity is minted separately per surface: CLI mints a uuid per typed line, HTTP accepts a client-supplied id per page load, Telegram/WhatsApp mint one uuid per chat/number in an in-memory dict (lost on restart), Voice mints one per spoken turn and records `turn-N` in `voice:turns`. Who is speaking exists only on the voice path (speaker book -> `speaker` on the percept -> `orchestration/scaffolds.who_is_here`); Telegram's allow-list knows the username but never puts a person on the bus, `contracts/household.py` has no handle-to-member mapping, and Persona never reads `speaker`. Persona (797 lines) keeps a valence/arousal mood driven by a ~30-word lexicon and task outcomes, decays it every 5 s, persists every change to `persona:state`, answers a `persona.voice` bus request that Cognition's assembler makes on every prompt (2 s timeout) with "Right now you're feeling <phrase>.", and keeps a two-regex user model (`I prefer X`, `call me X`) that has produced one facet in its lifetime.

### strengths

- TurnManager (simorgh/voice/turns.py) is a pure, mic-free state machine with explicit handling of stale, superseded and late replies (`reply_ready`, turns.py:196-231) and a transitions log; it is the right seam and is unit-testable with a list of events.
- External channels are closed and deny-by-default: `contracts/channels.py` makes `channel` a closed enum built from one module, `allowed()` admits nobody on an empty list, Telegram/WhatsApp keep chat ids and phone numbers in their own maps and never on the bus (telegram.py:83-87, whatsapp.py:88-90), and WhatsApp verifies Meta's HMAC with `hmac.compare_digest` before parsing (whatsapp.py:146-153).
- The HTTP server has a real route table with auth-by-default, a reviewed `_OPEN_ROUTES` list, per-route rate limits and body caps, a correct Origin-vs-Host CSRF check for POSTs, constant-time token comparison, and `resolve()`+prefix checks on every file-serving prefix (httpapi.py:224-242, 541-546, 596-611, 1021-1062).
- Dashboard side effects are not a back door: `/api/dash/cameras/*`, `/api/dash/youtube`, `/api/dash/ring/live` call `dispatch._run_tool`, which publishes `action.proposed` exactly as a Worker does (httpapi.py:388-418; dispatch.py:1330-1338), so Guardian sees page clicks.
- The barge-in bar is derived from what is being PLAYED, not from what the mic hears (vad.py:360-387 `EchoTracker`), which is the correct principle after two mic-learnt bars failed; the per-reply gain calibration and the 'fails open' rule in `_only_a_voice_we_know` (session.py:655-706) are sound engineering choices.
- Per-turn state is moving in the right direction: `TurnClock` (session.py:52-72) and `_named[turn_id]` (session.py:960-968) already carry timing and speaker per turn, so the remaining singletons have an obvious home.
- Persona restores mood from the ledger with downtime decay (persona/service.py:120-165) and sanitises user-model facets (single line, 200 chars, control chars stripped) before they reach a protected prompt block (user_model.py:38-48), which closed a real prompt-injection path.
- Telegram and WhatsApp are thin translators (241 and 267 lines) onto the existing percept/turn.completed path; adding a channel did not add a path through the system.
- Interface's bus-driven command channel refuses the `!` shell escape outright (`_on_command_request`), and all terminal output passes one gate (`_out()`), so the footer and bus-driven lines never interleave.

### findings

##### 1. A superseded spoken turn's 'quiet' outcome flips the floor and drops the newest turn's real answer

- **kind:** bug
- **severity:** high
- **claim:** `_stay_quiet(turn_id)` unconditionally sets `turns.state = LISTENING` when the state is THINKING, even when THINKING belongs to a NEWER asked turn, so the newer turn's answer is then refused by `reply_ready` as 'the session is listening' and never spoken.
- **evidence:**
  - simorgh/voice/session.py:1621-1632 (`_stay_quiet`): `actions = self.turns.reply_ready(turn_id)` ... `if self.turns.state == THINKING: self.turns.state = LISTENING if self.turns.auto_listen else self.turns.state`
  - simorgh/voice/turns.py:206-219 (`reply_ready`): the `_superseded` branch returns SPEAK 'late; the newer turn is still owed' and does not change state; then `if self.state != THINKING: return [Action(Actions.DROP_REPLY, ..., reason=f"the session is {self.state}")]`
  - Trigger chain is live: session.py:579-590 `_cancel_outstanding` publishes `task.cancel` for the old turn's session id; orchestration/worker.py:218 subscribes; orchestration/session.py:887 ends the session with CANCELLED_REASON at the next step boundary; voice/pipeline.py:264-272 `_on_task_event` does `fut.cancel()` when 'cancelled' in reason; pipeline.py:370-372 `ask` returns ""; session.py (in `_ask_and_speak`, after `reply = await self._pipeline.ask(...)`): `if not _strip_tone(reply).strip() or is_quiet(...): ... await self._stay_quiet(turn_id)`. A model answering QUIET to the older turn is a second trigger with no cancel needed.
  - Reproduction against the real TurnManager (python3 script in scratchpad, replicating session.py:1621-1632 verbatim): `after two asks: state=thinking asked=2 superseded=1` / `_stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')]` / `state after _stay_quiet(1): listening, asked=2` / `reply_ready(2) for the NEW turn's real answer -> [('drop_reply', 'the session is listening')]`
  - `grep -c 'self.turns.state = ' simorgh/voice/session.py` -> 17 direct writes; `_guarded` (session.py:487-500) does the same flip on any exception in an older turn's task; ASK at session.py:465 creates a new `_ask_task` without cancelling the previous one, so two `_ask_and_speak` coroutines run concurrently.
- **why it matters:** This is the exact live complaint recorded in turns.py's own comments ('a 15 s answer was dropped because the creator spoke meanwhile ... Sim was blamed for silence', 2026-09-13): ask one thing, ask another before the first is answered, and the second answer appears on screen as 'reply dropped' and is never spoken. It is also the general form of the 'per-turn fact in a session singleton read across an await' bug: the singleton here is the state machine's `state`.
- **recommendation:** Make TurnManager the only writer of `state`. Add `TurnManager.reply_quiet(turn_id)` (and `reply_failed(turn_id)`) that leave THINKING only when `turn_id == self._asked_turn` (and clear `_superseded` when it matches), then delete all 17 `self.turns.state = ...` writes in session.py, replacing each with a named TurnManager method. Add the reproduction above as a unit test in tests/simorgh/voice (48 test files exist; none reference `_superseded`).
- **confidence:** 0.9

##### 2. Camera stills and live HLS of the house are served without the token on a 0.0.0.0 bind

- **kind:** wrong-design
- **severity:** high
- **claim:** With `http_host = "0.0.0.0"` live, any device on the LAN can list the cameras (`/api/dash/streams` is in `_OPEN_ROUTES`) and fetch the newest still of every camera and the live HLS video without the token, because those prefixes are open so the Cast receiver can fetch them header-less; the bearer token is also placed in URLs.
- **evidence:**
  - simorgh/interface/httpapi.py:77-79 `_OPEN_ROUTES` includes "/api/dash/streams", "/api/dash/data", "/api/dash/state", "/api/dash/keys"
  - httpapi.py:921 `open_ = prefix in ("/tv/hls/", "/tv/media/", "/wallpapers/", "/cameras/snap/")` ; httpapi.py:208-212 comment: 'Served on the LAN without the token: the Cast receiver fetches segments with no header and no query of its own'
  - httpapi.py:540-562 `_snap` returns the newest JPEG for `/cameras/snap/<camera>`; httpapi.py:541-546 `_hls` returns `.m3u8`/`.ts` from workspace/cameras/hls; dashfeeds.py:985-986 builds `"url": prefix + urllib.parse.quote(safe)` into the open `/api/dash/streams` reply
  - ~/.simorgh/simorgh.toml: `[interface]\nhttp_host = "0.0.0.0"`; ~/.simorgh/secrets.toml contains key `SIM_API_TOKEN` (value not read); `du -sh workspace/cameras` -> 3.8G
  - Token in URL: httpapi.py:938-948 302-redirects a local viewer of `/dash` to `/dash?token=<token>`; httpapi.py:609-610 `_authorized` accepts `?token=`; the TV is handed a URL containing the token
- **why it matters:** For one family on one LAN this is a modest exposure, but it is the single most sensitive data the system holds (the inside of the house, live) and it is the only class of data served with no check at all; guest Wi-Fi, a compromised IoT device or a child's friend's phone gets it. A bearer token in a URL also ends up in browser history and in the `Referer` of any link the dash page opens.
- **recommendation:** Keep the Cast exception but make it a capability, not a public path: mint a per-boot random segment (`/tv/hls/<secret>/...`, `/cameras/snap/<secret>/...`) that only the token-gated `/api/dash/streams` reply and the TV URL carry, and 404 without it. Move `/api/dash/streams` (which enumerates cameras) behind the token. For browsers on this machine, set the token as an `HttpOnly; SameSite=Strict` cookie from `/dash` instead of a query redirect, and keep `?token=` only for the TV. Consider defaulting `http_host` back to loopback plus an explicit LAN opt-in that logs which peers fetched HLS.
- **confidence:** 0.85

##### 3. Four ad-hoc session models and no identity contract: 'who is talking' exists only on the voice path

- **kind:** wrong-design
- **severity:** medium
- **claim:** Each surface invents its own session id with different semantics (CLI: one uuid per typed line; HTTP: client-chosen per page load; Telegram/WhatsApp: one uuid per chat kept only in memory; Voice: one uuid per spoken turn plus `turn-N` in the ledger), and only Voice attaches a person; Telegram knows the username but drops it, the household roster has no handle field, and Persona never sees a speaker at all.
- **evidence:**
  - simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` per typed line (and :162 a separate REPL `self.session_id`)
  - simorgh/interface/httpapi.py:1121 `session_id = session_id or str(uuid.uuid4())` (client-supplied, validated only as a stream name at :1082)
  - simorgh/interface/telegram.py:83-87, 190-194 and whatsapp.py:88-90, 211-215: `_sessions[chat_id] = str(uuid.uuid4())` in plain dicts, never persisted; telegram.py:177-181 `who = username or id` is used only for `channels.allowed()` and never placed on the percept
  - simorgh/voice/pipeline.py:353 `session_id = session_id or str(uuid.uuid4())` per turn; session.py:1888 `VoiceTurn(session_id=f"turn-{turn_id}", ...)` records a different id for the same turn
  - simorgh/orchestration/service.py:267 `session_id = message.payload.get("session_id") or message.id`; worker.py:401 `Session(task_id=session_id, kind="chat", ...)`; memory/service.py:245 tags episodic memories with `[session_id, person:<name>...]`
  - simorgh/contracts/household.py:29-35 `Member(name, sex, say_as, age, relation, note)` has no handle/number field; `grep -c speaker simorgh/persona/*.py` -> 0 in every file
- **why it matters:** The system already knows who Saeed is by voice, by Telegram username and by phone number, but there is no place where those are the same person, so memories tagged `person:Saeed` from the room are invisible to him on Telegram, a Telegram conversation forgets itself on every restart, and Persona's 'user model' is a single anonymous blob for a five-person household. Every future feature that needs 'the same person across surfaces' (reminders, preferences, language) will have to re-solve this.
- **recommendation:** Add one small contract, `contracts/identity.py`: `Conversation(conversation_id, channel, person, language)` plus a `resolve(channel, address_or_voice) -> person` table that maps Telegram handles, WhatsApp numbers and speaker-book names onto `household.Member` names (config-driven, a dozen lines). Interface/Voice fill it, `percept.text.received` carries `person` and a stable `conversation_id` (persist the channel maps in a small JSON or a ledger stream so a restart does not forget), and Orchestration/Memory/Persona key on it. Keep the per-turn correlation uuid as `turn_id`, separate from `conversation_id`; the previous review's warning about the per-message uuid still holds for correlation, it just should not be called a session.
- **confidence:** 0.85

##### 4. Interface's `consumes`/`produces` manifests are decorative and out of date

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** The Subsystem manifest lists 16 consumed and 12 produced topics while the package actually subscribes 33 times (23 in service.py alone) and publishes topics not in `produces` (ACTION_PROPOSED, DASH_STATE, UI_HOOK_RECEIVED, TASK_CANCEL, UI_COMMAND_REPLY); nothing in the codebase reads `.consumes`, so the contract the module map is supposed to be drawn from cannot be trusted.
- **evidence:**
  - simorgh/interface/service.py:110-123: AST count `consumes 16`, `produces 12`
  - `grep -c 'ctx.bus.subscribe(' simorgh/interface/service.py` -> 23; `cat simorgh/interface/*.py | grep -c 'bus.subscribe('` -> 33
  - `grep -rn '\.consumes\b\|\.produces\b' simorgh --include='*.py'` (excluding the tuple declarations) -> 0 readers; kernel/selfcheck.py, registry.py, kernel.py contain no reference
  - docs/module-map.md header: 'the message edges by walking every `topics.*` reference in `simorgh/` and classifying publish vs. subscribe' (i.e. by grep, not from the manifests)
- **why it matters:** A manifest that lies is worse than none: the architecture docs, the self-check and any future 'which subsystem may this topic reach' rule will be built on it. This is the same 'designed slot, nobody writes it' shape the project already knows, applied to its own architectural metadata.
- **recommendation:** Either enforce or delete. Enforcing is cheap: in `kernel/selfcheck.py`, after boot, compare each service's live subscriptions (the Bus already knows them) with `consumes` and fail the boot gate on a mismatch; generate `produces` from the Bus's publish policy the same way. Then regenerate docs/module-map.md from the manifests instead of grep.
- **confidence:** 0.9

##### 5. Interface fetches the outside world itself (markets, news, YouTube search) outside Execution and Guardian

- **kind:** wrong-design
- **severity:** medium
- **claim:** `dashfeeds.py` (1,110 lines, on by default) performs outbound HTTP with a spoofed browser User-Agent from a thread pool inside the surfaces layer, parses untrusted HTML/RSS/JSON, and its scraped YouTube ids are what `/api/dash/youtube` hands to `cast_play`; none of these calls is proposed to Guardian or visible in the ledger as actions.
- **evidence:**
  - simorgh/interface/dashfeeds.py:73-79 `def fetch(url, ...)`: `urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 -- public read-only endpoints` with `USER_AGENT = "Mozilla/5.0 (Macintosh ...) Safari/605.1.15"`
  - dashfeeds.py:122 `CNBC_BARS = "https://ts-api.cnbc.com/harmony/..."`; :792 `parse_youtube_results(f(YOUTUBE_SEARCH.format(...)))`; :925 `ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="dash-feeds")`
  - simorgh/interface/config.py:131 `dash_feeds: bool = True`; service.py:263-270 constructs `DashFeeds(...)` whenever the HTTP server is on
  - httpapi.py:449-462 `_youtube_to_tv` -> `_run_for_page("cast_play", {"url": f"https://www.youtube.com/watch?v={video}", "mode": "full"})`
  - Creator's stated constraint (memory: reuse_open_source): 'only real constraint is Guardian must see every call'
- **why it matters:** It is the one place in the system where network I/O happens without the action path, so the 'Guardian sees every effect' invariant is true of tools but not of the process. It also explains a third of Interface's size: a surfaces package that scrapes CNBC is a god-module by construction, and scraping code rots fastest.
- **recommendation:** Move the fetchers into the execution/domains layer as read-only tools (`feeds_markets`, `feeds_news`, `media_search`) with their own cache and a `scope.network=True` proposal, and have a small scheduler task refresh them; Interface then reads a `dash:feeds` ledger stream or a bus reply and stays a renderer. If the creator consciously wants these to bypass Guardian as 'public reads', write that exception into contracts/topics.py or the blueprint so it is a decision rather than an accident.
- **confidence:** 0.8

##### 6. Persona is observable but its cost is out of proportion to what it adds

- **kind:** over-engineering
- **severity:** medium
- **claim:** Persona writes a ledger event and a bus message every 5 s of mood decay (93% of its 47,784 events, 17.8 MB), adds a bus round-trip with a 2 s timeout to every prompt assembly to inject one sentence ('Right now you're feeling <phrase>.') derived from a ~30-word lexicon, and its user model has extracted one facet in the system's lifetime.
- **evidence:**
  - Measured from ~/.simorgh/ledger/streams/persona%3Astate.jsonl: `persona:state events 47784 size MB 17.8` / sources `[('decay', 44444), ('task.completed', 2516), ('task.blocked', 328), ('percept.text', 288), ('health.reset', 141), ('task.failed', 67)]`
  - simorgh/persona/config.py:16 `decay_interval_s: float = 5.0`; persona/service.py:226-236 `_on_tick_second` publishes `PERSONA_STATE_CHANGED` and persists on every significant decay
  - simorgh/persona/emotion.py:14-24: 12 positive, 12 negative, 7 arousal words; user_model.py:16-17 two regexes (`I prefer`, `call me`); measured `persona:user_model events 1 {'preferred_name': 1}`
  - simorgh/cognition/assembler.py:54 `voice = await self._try_request(topics.PERSONA_VOICE, ...)` on every `assemble`; cognition/config.py:136 `assembly_request_timeout: float = 2.0`
  - Observable outputs: persona/voice.py:40-41 mood sentence in a protected prompt block; interface/vitals.py:159 mood bar; voice/service.py:687-692 mood -> delivery; curiosity/service.py:155 and reflection/service.py:184 subscribe
- **why it matters:** For one laptop and one family a mood engine is a fine flourish, but it is currently the noisiest writer in this concern (17.8 MB of the ledger is decay ticks) and it sits in the latency path of every model call. Meanwhile the one thing a persona layer should do for a household, model each person, is absent (finding on identity).
- **recommendation:** Persist mood only on non-decay changes and compute decay lazily on read (store `(value, ts)` and decay in `current()`), which removes ~93% of the stream; have Persona publish `persona.voice.changed` and let Cognition cache the style block instead of requesting it per prompt; key the user model by `person` once the identity contract exists. Keep the lexicon floor; it is cheap and honest.
- **confidence:** 0.8

##### 7. Voice is two half-generations: Pipeline still owns the plumbing VoiceSession runs on, AEC is dead in the live path, and barge-in is off in production

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** `VoiceSession` (the live loop) reaches into the legacy `Pipeline` 29 times for bus, ledger, lock and echo-memory, the default-on NLMS echo canceller is wired only into `Pipeline.run_loop` which `VoiceSession` never runs, and the live config disables barge-in entirely, so the EchoTracker, known-voice gate and stop-word paths cannot run while Sim speaks.
- **evidence:**
  - `grep -c 'self._pipeline\._' simorgh/voice/session.py` -> 29 (each marked `# noqa: SLF001`); voice/service.py:270-300 builds `Pipeline(...)` then `VoiceSession(pipeline=pipeline, microphone=pipeline._mic, recogniser=pipeline._stt, synthesiser=pipeline._tts, detector_factory=pipeline._detector_factory)`
  - simorgh/voice/pipeline.py:465-503 is the only place `EchoCanceller`/`EchoCancellingDetector` are constructed (`if self._config.aec and _aec_available()`); `grep -n 'aec' simorgh/voice/session.py` -> no matches; voice/config.py:96 `aec: bool = True`; voice/README.md says '`aec.py`, off by default'
  - ~/.simorgh/simorgh.toml `[voice] barge_in = false`; turns.py:128-131 in AGENT_SPEAKING `if not self.policy.interrupt_on_user_speech: return []`, so no CAPTURE_START while Sim talks and session.py's `if self._player.playing and opens_with_stop(text)` can never be reached during playback
  - Size and knobs: session.py 1,961 lines; `_ask_and_speak` 248 lines (session.py:887-1135); 39 distinct `self._config.*` knobs read in session.py out of 99 fields in voice/config.py; 127 awaits in session.py; 11 heuristic exits (`_courtesy_aside`, `_bystander`, `_continuation`, `_unplaced`, TV-audio, echo, repeat, who-said, identity-claim, whois, enrol) each ending in a direct `turns.state = LISTENING`
- **why it matters:** The README and config describe a barge-in and echo-cancellation system that the running house does not have; the creator has, in effect, given up on interrupting Sim by voice after three approaches, and the code that would let him is unreachable or off. The addressed-to-Sim policy (is this for me?) is the real product logic of a room assistant and it is spread across ~1,000 lines of heuristics plus a prompt scaffold, with each rule bolted on after a live incident, which is why they keep contradicting each other (the docstrings at session.py:1040-1063 say so).
- **recommendation:** (1) Finish the migration: move `_publish/_record/speech_lock/recent_said/_pending` into a ~150-line `VoiceBus` owned by VoiceSession and delete `Pipeline.run_loop`/`listen_once`; then either wire `EchoCanceller` into `VoiceSession._play`/`_on_frame` or delete aec.py and the flag. (2) Extract the addressed-to-Sim rules into one pure `addressing.decide(TurnFacts) -> Decision(answer|quiet(reason)|aside)` where `TurnFacts` is a frozen dataclass built once per turn (speaker, score, text, names_sim, sim_spoke_ago, tv_playing, room window, last_asked_speaker); the 11 exits become one call and one TurnManager transition, and the rules become a table you can test from the 842 kept turns. (3) Decide barge-in honestly: either fix the level gate on the laptop speakers with the kept audio or document that headphones/TV-output are required and remove the dead config.
- **confidence:** 0.8

##### 8. Per-turn facts still live in session singletons and are read across awaits; the known-voice barge-in judge is unthrottled

- **kind:** bug
- **severity:** medium
- **claim:** `_last_speech_s`, `_last_pcm` and `_last_skip` are set per turn in `_identify` and read after later awaits by `_ask_and_speak`, `_enroll_take` and the introduction path, while a second `_ask_and_speak` for the next turn can overwrite them (ASK never cancels the previous ask task); separately, `_only_a_voice_we_know` runs a speaker embedding of the 1.2 s pre-roll on every 30 ms frame while a non-family sound continues over Sim's voice.
- **evidence:**
  - simorgh/voice/session.py:712-716, 725 set `self._last_speech_s`, `self._last_pcm`, `self._last_skip` inside `_identify(turn_id)`
  - session.py `_ask_and_speak`: `segments = await self._attribute(turn_id, identification)` (a `to_thread` diarisation) precedes `may_refine(..., seconds=self._last_speech_s, ...)` at session.py:940; `_enroll_take` reads `self._last_pcm` at :842-843 after `await self._pipeline._publish(...)` at :830; introduction path reads it at :1415-1416
  - session.py:465 `self._ask_task = asyncio.create_task(self._guarded(self._ask_and_speak(...)))` with no cancel of the previous `_ask_task`, so two turns' `_ask_and_speak` overlap
  - session.py:655-706 `_only_a_voice_we_know`: gated only by `barge_in_known_voice`, `speech_ms >= barge_in_speech_ms` and embedder presence, then `await asyncio.to_thread(self._embedder.embed, samples, 16000)` with no memo; vad.py:548 `self._speech_ms += self._frame_ms` keeps the condition true on every subsequent frame; the await sits inline in the mic loop (`_on_frame`, session.py:373-385). Default off: voice/config.py:88 `barge_in_known_voice: bool = False`
  - The same shape was fixed for `speaker` on 2026-09-18 (session.py:955-968 comment: '23 of 122 named turns reached voice:turns with speaker=""')
- **why it matters:** The first is the same bug class the creator just paid for, still present for the enrolment and refinement paths: a take can be kept with another turn's audio/length, which is exactly how one family member's voice was blended into another's before. The second, when enabled, saturates the frame loop (one embedding per frame) precisely while the TV is on, which is when the creator enables it.
- **recommendation:** Move `speech_s`, `pcm`, `skip` onto `TurnClock` (already keyed by turn id) and pass the clock into `_enroll_take`/`_introduce_step`; cancel or fence the previous `_ask_task` at ASK (or make `_ask_and_speak` bail if `turn_id != turns._asked_turn` after each await). Throttle `_only_a_voice_we_know` to one judgement per barge-in candidate (cache the verdict until `speech_end`) and run it off the frame loop.
- **confidence:** 0.8

##### 9. `sim_command` is a Guardian-opaque command channel; `skills` mutates disk outside the action path

- **kind:** wrong-design
- **severity:** medium
- **claim:** The model can run any typed CLI line via the `sim_command` tool -> `ui.command.request` (a topic with no publish policy) -> `dispatch()`, where Guardian only sees the wrapper 'sim_command' (classified irreversible, auto-approved by sim.sh) and not the effect; only `!` shell is refused, while `skills install/approve/enable` copy and delete skill folders directly with `shutil`.
- **evidence:**
  - simorgh/interface/service.py `_on_command_request`: refuses `line.startswith("!")`, otherwise `outcome = await dispatch(command, ...)` for any parsed command
  - simorgh/contracts/topics.py:65 `UI_COMMAND_REQUEST = "ui.command.request"` with no `PUBLISH_ONLY_BY` entry (grep finds only the definition)
  - simorgh/orchestration/profiles.py:40 and :197 include "sim_command" in CHAT and VOICE_CHAT; orchestration/tools.py:65 `"sim_command": ("irreversible", False)`
  - simorgh/interface/dispatch.py `_skills_command` (line 1879, 274 lines): `shutil.rmtree(home)` / `shutil.copytree(folder, home)` and the `review/` staging copies (window 2080-2130), with no `ACTION_PROPOSED`/`_run_tool` in the function (grep)
  - Known context: sim.sh auto-approves irreversible actions (memory: guardian_auto_approve_default)
- **why it matters:** The action path's guarantee is that Guardian classifies the real effect; here it classifies a string. Installing a skill (third-party code that will later run) is the highest-consequence thing the CLI can do and it is reachable by the model as one opaque 'irreversible' action.
- **recommendation:** Turn `sim_command` into an allow-list of verbs that are genuinely UI-level (restart, voice on/off/mute, tv show, tasks, status, help) and reject the rest with 'use the tool'; route `skills install/approve/enable` through `_run_tool` as a real `skills_install` tool so Guardian sees the URL and the target path. Add `UI_COMMAND_REQUEST` to `PUBLISH_ONLY_BY` (execution, voice, interface).
- **confidence:** 0.7

##### 10. Language is detected twice and consumed by nobody who could act on it

- **kind:** missing
- **severity:** low
- **claim:** Whisper's language code is now recorded on the turn (the 2026-09-18 fix) and `lang.language_of` decides Farsi-vs-English from the reply's script for TTS, but neither value reaches the model, the percept, the STT hint for the next turn, or a per-person preference.
- **evidence:**
  - simorgh/voice/session.py:625 `clock.language = event.language or ""`; :1893 `language=clock.language` only into the `voice:turns` record
  - simorgh/voice/pipeline.py:349-366 `ask(...)` payload: channel, text, session_id, device, confidence, speaker, speaker_relation, speaker_before, room; no language field; contracts/messages/percept.py:11-28 has no `language` field
  - simorgh/voice/lang.py:24-33 `language_of` is a script-majority test used by the planner/backchannel/TTS routing; `_transcribe` passes the static `self._config.stt_language` (session.py:601-602) every turn
  - session.py:1040-1063 `_LANGUAGE_CODES`: nine Persian turns were discarded in half an hour on 2026-09-17 because of a code/name mismatch, i.e. this path is fragile and unobserved
- **why it matters:** A bilingual house is the stated use case; the cheapest wins (bias the next turn's STT to the language this speaker used last, tell the model which language was heard so it answers in kind) need the value to travel one hop further than it does.
- **recommendation:** Add `language` to the percept payload and to the Conversation/identity contract; keep a per-person `last_language` in the speaker book and pass it as the STT hint for that speaker's next turn; let scaffolds.who_is_here mention it.
- **confidence:** 0.7

##### 11. Family speech is being kept on disk with no retention policy

- **kind:** missing
- **severity:** low
- **claim:** The live config flips `keep_audio` on (code default is off) and every recognised turn's WAV plus transcript JSON is written to workspace/voice/audio with no pruning; only the overheard transcript store purges itself.
- **evidence:**
  - ~/.simorgh/simorgh.toml `[voice] keep_audio = true`; simorgh/voice/config.py:313 `keep_audio: bool = False`
  - `du -sh workspace/voice/audio` -> 68M; `ls workspace/voice/audio | wc -l` -> 842
  - session.py:762-792 `_keep_turn` writes `<stamp>-<turn>.wav` and `.json` (text, confidence, speaker scores); no reader of `audio_dir` prunes (grep: only session.py:780 and pipeline.py:589 write)
  - contracts/overheard.py:29 'Kept 48 hours by default and purged on every write' (transcripts only)
- **why it matters:** It was switched on for calibration (the docstring says so) and is now a permanent, growing archive of children's voices in a gitignored folder on a laptop; the privacy default in the design doc ('audio is not kept unless keep_audio') is technically honoured but practically inverted.
- **recommendation:** Give `_keep_turn` the same 48 h purge the overheard store has (or a `keep_audio_max_files`), and have `voice status` say how many turns are on disk so the flag is not forgotten.
- **confidence:** 0.65


### measurements

- `wc -l` voice: 10,930 total; session.py 1,961; service.py 806; pipeline.py 596; planner.py 584; vad.py 577; speakers.py 487; tts/subproc.py 406
- `wc -l` interface: 10,747 total; dispatch.py 2,234; service.py 1,504; httpapi.py 1,264; dashfeeds.py 1,110; render.py 1,013; persona: 797 total
- `grep -c 'self.turns.state = ' simorgh/voice/session.py` -> 17; `grep -c 'self._pipeline\._' session.py` -> 29; `grep -c 'await ' session.py` -> 127; distinct `self._config.*` knobs read in session.py -> 39; fields in voice/config.py -> 99; `_ask_and_speak` -> 248 lines
- TurnManager reproduction: `after two asks: state=thinking asked=2 superseded=1` / `_stay_quiet(1): reply_ready -> [('speak', 'late; the newer turn is still owed')]` / `state after _stay_quiet(1): listening, asked=2` / `reply_ready(2) -> [('drop_reply', 'the session is listening')]`
- Interface manifest vs reality: `consumes 16`, `produces 12` (AST); `bus.subscribe(` in service.py -> 23, across the package -> 33; readers of `.consumes`/`.produces` anywhere in simorgh/ -> 0
- persona:state stream: 47,784 events, 17.8 MB; by source: decay 44,444 (93%), task.completed 2,516, task.blocked 328, percept.text 288, health.reset 141, task.failed 67; persona:user_model: 1 event ({'preferred_name': 1}); persona `decay_interval_s = 5.0`
- Live config (~/.simorgh/simorgh.toml): `[interface] http_host = "0.0.0.0"`; `[voice] barge_in = false`, `keep_audio = true`, `tts = "kokoro"`, `stt = "auto"`; secrets.toml keys present: SIM_API_TOKEN, REOLINK_HOST, REOLINK_USERNAME, REOLINK_PASSWORD, RING_TOKEN, RING_USERNAME
- HTTP routes: 26 `register_route` calls in httpapi.py + 2 in service.py (WhatsApp) + 5 prefix routes; open (no token) GET paths: /, /api/status, /tv, /dash, /remote, /logo.png, /favicon.ico, /api/wallpapers, /api/dash/data, /api/dash/state, /api/dash/keys, /api/dash/banner, /api/dash/streams, /tv/hls/*, /tv/media/*, /wallpapers/*, /cameras/snap/*; open POST: /api/whatsapp (HMAC-signed)
- `du -sh workspace/cameras` -> 3.8G; `du -sh workspace/voice/audio` -> 68M (842 files); workspace/voice/overheard -> 376K; ledger voice:turns 1.1 MB; task:* streams 2,431 files 6.2 MB
- Test files: tests/simorgh/voice 48, tests/simorgh/interface 33, tests/simorgh/persona 5; no test in tests/simorgh/voice references `_superseded` or `stay_quiet`

