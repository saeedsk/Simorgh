# refute:proportionality:Chat and voice sessions are per-turn tas

*Workflow: review · Phase: Refute · Agent id: `a67c683c977271b02` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Chat and voice sessions are per-turn task ids; the designed session window (WorkingMemory) has no producer, so 'the conversation' is a global 6-record recency recall",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "There is no session object that spans turns in any channel: the CLI mints a uuid per line, voice per spoken turn, the orchestration `Session` is a task-attempt record whose `restore_session` reads an empty stream for a fresh id, and Memory's `WorkingMemory` (bounded per-session turns, with config fields) has never had a producer -- so the substitute for dialogue history is the 6 most recent episodic records across all speakers and channels (extends the already-known 'no sliding buffer' finding with where the designed slot is).",
    "evidence": [
      "simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` per typed line; simorgh/voice/session.py:888 and voice/pipeline.py:353 per spoken turn; simorgh/orchestration/worker.py:402-405 `Session(task_id=session_id, kind=\"chat\", ...)`; orchestration/resume.py:112 `events = await ledger.read(f\"task:{session.task_id}\")`",
      "simorgh/memory/store.py:51-75 WorkingMemory docstring: 'nothing in the codebase publishes `memory.store{kind:\"working\"}` outside tests'; my grep for `\"working\"` outside simorgh/memory/ finds only the wire enum (contracts/messages/memory.py:9); memory/config.py:15-21 `working_max_turns`/`working_max_chars` bound 'a window that never receives real data'",
      "simorgh/orchestration/context.py:36-66 documents the measured consequence (machine names and a corrected birthday lost within one 22-turn session) and the `_MEMORY_RECENT_K = 6` workaround; context.py:292-294 shows the recency window is only speaker-filtered on the voice channel",
      "simorgh/learning/outcomes.py:63-71 -- the HTTP path that DOES reuse an id ('send the same id every time') then collides with retry/attempt semantics in `_task_facts`"
    ],
    "why_it_matters": "For one family talking to one agent, a dialogue is the primary unit of interaction, and today it is reconstructed from vocabulary-overlap recall plus a recency window shared with every autonomous task. The blueprint already reserved the right slot (working memory keyed by session); building the recency hack instead of wiring it means every channel re-solves continuity differently.",
    "recommendation": "Give each channel a stable conversation id (the REPL's existing `self.session_id`; the voice `device`+speaker; the HTTP client id) separate from the per-turn task id, feed `turn.completed` into `WorkingMemory.add(conversation_id, ...)` in memory/service.py, and have context.py ask `kinds=[\"working\"]` with `filters={\"session_id\": conversation_id}` before the episodic recalls. Keep the per-turn task id for leases and traces.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited lines for session id minting |  )) return # A fresh id per turn, not `self.session_id` (the REPL's own # stable per-instance identity, still used elsewhere e.g. # `dispatch()`'s session_id= f |
| 2 | Bash | Read WorkingMemory and search for producers | #: enough to need it -- the fix was invisible exactly where it mattered #: (observer, 2026-09-10, on the fix from the same morning). TRUNCATION_NOTICE = ("[memo |
| 3 | Bash | Read context.py workaround and outcomes.py collision | simorgh/contracts/messages/memory.py:9:MEMORY_KIND = Enum("working", "episodic", "semantic", "procedural") simorgh/contracts/schema/memory.stored.v1.json:9: "wo |
| 4 | Bash | Check prior reviews, resume carry semantics, HTTP session id | ----prior docs/architecture-audit-2026.md:14:1. **Conversational Amnesia:** While a stable session ID exists, the core orchestration (`orchestration/context.py` |
| 5 | Bash | Check HTTP reuse comment, restore use in chat, episodic producers | ----http `session_id` is optional and, when a caller supplies one, is reused as-is rather than replaced -- 02-system-architecture.md section 6.1's own multi-ses |
| 6 | Bash | Check episodic write grouping, reflection producer, context filters | ----memsvc 26: topics.MEMORY_RETRIEVE, topics.MEMORY_STORE, topics.SYSTEM_TICK_SLEEP, topics.TURN_COMPLETED, 62: self._sub_turn = await ctx.bus.subscribe(topics |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited location reads as claimed. CLI mints `session_id = str(uuid.uuid4())` per typed line (interface/service.py:943, with a comment explaining the REPL's stable `self.session_id` is deliberately not used because reusing it cross-wired pending futures); voice mints per spoken turn (voice/session.py:888, voice/pipeline.py:353); `run_percept_chat` builds a throwaway `Session(task_id=session_id, kind="chat", ...)` (worker.py:402-405). `WorkingMemory` (memory/store.py:51-75) has both Memory-owned sides implemented (`_on_store` special-cases kind="working" at service.py:179-185; retrieve answers kinds=["working"]) and no producer: `grep -rn '"working"' simorgh` outside simorgh/memory/ hits only the wire enum and JSON schemas plus an unrelated string in execution/domainstatus.py:51. Config bounds `working_max_turns=20`/`working_max_chars=8000` (memory/config.py:15-21) are documented as bounding a window with no traffic. context.py:36-66 documents the measured loss (machine names, corrected birthday) and `_MEMORY_RECENT_K = 6`; the recency recall at context.py:253 is `{"query": "", "kinds": ["episodic"], "k": 6}` with no session filter, and speaker filtering applies only when channel == "voice" (context.py:292-294). Autonomous tasks do write episodic records that share that window (reflection/service.py:347 stores kind="episodic"; the context.py comment cites a code-patch record outranking the user's own fact). learning/outcomes.py:63-71 confirms the HTTP reused-id collision with attempt/run semantics. Two corrections that do not weaken the finding: (1) `restore_session` is called only on the task-claimed path (worker.py:302), not on the chat path at all, so chat gets no restore rather than an empty one; (2) Memory's episodic write already tags each record with the turn's `session_id` (memory/service.py:245) and context.py already does tag-filtered recalls (context.py:265 for person:<name>), so a conversation-keyed recall is even closer to wired than the finding says: a stable conversation id on the percept plus one tag-filtered recall would work without touching WorkingMemory. On the proportionality lens: for one family on one laptop, dialogue continuity is the primary interaction and the recommended fix is a field plus one recall, smaller than the recency hack it replaces, so the recommendation is not disproportionate. The genuinely new material versus prior reviews (which already name 'no sliding buffer' and 'map to the stable session_id') is: the per-turn id in every channel means no key exists to map to; the designed WorkingMemory slot has both consumer sides done; and the one channel that does reuse an id collides with attempt accounting.

### evidence

- simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` per typed line; lines 933-941 explain why the REPL's stable `self.session_id` is not reused (pending-future cross-wiring, milestone 106)
- simorgh/voice/session.py:888 `session_id = str(uuid.uuid4())` in `_ask_and_speak`; simorgh/voice/pipeline.py:353 `session_id = session_id or str(uuid.uuid4())`
- simorgh/orchestration/worker.py:402-405 `Session(task_id=session_id, kind="chat", ...)` then `self.run(session, ...)` directly; `restore_session` is only called at worker.py:302 on the task-claimed path (grep 'restore_session' simorgh/orchestration/worker.py -> lines 31, 302)
- simorgh/memory/store.py:51-75 WorkingMemory docstring: 'What is still missing is a producer'; simorgh/memory/service.py:179-185 `if payload["kind"] == "working": self.engine.working.add(...)`
- `grep -rn '"working"' simorgh | grep -v '^simorgh/memory/'` -> contracts/messages/memory.py:9, five contracts/schema/*.json entries, execution/domainstatus.py:51 (unrelated string); no producer
- simorgh/memory/config.py:15-21 `working_max_turns: int = 20`, `working_max_chars: int = 8_000` with comment 'no real producer yet'
- simorgh/orchestration/context.py:66 `_MEMORY_RECENT_K = 6`; context.py:253 `{"query": "", "kinds": ["episodic"], "k": _MEMORY_RECENT_K}` (no session filter); context.py:292-294 speaker filter only when channel == "voice"
- simorgh/reflection/service.py:347 stores `"kind": "episodic"` for autonomous task critiques, so the recency window is shared with autonomous work
- simorgh/learning/outcomes.py:63-71: chat task_id IS session_id; HTTP 'send the same id every time' appends turn 5 to the same task stream; measured $0.000629 turn billed as $0.001256
- simorgh/interface/httpapi.py:1100-1130 documents the reused session_id path and 409 on concurrent reuse; httpapi.py:1128 `session_id = session_id or str(uuid.uuid4())`
- simorgh/memory/service.py:245 `tags = [payload.get("session_id", "")] + [f"person:{name}" ...]` -- episodic records already carry the session id as a tag; context.py:265 already uses tag filters for person recall
- docs/architecture-audit-2026.md:14,30 and docs/architecture-third-opinion-2026-09-18.md:101,150 already name the missing sliding buffer but not the per-turn id in every channel, the WorkingMemory slot, or the outcomes.py collision

**severity adjustment:** keep

**corrected claim:** As claimed, with two refinements: `restore_session` is not invoked on the chat path at all (worker.py:302 is task-claimed only), so chat sessions get no restore rather than an empty one; and Memory already tags each episodic record with the turn's session_id (memory/service.py:245) while context.py already performs tag-filtered recalls (context.py:265), so a stable per-channel conversation id plus one tag-filtered episodic recall would restore continuity even before wiring WorkingMemory.

