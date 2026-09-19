# refute:correctness:Chat and voice sessions are per-turn tas

*Workflow: review · Phase: Refute · Agent id: `a1e7eec432b66b48f` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "cognition-memory-selfmodel". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read cited session-id lines |  )) return # A fresh id per turn, not `self.session_id` (the REPL's own # stable per-instance identity, still used elsewhere e.g. # `dispatch()`'s session_id= f |
| 2 | Bash | Check WorkingMemory producer claim | #: enough to need it -- the fix was invisible exactly where it mattered #: (observer, 2026-09-10, on the fix from the same morning). TRUNCATION_NOTICE = ("[memo |
| 3 | Bash | Check remaining evidence and known-findings overlap | simorgh/contracts/messages/memory.py:9:MEMORY_KIND = Enum("working", "episodic", "semantic", "procedural") simorgh/contracts/schema/memory.stored.v1.json:9: "wo |
| 4 | Bash | Verify HTTP id reuse, recency query scope, and known-finding overlap | 162: self.session_id = str(uuid.uuid4()) 390: ctx.logger.info("interface.started", session_id=self.session_id) 752: session_id=self.session_id, vitals=self.vita |
| 5 | Bash | Read recency query construction, HTTP/Telegram id policy, memory retrieve |  async def _memory_block(self, query: str, session: Session) -> tuple[str, str]: """`(what to show, why there is nothing)`. Two recalls, not one, and they answe |
| 6 | Bash | Check whether a reused session id carries prior turns into the prompt | 31:from .resume import restore_session 302: await restore_session(session, self._ledger) ---- # before it are summarised in it; only later ones need listing. cu |
| 7 | Bash | Check whether carried note reaches chat prompts on reused-id channels | simorgh/orchestration/context.py:137: Measured 2026-09-07: every think call carried both twice -- 198 of simorgh/orchestration/context.py:170: if session.carrie |
| 8 | Bash | Check carried-note prompt placement and episodic session tagging |  # no longer had the request in front of it -- only its own tool # calls and their output. A patch session that applied a file and # then stopped had, by then,  |
| 9 | Bash | Confirm restore_session runs for chat sessions and episodic session tagging |  kind = str(task.get("kind") or kind) mode = task.get("mode", "execute") description = await self._full_description(task) profile = profiles.for_claimed(kind, m |
| 10 | Bash | Locate which worker method calls restore_session | 302: await restore_session(session, self._ledger) 380: async def run(self, session: Session, *, user_text: str = "") -> Outcome: 387: async def run_percept_chat |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core mechanism is true of the code today: the CLI mints a uuid per typed line, voice mints one per spoken turn, the chat Session is a task-attempt record keyed by that per-turn id, WorkingMemory has both consumer sides built and no producer anywhere outside tests, and the stand-in for dialogue history is a recency recall of 6 episodic records with no session, channel or speaker filter (speaker-filtered only on voice). Two corrections. (1) "no session object that spans turns in any channel" is overstated: Telegram, WhatsApp and HTTP each keep a stable session id per chat/wa_id/client and reuse it on every turn, and Memory's episodic write tags every record with that session_id -- so the stable key the recommendation asks for already exists on three channels and in the store; nobody filters the recency recall by it. (2) The resume.py evidence is misdirected: `restore_session` is called only from `_on_claimed` (worker.py:302), never from `run`/`run_percept_chat`, so it does not "read an empty stream" on the chat path -- chat sessions simply never restore anything. The finding also substantially overlaps the already-known "no in-prompt sliding dialogue buffer" item (docs/architecture-audit-2026.md:14,30-31 even names the stable session_id and proposes mapping history to it). What is materially new and verified: the designed slot is Memory's WorkingMemory (no known doc mentions it), the recency window is global across all channels and autonomous tasks, and the reused-id channels already carry the key that would scope it. Severity stays medium.

### evidence

- simorgh/interface/service.py:943 `session_id = str(uuid.uuid4())` per typed line, with the comment at :933-941 explaining why `self.session_id` (stable, :162) is deliberately not used
- simorgh/voice/session.py:888 `session_id = str(uuid.uuid4())` per spoken turn; simorgh/voice/pipeline.py:353 `session_id = session_id or str(uuid.uuid4())`
- simorgh/orchestration/worker.py:402-405 `Session(task_id=session_id, kind="chat", ...)`; restore_session is invoked only at worker.py:302 inside `_on_claimed`, not in `run` (:380) or `run_percept_chat` (:387) -- chat turns never restore a stream
- simorgh/memory/store.py:51-75 WorkingMemory docstring: both Memory-side halves done, 'nothing in the codebase publishes memory.store{kind:"working"} outside tests'; simorgh/memory/config.py:15-21 same; memory/service.py:179-186 the `kind=="working"` store branch
- Command: grep -rn '"working"' simorgh | grep -v '^simorgh/memory/' -> only contracts/messages/memory.py:9, five JSON schemas, and an unrelated string in execution/domainstatus.py:51; grep -rln 'kind="working' simorgh tests -> simorgh/memory/store.py and tests/simorgh/memory/test_service.py only
- simorgh/orchestration/context.py:36-66 the measured 22-turn loss and `_MEMORY_RECENT_K = 6`; context.py:251-254 the recent recall is `{"query": "", "kinds": ["episodic"], "k": 6}` with no filters; context.py:292-294 speaker filter applied only when session.channel == "voice"
- COUNTER: simorgh/interface/telegram.py:201-205 and simorgh/interface/whatsapp.py:197-201 reuse one session_id per chat_id/wa_id; simorgh/interface/httpapi.py:1068,1100-1108 reuses a client-supplied session_id ('sends the same id every time'); simorgh/memory/service.py:245 tags every episodic record with `payload.get("session_id")` -- a stable conversation key already exists on three channels and in the store
- simorgh/learning/outcomes.py:63-71 confirms the HTTP reused-id / attempt-semantics collision as stated
- Already-known overlap: docs/architecture-audit-2026.md:14 'While a stable session ID exists, the core orchestration lacks an in-prompt sliding dialogue buffer'; :30-31 recommends mapping the window to the stable session_id. grep -i 'workingmemory\|working memory' over architecture-audit-2026.md, architecture-review-2026-09-18.html, architecture-third-opinion-2026-09-18.md -> no hits

**severity adjustment:** keep

**corrected claim:** The CLI and voice channels mint a fresh task id per turn and the chat Session is a per-turn attempt record that never restores a stream (restore_session runs only on the claimed-task path), so on those channels nothing spans turns. Telegram, WhatsApp and HTTP do keep a stable per-conversation session id and Memory already tags every episodic record with it, but no consumer uses that key: the designed per-session window, Memory's WorkingMemory, has both Memory-side halves built and no producer anywhere outside tests, and context.py substitutes a global 6-record episodic recency recall that is unfiltered by session or channel (speaker-filtered only on voice). This extends the known 'no sliding dialogue buffer' finding by naming the designed slot and showing that the conversation key needed to scope it already exists on three channels.

