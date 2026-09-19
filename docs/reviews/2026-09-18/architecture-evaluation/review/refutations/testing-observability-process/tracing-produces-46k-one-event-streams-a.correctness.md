# refute:correctness:Tracing produces 46k one-event streams a

*Workflow: review · Phase: Refute · Agent id: `a09b8fdee204783e6` · Tool calls: 18*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "testing-observability-process". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Tracing produces 46k one-event streams a day and no end-to-end trace for a chat or voice turn",
    "kind": "bug",
    "severity": "medium",
    "claim": "The per-root-message trace design with a hand-maintained exclusion list yields mostly single-event streams from topics that were never excluded, while the daily path (a typed or spoken turn) leaves only a two-event think/reply island, so `simorgh trace <id>` cannot reconstruct a bad turn.",
    "evidence": [
      "Measured on ~/.simorgh/ledger/streams: `streams total: 118215  trace: 88356  non-trace: 29859`, `trace in last 24h: 46264`; 400-file sample: 228 streams with 1 line, 54 with 2, 16 with 3, 2 with 14.",
      "One-event roots by type (400 sample): world.camera.event 52, ui.notice 51, ui.hook.received 44, persona.state.changed 42, voice.listening 31, tool.registered 21, voice.transcript 18 -- none of these are in the exclusion list at bus/config.py:60-64 (`system.tick.*`, `system.metrics`, `system.health`, `cognition.provider.status`, `_inbox.#`).",
      "3000-file sample: traces containing cognition.think by length `[(2, 69), (12, 1), (14, 4), (27, 1), (271, 1)]`; traces rooted at voice.transcript `[(1, 130)]` -- every voice turn is an orphan.",
      "session.py:1291 `trace_id=session.task_id` on the think request; the inbound line/transcript and the outbound reply (private inbox, `_inbox.#` sampled to 0.0) never share it.",
      "kernel/cli.py:37 and 242-256 implement `simorgh trace <id>`; grep 'trace' in interface/tui.py returns only traceback-formatting lines (390-400), so no turn ever shows a human its trace id.",
      "kernel/metrics.py:17-27 notes that mining trace streams is already 'a dead end in practice' and adds a separate metrics:history stream."
    ],
    "why_it_matters": "The blueprint's tracing exists to answer 'what happened on that turn'; on this system it answers it only for task sessions, which are the minority path, while costing ~46k files a day of write and retention work on a JSONL ledger that is already 1.4 GB. For a one-laptop, one-family system the interesting unit is the turn, not the message.",
    "recommendation": "Invert the policy: trace only messages that carry a partition_key or task_id (an allow-list of causal topics), which removes the periodic roots without maintaining a denylist. Assign one turn id at the Interface line / voice transcript, pass it as trace_id through session, think, verify and voice.speak, and add a TUI `trace` (or `last`) command that prints the last turn's id and its chain. Measure the file count a day later.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read tracing config, CLI trace command, TUI grep, metrics note |  # section 5 "Tracing"). The zeroed entries are all heartbeats and # periodic broadcasts: they root a trace of their own but cause # nothing, so each one wrote  |
| 2 | Bash | Check session.py trace_id, interface trace ids, ledger stream counts, bus trace writing |  it names Sim. A question missed this way costs one repeat with the name in it; an answer into someone's meeting costs more. Only with speaker recognition on -- |
| 3 | Bash | Inspect think-request trace_id and chat turn path |  # whose assembled memory-retrieval block happens to be # large (large migrated records, a broad query) could # exceed budget even after layers 1-4 -- `allow_su |
| 4 | Bash | Measure trace stream counts, line distribution and root types | trace in last 24h: 43198 line dist (first 600 trace files by ls): 462 1 104 2 28 3 5 14 1 67 ---- one-line root types (same sample): 84 ui.hook.received 72 pers |
| 5 | Bash | Measure think and voice trace lengths; inspect turn entry path for trace_id | think by len [(2, 69), (12, 1), (14, 4), (27, 1), (271, 1)] 2-len think shapes [(('cognition.think', 'cognition.think.reply'), 69)] voice.transcript-rooted [(1, |
| 6 | Bash | Inspect interface trace command, line-to-task path, and inbox reply path | ---- ---- how a line becomes work ---- reply path 9:subscription (`_inbox.<source>.<uuid>`), replies routed point-to-point 85: self._inbox_pattern = f"{INBOX_PR |
| 7 | Bash | Inspect trace command mention, voice publish, and transcript consumers | `project`/`plan <n>` into `plan`; `interest`/`curious` into `interests`; `autonomous`/`discover`/`news`/`growth` into `auto`; `stop`/`quit` into `exit`) and dro |
| 8 | Bash | Find transcript consumers, Message.new default trace id, cli trace body, trace disk size | ---- consumers simorgh/interface/service.py:119: topics.PERCEPT_TEXT_RECEIVED, topics.INTENT_GOAL_STATED, topics.SYSTEM_PAUSE, simorgh/interface/service.py:240: |
| 9 | Bash | Compute trace bytes, read bus.new and Message.new defaults, interface transcript handler | trace files 88356 bytes 144289993 MB 144.3 1.4G /Users/saeed/.simorgh/ledger ---- bus.new def new( self, type: str, payload: dict, *, caused_by: Message \| None  |
| 10 | Bash | Trace the chat turn's causal chain through orchestration and the trace writer's sampling | ---- orchestration consumes percept 12:45- def __init__(self, config: Config \| None = None) -> None: 26:59- async def start(self, ctx: Context) -> None: 54:115- |
| 11 | Bash | Find percept consumer, task-event publish, and type sets in think-bearing traces | ---- who subscribes to percept.text.received simorgh/orchestration/service.py:36: topics.PERCEPT_TEXT_RECEIVED, topics.TOOL_REGISTERED, simorgh/orchestration/se |
| 12 | Bash | Classify think islands by source/kind and inspect chat task creation and task-event trace ids | ---- _on_percept 5:267- session_id = message.payload.get("session_id") or message.id 18:280- worker.run_percept_chat(session_id, text, channel=channel, **who),  |
| 13 | Bash | Trace the chat think origin and the reply-to-interface message and their trace ids | ---- run_percept_chat 13:399- `if session.kind == "chat": publish turn.completed` branch. 16:402- session = Session( 17:403- task_id=session_id, kind="chat", mo |
| 14 | Bash | Check turn.completed publish trace id and its presence in trace streams | ---- _publish helper 2:1939- msg = Message.new(type_, source=self._bus.source, payload=payload, 4:1941- trace_id=session.task_id, clock=self._clock) ---- ledger |
| 15 | Bash | Compare the two chat trace shapes by sequence, payload, emitter and recency | ---- execution think emitters simorgh/execution/service.py:108: topics.UI_NOTICE, topics.COGNITION_THINK, topics.VOICE_SPEAK_REQUEST,) simorgh/execution/vision. |
| 16 | Bash | Check vision think root, outbound speak causation, and whether session ids are shown to users | Exit code 1 ---- vision.py 160-172 side" while this very code was running (live 2026-09-15). """ kinds = [str(k) for k in (kinds or []) if str(k).strip()] kinds |
| 17 | Bash | Check outbound speak causation, CLI session id display, and speak-rooted trace shapes | ---- outbound speak publish sites simorgh/voice/service.py:39: topics.VOICE_STATUS_REQUEST, topics.VOICE_CONTROL_REQUEST, topics.VOICE_SPEAK_REQUEST, simorgh/vo |
| 18 | Bash | Check whether task id reaches the user on turn completion |  await _refused(f"{command.name} failed: {exc!r}", code="command_failed") return if outcome.text: self._out(outcome.text) extra = {} if outcome.task_id: extra[" |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The volume half of the claim is confirmed by measurement and code; the "no end-to-end trace for a turn" half rests on a misread of the data. The 2-event cognition.think islands the finding treats as chat turns are camera-frame vision thinks from execution/vision.py:167 (Message.new with source="execution", purpose "chat", an `images` key, no trace_id), 281 of them in the last 24h. A real typed or spoken turn produces a 12-event trace keyed by the session id (task.started, task.step, memory.retrieve x2 + replies, cognition.think + reply, task.step, task.completed, turn.completed, self.observation), because orchestration/session.py's `_publish` helper (1939-1941) and the think request (1291) both stamp trace_id=session.task_id and run_percept_chat (worker.py:402-403) sets task_id=session_id. So `simorgh trace <session_id>` does reconstruct the cognition/memory/orchestration core of a turn today. What is genuinely missing: (1) the inbound root -- interface/service.py:953 publishes percept.text.received via bus.new with neither caused_by nor trace_id, and voice/pipeline.py:565-566 does the same for voice.transcript, so each is a 1-event orphan stream (16/16 and 130/130 in sample); (2) the outbound voice.speak.request roots its own 2-event stream with causation_id None; (3) no surface shows the session id (uuid4 at service.py:943, never printed; dispatch.py:12 records the `trace` REPL command as dropped; tui.py has only traceback lines). The `_inbox.#` explanation is inert: bus/trace.py:58-66 samples by message.type, which is why think.reply IS traced. The file-churn claim holds (43,198 trace streams in last 24h; 462/600 sampled streams have one line; roots are ui.hook.received, persona.state.changed, world.camera.event, ui.notice, tool.registered, voice.listening, voice.transcript, tool.invoked -- none in bus/config.py:60-64), but the cost is file count, not bytes: trace streams total 144 MB of the 1.4 GB ledger. Not in the known-findings list (the 1.4 GB JSONL item is about the ledger, not the residual trace-root churn after the 2026-09-07 exclusion fix documented at bus/config.py:40-58). Severity should drop because the headline harm -- a bad turn cannot be reconstructed -- is false for the part of the turn that matters.

### evidence

- `ls ~/.simorgh/ledger/streams | wc -l` -> 118215; `| grep -c '^trace'` -> 88356; `find ... -name 'trace*' -mtime -1 | wc -l` -> 43198 (finding said 46264; consistent).
- 600-file sample line distribution: 462 x 1 line, 104 x 2, 28 x 3, 5 x 14, 1 x 67. One-line root types: ui.hook.received 84, persona.state.changed 72, world.camera.event 70, ui.notice 70, tool.registered 43, voice.listening 39, voice.transcript 29, tool.invoked 28 -- none appear in simorgh/bus/config.py:60-64 trace_sample (system.tick.*, system.metrics, system.health, cognition.provider.status, _inbox.#).
- simorgh/bus/config.py:40-58 comment documents the 2026-09-07 measurement (192,332 streams/day) and the denylist fix; the residual 43k/day from un-excluded roots is the new part.
- Python over 8000 trace streams: 2-event think islands = 156 with (source='execution', purpose='chat'); think payload keys ['budget','images','messages','purpose','require_real_provider']. simorgh/execution/vision.py:166-171: `Message.new(topics.COGNITION_THINK, source="execution", payload={"purpose": "chat", ...` with no trace_id -> these are camera-frame thinks, not chat turns. 281 such islands in last 24h.
- Python over 20000 trace streams: 80 streams contain turn.completed, all rooted at their own session id; sequence = ['task.started','task.step','memory.retrieve','memory.retrieve','memory.retrieve.reply','memory.retrieve.reply','cognition.think','cognition.think.reply','task.step','task.completed','turn.completed','self.observation']; sample had channel=voice, stream id == payload session_id. 12 in last 24h. So voice/chat turns are NOT two-event islands.
- simorgh/orchestration/worker.py:402-403 `session = Session(task_id=session_id, kind="chat", ...`; simorgh/orchestration/session.py:1291 `trace_id=session.task_id` on the think request; session.py:1939-1941 `_publish` helper uses `trace_id=session.task_id` for task.started/step/completed/turn.completed.
- simorgh/interface/service.py:953 `await self._ctx.bus.publish(self._ctx.bus.new(topics.PERCEPT_TEXT_RECEIVED, {...}))` -- no caused_by, no trace_id; simorgh/bus/client.py:135-165 shows bus.new falls through to Message.new with a fresh trace when neither is given. Ledger: percept.text.received-rooted streams [(1, 16)], voice.transcript-rooted [(1, 130)] -- inbound is an orphan root.
- simorgh/voice/pipeline.py:565-566 `async def _publish(self, topic, payload): await self._bus.publish(self._bus.new(topic, payload))` -- every voice.listening/transcript/spoken is a fresh root. pipeline.py:573 does record the turn to TURNS_STREAM with trace_id=turn.session_id, which links a voice turn to its 12-event trace.
- Ledger: voice.speak.request-rooted streams [(2 lines, causation_id None) x 11, (1 line) x 1] -- outbound speak is its own island, not chained to turn.completed.
- simorgh/bus/trace.py:58-72 `sample_rate(self, type_name)` / `should_trace` key on message.type, so the `_inbox.#` entry never matches a reply type; cognition.think.reply is present in every island, contradicting the finding's `_inbox.#` mechanism.
- simorgh/interface/dispatch.py:8-16 lists `trace` among REPL commands that were DROPPED; `grep -n trace simorgh/interface/tui.py` -> only lines 390-400 (traceback formatting); simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` is never printed to the user; simorgh/kernel/cli.py:242-256 `_cmd_trace` reads `trace:{trace_id}` and exists only in the offline CLI.
- Byte cost: python sum of trace file sizes -> 88356 files, 144.3 MB; `du -sh ~/.simorgh/ledger` -> 1.4G. The trace churn is a file-count problem (~43k files/day), not a disk-size problem.
- simorgh/kernel/metrics.py:17-27 confirms the 'dead end in practice' note about mining trace streams for system.metrics.

**severity adjustment:** lower

**corrected claim:** Tracing still writes ~43k mostly single-event trace streams a day (77% of sampled streams hold one event) because the per-root trace design relies on a hand-maintained denylist (bus/config.py:60-64) that omits ui.hook.received, persona.state.changed, world.camera.event, ui.notice, tool.registered, voice.listening and voice.transcript; this is file-count churn (88k files, 144 MB), not the bulk of the 1.4 GB ledger. A chat or voice turn is NOT reduced to a two-event island: orchestration stamps trace_id=session.task_id (session.py:1291, 1939-1941) so `simorgh trace <session_id>` yields a 12-event chain from task.started through turn.completed. The two-event cognition.think islands are camera-frame vision thinks (execution/vision.py:167). What is missing at the turn's edges: the inbound percept.text.received (interface/service.py:953) and voice.transcript (voice/pipeline.py:565) are published without caused_by/trace_id and so root orphan one-event streams; the outbound voice.speak.request roots its own two-event stream; and no surface shows the user the session id (dispatch.py:12 dropped the `trace` command; tui.py has none), so the working trace is hard to find rather than absent. The `_inbox.#` exclusion is inert because trace.py samples by message type.

