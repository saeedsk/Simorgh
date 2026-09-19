# read:agent-loop-orchestration

*Workflow: review · Phase: Read · Agent id: `a84c731b55bc166ab` · Tool calls: 62*

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
  
  
  CONCERN: the agent loop itself -- Orchestration workers, sessions, step budgets, context/prompt assembly, tool routing, profiles, scaffolds, delegation, resume.
  Read simorgh/orchestration/ thoroughly (service.py, worker.py, session.py, context.py, profiles.py, tools.py, scaffolds, delegation, claims/leases) and how it calls cognition (cognition.think request/reply over the bus) and tools (action.proposed -> guardian -> execution -> action.result).
  Questions: Trace one chat turn and one code task end to end through the actual code; how many bus round-trips and ledger writes does ONE tool call cost, and is that latency structurally necessary? How does the model see tool results (there was a 200-char truncation bug once -- what is the limit now)? How is the prompt assembled -- system prompt size, what is injected each step, is there prompt caching-friendly stable prefix ordering? How do profiles pick tools and is the routing declarative or scattered? What does resume-from-ledger actually replay? Is the worker/lease/claim design (consumer groups, heartbeat leases) proportionate for a single process? Where is the loop's correctness fragile (retries, step budget, memory carried across attempts)? Evaluate the agent-loop design against how state-of-the-art agent harnesses are built in 2026 (single loop, tool results as messages, context compaction, sub-agents).
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List orchestration package files with line counts | __init__.py __pycache__ api.py claims.py config.py context.py profiles.py progress.py README.md resume.py scaffolds.py service.py session.py tools.py worker.py  |
| 2 | Bash | Read orchestration README, init, config | # simorgh/orchestration The harness loop (16 section 5): `Worker` claims one `task.available` command at a time (consumer group `workers`), runs a `SessionRunne |
| 3 | Bash | Read orchestration api and service | """Dataclasses and protocols internal to `simorgh.orchestration` (docs/blueprint/subsystems/16-orchestration.md section 3.4). Not part of `simorgh.contracts` -- |
| 4 | Bash | Read orchestration worker | """The `Worker` (16 section 3.4/5): claims one `task.available` command at a time (consumer group `workers`, competing-consumer -- multiple Worker instances sha |
| 5 | Bash | Read session.py part 1 | """The session state machine (16 section 5): CLAIMED -> GATHER -> THINK -> (final -> VERIFY -> COMPLETED \| tool_calls -> PROPOSE -> GATHER) with a bounded evalu |
| 6 | Bash | Read session.py part 2 | # # Kept a little above Execution's own limits so the tool's timeout is # what fires, with its real error, rather than this one guessing. When # `test_timeout_s |
| 7 | Bash | Read session.py part 3 |  session.worktree = "" first = next((line.strip() for line in (summary or "").splitlines() if line.strip()), "landed") return Outcome( "completed", result_summa |
| 8 | Bash | Read session.py part 4 (rest) | <persisted-output> Output too large (39.4KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 9 | Bash | Read session.py lines 1250-1560 |  now=_epoch(self._clock), ) + (f"\n\n{session.extra_rules}" if getattr(session, "extra_rules", "") else ""), # Live-caught: this request never actually asked Co |
| 10 | Bash | Read session.py lines 1560-end |  step = Step(session.next_step_no(), "gather", f"reground{' (context too large)' if forced else ''}: {before} messages -> {len(session.messages)}; " f"next: {no |
| 11 | Bash | Read context.py | """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the self summary a |
| 12 | Bash | Read profiles.py | """Per-kind Profiles (16 section 5). v1 kept its own per-agent step ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); these are the sam |
| 13 | Bash | Read tools.py | <persisted-output> Output too large (35.7KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 14 | Bash | Read resume, progress, claims | """What a Session inherits from the `task:<id>` stream before it runs. Two different situations look alike from here -- a task whose last worker died mid-run, a |
| 15 | Bash | Read scaffolds.py | <persisted-output> Output too large (44.4KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 16 | Bash | Read tools.py middle |  "self_map": ("read_only", False), "web_fetch": ("read_only", True), "web_search": ("read_only", True), "render_page": ("read_only", True), "browse_page": ("rev |
| 17 | Bash | Read tools.py end |  "a period on one line: today, yesterday, week, month, or a number of days. Costs it " "hour by hour against the tariff, which is the point of a time-of-use rat |
| 18 | Bash | Read scaffolds.py first half |  _UNAVAILABLE.pop(name, None) return _UNAVAILABLE[name] = (detail, tuple(tools)) def unavailable_note(offered: tuple[str, ...] \| list[str]) -> str: """What to t |
| 19 | Bash | Read scaffolds.py second half | A single file, a short script, a quick edit: just do it here.""" # The creator, 2026-09-09, after watching another agent solve "real # estate listings, no API k |
| 20 | Bash | List cognition package and read parser head | __init__.py __pycache__ api.py assembler.py budget.py compaction.py config.py parser.py providers router.py service.py tokens.py 2297 total """Output parsing: m |
| 21 | Bash | List bus package and grep client for publish/request/ledger | __init__.py __pycache__ api.py backends client.py config.py enforcement.py factory.py metrics.py policy.py README.md router.py service.py trace.py 1148 total 8: |
| 22 | Bash | Read bus trace module | """The trace writer: every message -> Ledger stream `trace:<trace_id>`, sampled per type (docs/blueprint/subsystems/01-bus.md section 5.6; 03 section 5 "Tracing |
| 23 | Bash | Read runtime config and list ledger dir | [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2.8 min_confidence =  |
| 24 | Bash | Grep guardian and execution service for the action flow | 2:Kernel/Bus enforcement lets subscribe to `action.proposed`. Runs every 98: topics.ACTION_PROPOSED, 112: topics.ACTION_APPROVED, 134: # `action.proposed` -- wh |
| 25 | Bash | Outline cognition service handlers | 33:# `CognitionThink.expected` is a flat wire enum (text\|tool_calls\|edit_blocks\| 38:def _expected_spec(payload: dict) -> dict: 39: expected = payload.get("expec |
| 26 | Bash | Read cognition assembler head | """Prompt assembly (docs/blueprint/subsystems/04-cognition.md section 5, "Prompt assembly order"): ordered blocks, each `protected` (never compacted -- principl |
| 27 | Bash | Read bus config and client publish/request | """Bus configuration (docs/blueprint/subsystems/01-bus.md section 3.5). Loaded from the `[bus]` section of `simorgh.toml` by the Kernel; every field has a worki |
| 28 | Bash | Read guardian _on_proposed |  async def _on_proposed(self, message: Message) -> None: p = message.payload action_id = p["action_id"] fingerprint = self._fingerprint(p) seen = self._decided. |
| 29 | Bash | Read execution _on_approved |  async def _on_approved(self, message: Message) -> None: approved = message.payload action_id = approved["action_id"] now = self._ctx.clock.now() args, task_id, |
| 30 | Bash | Outline planning service and store | 53: topics.TASK_CLAIM, 77: topics.TASK_CLAIM_REPLY, 151: priority_weights=self.config.priority_weights, lease_seconds=self.config.lease_seconds, 162: topics.TAS |
| 31 | Bash | Interface chat entry, ledger config, and ledger stream counts | 45:and `_handle_chat`'s heartbeat update the footer in place for an 114: topics.SYSTEM_HEALTH, topics.GUARDIAN_POSTURE_CHANGED, topics.TURN_COMPLETED, 119: topi |
| 32 | Bash | Count orchestration tests and peek memory retrieve | __init__.py __pycache__ fakes.py harness.py test_api_and_profiles.py test_attempts.py test_cancel.py test_catalog_channels.py test_claims.py test_clean_retries. |
| 33 | Bash | Read cognition tool instruction block and _on_think | # `web_fetch` is enough on its own. **Second live-catch, same day**: a # name alone was NOT enough for `propose_mcp_server` -- its one argument # has real inter |
| 34 | Bash | Cognition budgets, routes, caching support, native tools | 55: only_purposes: tuple = () 70: # default model. It leads the order, so it is what answers unless it is 73: provider_order: tuple[str, ...] = ("together", "cl |
| 35 | Bash | Execution config limits, proposal fetch, registration payload | 53: max_concurrent_actions: int = 4 54: default_timeout_s: float = 60.0 55: max_output_bytes: int = 65536 56: blob_inline_threshold_bytes: int = 4096 163: test_ |
| 36 | Bash | Ledger stream prefix counts and dump newest task stream | 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice 1 system.jsonl 1 schedule.js |
| 37 | Bash | Ledger JSONL append and fsync behaviour | __init__.py __pycache__ dynamodb.py jsonl.py memory.py sqlite.py 1:"""The default backend: one append-only JSONL file per stream, fsync'd 4:was mid-write, and a |
| 38 | Bash | Read interface _handle_chat |  async def _handle_chat(self, text: str) -> None: # A paused system runs no sessions, so no answer is coming. This # used to publish the percept and then wait ` |
| 39 | Bash | Read cognition compaction layers | """The graduated context-compaction pipeline (docs/blueprint/subsystems/ 04-cognition.md section 5, "Compaction pipeline"; docs/KnowledgeBase/ harness-01-claude |
| 40 | Bash | Planning store backend, lease scan, and config | 21:# `is_ref` through the client, not `ledger.blobs`: a subsystem may 22:# import `ledger.client` and nothing else of the Ledger. 23:from simorgh.ledger.client  |
| 41 | Bash | Find a recent task stream with tool calls and count its ledger and trace events | TASK STREAM: task%3A01d310a3-dbaa-4436-87d3-aaed1b1df22c.jsonl events: 7 tool steps: 4 task.started \| \| task.step \| cam_list \| 2. Front Window NVC-B12M online 6 |
| 42 | Bash | Inspect one action stream and the execution/cognition streams | action%3Ac15efdc8dd7f.jsonl 3 action%3Ac15efdc8dd7f.jsonl received ['proposal'] decided ['kind', 'layer'] verified ['outcome', 'reason'] ---- inflight execution |
| 43 | Bash | Planning refresh_lease, cognition purpose budgets, execution inflight stream |  async def refresh_lease(self, task_id: str, lease_seconds: float) -> None: task = self.index.tasks.get(task_id) if task is None or task.lease is None: return s |
| 44 | Bash | Count guard regexes, comment density, and the tool-name registries | 11 comment lines: 527 total lines: 1942 docstring-ish lines: 1051 --- registries keyed by tool name --- 320 simorgh/contracts/toolargs.py simorgh/contracts/tool |
| 45 | Bash | Read Together provider request construction |  def model(self) -> str: return self._model def available(self) -> bool: return bool(self._api_key) async def complete( self, messages: list[dict], *, tools: li |
| 46 | Bash | Memory retrieve location, chat timeout, module boundary rule | simorgh/memory/store.py:238: async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict \| None) -> tuple[list[MemoryItem], bool]: 88: chat_ |
| 47 | Bash | Measure trace-stream fragmentation and lease writes per step on a real task | trace streams: 88356 1 events: 67421 2 events: 16517 3 events: 4011 8 events: 1 >=10 events: 406 ---- a real task (non-chat) stream: lease_refreshed vs task.ste |
| 48 | Bash | Read memory retrieve implementation |  async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict \| None) -> tuple[list[MemoryItem], bool]: """Rank what is remembered against `q |
| 49 | Bash | Check what prior reviews already said about the agent loop | marker audit:0 review:0 function calling\\|native tool\\|tool_use\\|tool-use audit:0 review:0 flatten audit:1 review:0 prompt cach\\|cache audit:0 review:0 resume a |
| 50 | Bash | Check tests for crash-resume transcript expectations | 19:from simorgh.orchestration.resume import carried_note, restore_session 62: self.assertIn("Attempt 1 ended blocked: step budget exhausted", session.carried) 6 |
| 51 | Bash | Together output budget and parser's first-marker rule | 133: body["max_tokens"] = self._room_to_answer(int(max_tokens)) 134- if self._reasoning_effort: 135- body["reasoning_effort"] = self._reasoning_effort 136- 137- |
| 52 | Bash | Measure rendered system-prompt sizes per profile | CHAT/cli tools= 72 task_rules= 13013 chars ~ 3254 tok \| tool_instructions= 10095 chars ~ 2524 tok \| total ~5778 tok VOICE_CHAT/voice tools= 58 task_rules= 16700 |
| 53 | Bash | Provider order construction, session_id in think payload, ollama context |  assembly_request_timeout: float = 2.0 # persona.voice / self.summary -- omitted on timeout, not fatal #: What `from_mapping` had to ignore, logged by the servi |
| 54 | Bash | Provider order semantics and Claude CLI provider prompt shaping |  num_ctx: int = 0 # A separate local model for calls that carry pictures (a camera still, # a screenshot). The text model above cannot see one; without this, Si |
| 55 | Bash | Churn on session.py and kernel boot layer order |  80 80 --- session.py churn (last 30 days) --- added 2091 deleted 149 --- kernel boot layers --- |
| 56 | Bash | Check whether Execution restricts chat-session writes to workspace | simorgh/execution/tools.py:1791: if ctx.task_id and kind != "chat": simorgh/execution/vision.py:169: "purpose": "chat", simorgh/execution/tools.py:1791: if ctx. |
| 57 | Bash | Look for tests covering chat sessions with uncommitted edits | tests/simorgh/orchestration/test_session_flows.py:38: session = Session(task_id="t-announce", kind="chat", mode="execute", profile=profiles.CHAT) tests/simorgh/ |
| 58 | Bash | Provider order placement for configured providers and kernel layers |  if "provider_order" in raw: kwargs["provider_order"] = tuple(raw["provider_order"]) if "routes" in raw and isinstance(raw["routes"], Mapping): kwargs["routes"] |
| 59 | Bash | Count chat sessions that ended blocked with uncommitted edits in the ledger | uuid-keyed (chat) task streams: 2328 \| task.edits_kept events: 2 \| task.blocked with 'uncommitted': 2 |
| 60 | Bash | Confirm the chat write-scope check and list the chat sessions that orphaned edits |  if not goal: return ToolResult(ok=False, error="refused: say what the task is for") # A chat turn is a session with a task id too (its percept's # session id). |
| 61 | Bash | Pin exact line numbers for every citation | Exit code 1 (eval):1: defining function based on alias `g' (eval):1: parse error near `()' |
| 62 | Bash | Pin exact line numbers for every citation | simorgh/cognition/service.py:358: purpose, think_messages, tools=None, simorgh/cognition/service.py:340: think_messages.append({"role": "user", "content": compa |

## Structured reply

**concern:** The agent loop itself: Orchestration workers, sessions, step budgets, context/prompt assembly, tool routing, profiles, scaffolds, delegation, resume

**summary of what is actually there:** A chat turn enters at interface/service.py:917 (_handle_chat publishes percept.text.received and waits up to 420s on a future); orchestration/service.py:_on_percept hands it to a Worker as a detached task; worker.py:run_percept_chat builds an ephemeral Session (kind=chat, profile CHAT or VOICE_CHAT) and runs SessionRunner._run (session.py:875), a ~400-line while loop: publish a task.step heads-up, _think (context.py Assembler gathers 2-3 memory.retrieve request/replies with a 0.25s timeout, scaffolds.render builds task_rules, then one cognition.think request with a 200s timeout), then either _propose_and_await (session.py:1613: publish action.proposed, subscribe to result/denied/needs_human via _EventWaiter :488, wait a hand-tabled per-tool timeout from _ACTION_TIMEOUTS :407) or a chain of regex "honesty" guards on the final text, then Outcome and Worker._report (ledger append + task.completed + memory.store + turn.completed). A code task is the same loop entered from task.available via a task.claim request/reply to Planning (worker.py:279), restore_session from the task:<id> ledger stream (resume.py), a heartbeat coroutine (worker.py:350), worktree_open/worktree_land/worktree_close proposed through the same Guardian->Execution path, and _verify_then_finish (verify.requested with a 300s wait, bounded revisions). Cognition (cognition/service.py:250 _on_think) fetches persona.voice, self.summary and (chat only) a world.env.query user_profile per call, then compacts and sends exactly two system messages plus ONE user message containing the whole transcript flattened as "[role] content" text (assembler.py:70, service.py:340); it calls the provider with tools=None (service.py:358) and parses the FIRST "TOOL_NAME: arg" marker line out of the reply (parser.py:345-381, extra markers reported as dropped). Tool results reach the model as a plain user message "Result of <tool>:\n<summary>" (session.py:1045) bounded to 8,000 chars with a cut notice (session.py:1597-1611); Execution's preview cap is 65,536 bytes and Cognition's layer-1 cap is 2,000 tokens per result, so the old 200-char truncation is gone and the three limits are consistent. Guardian records "received" and "decided" on action:<id> (guardian/service.py:547,583) and issues an HMAC token; Execution reads the proposal back from the ledger (execution/service.py:719), appends "verified" plus inflight started/finished, runs the tool, publishes action.result; Planning appends lease_refreshed on every task.step and heartbeat (planning/service.py:351-356, store.py:355). Profiles are static tuples in profiles.py (CHAT: 72 tools offered, 20 steps, 16k output tokens, verify off; VOICE_CHAT: 58 tools, 6 steps; PATCH/SKILL: 20 steps, worktree, verify + 2 revisions; RESEARCH 14; PLAN 8). Routing knowledge is spread over six tool-name-keyed tables in three packages (contracts/toolargs.py MARKER_* x6, orchestration/tools.py _TOOL_POLICY and _MARKER_ARG_HINT, scaffolds.py _TOOL_NOTES, session.py _ACTION_TIMEOUTS, cognition/parser.py _CODE_BEARING_MARKERS) plus Execution's own registry. Delegation (in-process child research session), re-grounding via a progress note, parallel read-only batches, clean revisions and strong-tier escalation are all implemented in session.py but all default OFF in config.py:60-74, and ~/.simorgh/simorgh.toml has no [orchestration] section, so the live loop runs one tool per step with an unbounded transcript until context_too_large forces a reground. Resume (resume.py) rebuilds steps and budget from the ledger, and for retries renders earlier attempts into a carried note; for a crash it restores the step count but not the transcript.

### strengths

- Attempts are first-class and budgets bound one attempt, not the task: resume.py splits the task:<id> stream into attempts, carries a rendered note of earlier attempts into the next (carried_note), and task.edits_kept lets a later attempt inherit an uncommitted patch instead of redrafting it (resume.py:41-108, session.py:846). This is a better retry model than most harnesses have.
- The harness, not the model, enforces 'never leave a broken change in the tree': SessionRunner.run (session.py:672-750) converts completed-with-uncommitted-edits into blocked, discards or keeps edits deterministically, and closes worktrees on terminal outcomes.
- The claim check is designed asymmetrically and correctly: claims.py only fires on first-person past-tense claims about tools the profile actually had, skips retries (complete_log=False), and treats false negatives as acceptable (claims.py:1-60).
- Tool results are cut honestly: _bound_for_model (session.py:1601-1611) appends 'cut at N of M chars' and a READ_FILE range hint, and the 8,000-char cap lines up with Cognition's 2,000-token per-result layer-1 cap (cognition/config.py:114).
- Guardian's approval is not trusted from the wire: Execution re-reads the proposal from the ledger (execution/service.py:719) and HMAC-verifies the token against the real args before running; the action id is claimed before the first await to defeat redelivery races (guardian/service.py:463-500).
- Cancellation is cooperative at step boundaries (worker.py:_on_cancel) so an applied-but-uncommitted edit is never abandoned mid-step, and read-only waits poll the cancel flag at 200ms (session.py:1633-1642).
- Profiles are data (profiles.py) and the tool.registered/tool.probed replay in service.py:_replay_registrations closes the boot-order race honestly, with the failure mode documented in place.
- The progress-note compaction design (progress.py: goal/done/learned/next JSON, transcript replaced by note plus last N steps, note persisted as task.progress and reused by resume) is the right shape for long-run context; it only needs to be switched on.
- Memory degradation is honest: MEMORY_UNAVAILABLE_NOTE (context.py:64) tells the model 'could not look' distinctly from 'nothing matched', and _why_not reports the real error code.

### findings

##### 1. Tool calls are regex-parsed text markers; native function calling is never used

- **kind:** wrong-design
- **severity:** critical
- **claim:** Every provider call passes tools=None and the model is asked to write 'TOOL_NAME: argument' as the first line of its reply, which a regex parser turns into at most one call per message, so the entire tool protocol (argument splitting, multi-line payloads, JSON second lines, dropped markers, invented markers, narrated calls) is reimplemented by hand and keeps breaking per tool.
- **evidence:**
  - simorgh/cognition/service.py:358 `purpose, think_messages, tools=None,`
  - simorgh/cognition/service.py:67-104 _tool_instruction_block: 'write its name in capitals, a colon, then your argument, as the very first line of your reply'
  - simorgh/cognition/parser.py:345-381 _parse_markers runs the first marker; :377 `call["dropped_markers"] = extra`
  - simorgh/orchestration/scaffolds.py:~700 'One tool call per message: write a single marker line ... Anything after the first marker is ignored.'
  - Six tool-name-keyed tables must agree for one tool to work: simorgh/contracts/toolargs.py:31,119,125,157,167,256 (MARKER_ARG_KEY, MARKER_NO_ARGS, MARKER_SPLIT_FIRST_LINE, MARKER_JSON_REST, MARKER_CODE_REST, MARKER_KEY_VALUES); simorgh/orchestration/tools.py:29 _TOOL_POLICY, :268 _MARKER_ARG_HINT; simorgh/orchestration/scaffolds.py:58 _TOOL_NOTES; simorgh/orchestration/session.py:407 _ACTION_TIMEOUTS; simorgh/cognition/parser.py:47 _CODE_BEARING_MARKERS
  - parser.py:47-120 comments record five separate days on which a newly added tool silently lost every line after its first because it was missing from _CODE_BEARING_MARKERS
  - session.py has 11 compiled guard regexes (grep -c re.compile = 11): _ECHO_SHAPES, _MARKER_LINE, _TV_CLAIM, _TV_ASK, _DASH_ON_TV, _COMMIT_CLAIM, _PROMISED_BEHAVIOUR, _NOTED_PRONUNCIATION, _NAMES_SIM, plus unhonoured_marker/invented_markers, each documented as a live-caught marker failure
  - Execution already announces description/read_only/reversibility on tool.registered (execution/service.py:169-179) and holds args_schema per tool, but Orchestration cannot read it (module-boundary rule) and rebuilds it by hand
  - grep -rn 'tools=None|tools:' simorgh/cognition/providers/*.py: every provider accepts a `tools` argument and none is ever given one
- **why it matters:** This is the root cause behind most of the loop's accreted complexity: one-call-per-message (so a 4-lookup question costs 4 model round trips, each with ~6k tokens of system prompt), argument-shape bugs per tool, and the whole class of 'the model narrated a call instead of making one' fabrications. In 2026 every serious provider (Together's OpenAI-compatible API, Anthropic, Gemini, Ollama) returns structured tool_calls with schema-validated JSON arguments and supports parallel calls; the harness is fighting the model's training instead of using it.
- **recommendation:** Make tool.registered carry Execution's args_schema and description, have Cognition pass them as native `tools` to the provider, and have the router return structured tool_calls; keep the marker parser only as a fallback for a provider that reports no tool support. Then delete MARKER_*, _MARKER_ARG_HINT, _CODE_BEARING_MARKERS and the marker-shape guards (unhonoured_marker, invented_markers, _transcript_echo). Timeouts and policy (reversibility/network) should ride on the same registration event so _ACTION_TIMEOUTS and _TOOL_POLICY become a cache of what Execution said, not a second source of truth.
- **confidence:** 0.95

##### 2. The whole transcript is flattened into one user message; tool results are never tool-role messages

- **kind:** wrong-design
- **severity:** critical
- **claim:** Cognition joins every message of session.messages into a single '[role] content' string and sends it as one user turn after two system messages, so the model never sees an assistant/tool alternation and is asked to continue a conversation whose last turn it cannot distinguish from its own.
- **evidence:**
  - simorgh/cognition/assembler.py:70 `conversation = "\n\n".join(f"[{m.get('role', 'user')}] {m.get('content', '')}" for m in messages)`
  - simorgh/cognition/service.py:329-340: think_messages = [system: protected_text], [system: tool_instructions], [user: compacted.text]
  - simorgh/orchestration/session.py:1029-1050: tool results are appended as {'role':'user','content':'Result of read_file:\n...'} and the code comment says it was changed from an assistant message because the model 'lost the thread'; the fix never reached the provider because the assembler re-flattens it
  - simorgh/cognition/providers/together.py:126-130 forwards messages role-for-role, so the flattening is purely self-inflicted upstream
  - session.py:161-175 _ECHO_SHAPES exists to catch the model reproducing '[tool_call X]' / '[result message]' text, which is exactly the shape the flattened transcript teaches it
- **why it matters:** Models are trained on real tool-use turns; a flattened blob defeats that training (hence the fabricated results the guards catch), removes any stable prefix for prompt caching, and makes compaction operate on text segments rather than on tool-result messages that could be dropped or summarised individually.
- **recommendation:** Send session.messages as real messages (assistant text/tool_calls, tool results as role='tool' with the call id) and keep only the protected blocks as the system prompt. The compactor already works on the raw message list (service.py:300-306), so this is a change in assembler.py and service.py:329-341 only; the Claude CLI provider (claude_code.py:78-84) would keep its own flattening as the one place that needs it.
- **confidence:** 0.95

##### 3. No stable prompt prefix and no prompt caching: the clock-to-the-minute is the first line of the system prompt

- **kind:** right-design-undermined
- **severity:** high
- **claim:** task_rules is a protected block placed in the system message, and scaffolds.render puts 'Right now it is <weekday> <date>, HH:MM.' ahead of everything in it, so the system prompt changes every minute; the budget hint changes every step; persona/self/user_profile blocks are re-fetched per call; and no provider sends any cache directive, so every step re-pays the full ~6k-token prefix.
- **evidence:**
  - simorgh/orchestration/scaffolds.py:638 `return f"Right now it is {when:%A %-d %B %Y}, {when:%H:%M}."`; :690-692 `stamp = when_line(now)` ... `body = f"{stamp}\n\n{body}"` ('Ahead of everything, including the task')
  - Measured: `first line of CHAT task_rules: 'Right now it is Friday 18 September 2026, 18:47.'`
  - simorgh/cognition/assembler.py:56-88: constitution, voice, self_summary, user_profile, task_rules, conversation, then budget_hint 'You have {steps_left} tool call(s) left' as protected
  - grep -rn 'cache_control|prompt_cach|cache_read|cache_creation' simorgh/cognition/ -> no matches (together.py:_to_response only reads cached tokens back if the provider happens to return them)
  - Measured system-prompt size per THINK (scaffolds.render + _tool_instruction_block): CHAT/cli tools=72 ~5,778 tokens; VOICE_CHAT tools=58 ~5,841 tokens; PATCH tools=25 ~2,841 tokens; plus constitution/voice/self summary (~300) /user profile
- **why it matters:** On a 20-step chat or patch session the same ~6k tokens are re-sent uncached 20 times; with Together's cached-token pricing and Anthropic's cache_control this is the single largest avoidable cost and latency term in the loop, and the timestamp guarantees a miss even if caching were enabled.
- **recommendation:** Order the system prompt static-to-dynamic (constitution, persona, tool schemas/notes, scaffold body, then task, then memory), move the date to day granularity and the time into the user turn, keep budget/last-step hints in the user turn, and enable provider caching (cache_control on the static system block for Anthropic; Together caches automatically on a stable prefix). Fetch persona.voice/self.summary once per session, not per THINK.
- **confidence:** 0.9

##### 4. One tool call costs ~13 bus messages and ~20 fsync'd file appends, and Cognition's per-call bus requests fragment the trace store

- **kind:** over-engineering
- **severity:** high
- **claim:** For a single-process deployment with the in-memory bus, each tool step is routed through action.proposed -> Guardian (2 ledger appends) -> action.approved -> Execution (ledger read-back + 3 appends) -> action.result + tool.invoked -> Orchestration (1 append + 2 task.step publishes) -> Planning (1-2 lease_refreshed appends), plus 3 memory.retrieve and 3 persona/self/world request-replies per THINK, plus a cognition:calls and cognition:budget append, with every bus publish also appended to a trace stream; each JSONL append is open+flush+fsync, and 95% of the 88,356 trace streams hold one or two events because Cognition and Execution mint a fresh trace_id per internal request.
- **evidence:**
  - Measured trace stream for one chat turn (5 THINKs, 4 tool calls): `TRACE STREAM: trace%3A01d310a3-... events: 67`: 15 memory.retrieve, 15 memory.retrieve.reply, 10 task.step, 5 cognition.think, 5 cognition.think.reply, 4 action.proposed, 4 action.approved, 4 action.result, 1 task.started, 1 task.completed, 1 memory.store, 1 turn.completed, 1 self.observation
  - Measured trace fragmentation: `trace streams: 88356 / 1 events: 67421 / 2 events: 16517 / 3 events: 4011 / >=10 events: 406`; ledger prefixes: 88356 trace, 26737 action, 2431 task
  - Measured real task task:5ad4ce1cce7d: `'task.step': 10, 'lease_refreshed': 16, 'claimed': 2, 'task.started': 2`
  - simorgh/guardian/service.py:547 append 'received', :583 append 'decided'; simorgh/execution/service.py:719 _fetch_proposal does ledger.read(f'action:{action_id}'), :759 append 'verified', :791 inflight 'started', :713/829 inflight 'finished'; simorgh/orchestration/session.py:1901-1913 _record_step appends task.step and publishes it; :892-896 a second task.step publish before every THINK; simorgh/planning/service.py:351-356 _on_task_step and _on_task_lease_heartbeat both -> store.refresh_lease -> planning/store.py:355 ledger.append
  - simorgh/ledger/backends/jsonl.py:409-413 `with open(path, "ab") as fh: ... fh.flush(); if self._fsync: os.fsync(fh.fileno())` per append (ledger/config.py fsync=True default)
  - simorgh/bus/client.py:189-191 every publish also queues a trace event; simorgh/bus/trace.py:101 `stream=f"trace:{message.trace_id}"`; simorgh/cognition/assembler.py:116 `Message.new(type_, source=self._source, payload=payload)` with no trace_id (context.py:150-166 documents the same for other call sites)
  - simorgh/orchestration/session.py:488-530 _EventWaiter subscribes to three topics and unsubscribes per action, polling every 0.2s
  - ledger streams cognition:calls.jsonl 9,379 lines; cognition:budget:together 6,991 lines
- **why it matters:** None of this latency or write volume is structurally necessary on one laptop: the guarantees that matter (Guardian sees every call, the token is re-verified, the step is on the record) need one append per step, not twenty. The 1.4 GB ledger and the 192k-stream explosion already in the project's history are the visible symptom; the invisible one is that every step spends milliseconds-to-seconds in fsync and bus hops before the model even runs.
- **recommendation:** Keep the message contracts but collapse the hops: Guardian and Execution can be invoked in-process by a single 'act' request (one request/reply) that still issues and verifies the HMAC token; record one task.step event per step carrying action_id, verdict and result refs; drop the pre-THINK task.step publish (narrate from the bus, not the ledger); thread trace_id through Cognition's and Execution's internal requests so traces join the task's stream; make trace writing sample-by-root (only task/action-rooted ids) and set fsync to batched/periodic for trace and lease streams. Also stop appending lease_refreshed on every task.step when workers==1.
- **confidence:** 0.9

##### 5. Crash-resume restores the step count but not the context: the resumed model starts blind with fewer steps

- **kind:** bug
- **severity:** high
- **claim:** restore_session rebuilds session.steps and steps_used from the ledger after a worker crash, but session.messages is only populated when a progress note exists (re-grounding is off by default) and session.carried is rendered only from earlier attempts, so the new worker asks the model to continue a task whose previous steps it cannot see while charging it for them.
- **evidence:**
  - simorgh/orchestration/resume.py:117-136: `if last["ended"] is None:` restores steps and `session.budget.steps_used = len(last["steps"])`; :127-131 sets session.messages only `if last.get("note")`; :132-133 `if len(attempts) > 1: session.carried = carried_note(attempts[:-1])` (the crashed attempt itself is never rendered)
  - simorgh/orchestration/config.py:60 `reground_every_steps: int = 0` and ~/.simorgh/simorgh.toml has no [orchestration] section, so no note is ever written in production
  - simorgh/orchestration/context.py:141-160 assemble() only injects task, carried and session.messages
  - tests/simorgh/orchestration/test_attempts.py:65 `test_a_crashed_attempt_is_continued_with_its_steps_counted` asserts the count, not that the model can see the steps
- **why it matters:** Crash-resume is the reason the lease/heartbeat/claim machinery exists at all; as built it produces a session that is worse than a fresh retry (less budget, no memory of what was done, edits in the tree it does not know about). The 'unconnected wire' shape the project already names: the resume slot is designed, the budget side is written, the context side is not.
- **recommendation:** In the crash branch, render the crashed attempt's steps with carried_note([last]) into session.carried (the same renderer retries use), and prefer to always write the progress note by turning reground_every_steps on. Add a test that a resumed session's first THINK contains the prior step summaries.
- **confidence:** 0.9

##### 6. A chat turn can edit the live checkout, cannot commit, and leaves the edit orphaned 'for a next attempt' that never comes

- **kind:** bug
- **severity:** high
- **claim:** The CHAT profile offers apply_source_patch and replace_in_file but not git_commit, chat is not a worktree kind, and on completion with uncommitted edits the runner converts the outcome to blocked and _continues returns True on attempt 1, so _keep_uncommitted leaves a source edit in the live tree with a task.edits_kept record on a task stream no worker will ever re-claim.
- **evidence:**
  - simorgh/orchestration/profiles.py:59 CHAT tools include 'apply_source_patch', 'replace_in_file', 'install_package', 'run_script'; the tuple contains no 'git_commit'
  - simorgh/orchestration/session.py:63 `WORKTREE_KINDS = frozenset({"patch", "skill"})` so chat edits the live tree
  - simorgh/orchestration/session.py:712-735 completed + uncommitted -> Outcome('blocked', reason=UNCOMMITTED_REASON...)
  - simorgh/orchestration/session.py:827-841 _continues: attempt 1 < KEEP_EDITS_UNTIL_ATTEMPT (:389 = 6) and reason startswith UNCOMMITTED_REASON -> True; :846 _keep_uncommitted appends task.edits_kept
  - worker.py:run_percept_chat: a chat session is ephemeral; nothing re-offers its task id
  - Measured in ~/.simorgh/ledger: `uuid-keyed (chat) task streams: 2328 | task.edits_kept events: 2 | task.blocked with 'uncommitted': 2`, kept paths: ['simorgh/voice/config.py'] and ['simorgh_skills/hot_stocks.py']
  - The creator's own memory note 'Live checkout, keep it committed: sim.sh boots from the repo I edit; half-done edits get gated and block rollback' is the operator-side symptom
- **why it matters:** A chat turn silently modified simorgh/voice/config.py in the running checkout that simloader gates and rolls back; the user was told '(Not finished: finished with uncommitted changes)' and the file stayed dirty. This is the exact failure the worktree design was built to prevent, reachable from the most common entry point.
- **recommendation:** Either refuse source writes from a chat session (Execution already receives scope.kind='chat', execution/tools.py:1791 uses it for start_task) and route them through start_task into a patch worktree, or make _continues return False for kind=='chat' so the edit is discarded and the reply says so. Smallest safe change: `if session.kind == "chat": return False` at session.py:832 plus a profile tweak restricting chat writes to workspace/.
- **confidence:** 0.9

##### 7. The chat profile is a 20-step, 72-tool, 16k-output task without task semantics, on a 12k-token input budget

- **kind:** wrong-design
- **severity:** high
- **claim:** A typed chat turn is given the same step budget and output budget as a patch task and more tools than any task profile, yet it has no verification, no worktree, no resume and a synchronous 420s wait, while its Cognition input budget is 12,000 tokens of which ~5.8k are the fixed prompt, leaving roughly 5k for memory plus a transcript whose tool results can each be ~2k tokens.
- **evidence:**
  - simorgh/orchestration/profiles.py:77 `read_only=False, max_steps=20, max_revisions=0, scaffold="chat", verify=False,` and :90 `max_output_tokens=16_000` (comment: 'Matched to the patch profile, which is what a chat turn now IS')
  - Measured: `CHAT/cli tools= 72 task_rules= 13013 chars ~3254 tok | tool_instructions= 10095 chars ~2524 tok | total ~5778 tok`
  - simorgh/cognition/config.py:22 `"chat": Budget(12_000, 1_000, 0.05, max_seconds=90.0)`; cognition/service.py:307 elastic_limit = max_tokens_in - protected_tokens; context.py:31 memory block up to 4,000 chars
  - simorgh/interface/config.py:88 `chat_reply_timeout_s: float = 420.0`; interface/service.py:917-1000 blocks the REPL on the future
  - scaffolds.py _CHAT already says 'Judge the SIZE first ... anything that will take many edits ... goes to start_task', and tools.py:_MARKER_ARG_HINT['start_task'] says the same; the profile numbers contradict the instruction
  - ~/.simorgh/simorgh.toml: [cognition.providers.ollama] only_purposes=['chat'], num_ctx=8192 -- the chat fallback model's context is smaller than the chat purpose's own input budget
- **why it matters:** The two modes converge into one that is bad at both: a chat turn that reads two files is already being snipped by compaction, a 20-step chat can outlive the REPL's wait, and a build started 'in chat' gets none of the worktree/verify/resume protections. The design already contains the right split (start_task hands builds to a task with a worktree); the profile undoes it.
- **recommendation:** CHAT: 6-8 steps, ~15-20 tools (read-only + house/TV/camera acts + remind + start_task/list_tasks/cancel_task), output ~2-4k tokens, writes limited to workspace/; every source edit and every multi-file build goes through start_task. Raise the chat purpose input budget to what the primary model actually supports (and set Ollama num_ctx to match or drop it from chat), and cut the tool-notes block once native tool schemas carry the descriptions.
- **confidence:** 0.85

##### 8. Domain and channel knowledge has leaked into the kernel loop (TV, cameras, voice mishearings, pronunciation)

- **kind:** wrong-design
- **severity:** medium
- **claim:** session.py, the harness state machine, hard-codes the TV tool list, TV/dashboard claim regexes, a pronunciation-claim regex, misheard forms of Sim's name and a voice-only refusal rule, and Session carries speaker/room/speaker_before fields, so every new domain or channel means another regex and another branch in the core loop.
- **evidence:**
  - simorgh/orchestration/session.py:189 `_TV_TOOLS = ("cast_play", "cast_show", "tv_charts", "tv_app", "tv_key", "dash_view", "cast_stop")`; :180-186 _TV_CLAIM; :191-197 _TV_ASK; :224-226 _DASH_ON_TV; :329-333 _NOTED_PRONUNCIATION; :553 _NAMES_SIM ('sim|sima|simorgh|sam|seem|seam|seym|syme'); :556 unplaced_voice_refusal
  - session.py:1100-1195: eleven sequential guard branches in _run, each 'once per session' via marker_corrected/claim_corrected/invented_corrected flags on Session (api.py:118-131)
  - simorgh/orchestration/api.py:166-175 Session fields speaker, speaker_relation, room, speaker_before
  - git log: 80 commits to simorgh/orchestration/session.py since 2026-09-01, +2091/-149 lines; the file is 1,942 lines with 527 comment lines
  - prior reviews (docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html) contain 0 hits for 'marker', 'lease', 'resume', 'cache', 'fsync'
- **why it matters:** The loop is the one file everything depends on and it is the file with the highest churn; each guard is a reasonable live fix, but their home is wrong, so the fixes accrete where they are hardest to test in isolation and easiest to break each other (several guards share one claim_corrected flag, so only the first that fires in a session ever runs).
- **recommendation:** Introduce a small reply-guard interface (`guard(text, session) -> Correction | None`) and let voice/, execution/media and the household contracts register their own guards; the loop applies at most one correction per step from an ordered list. Move channel fields into an opaque `session.channel_context` dict rendered by the channel's own scaffold. Most of the guards then disappear entirely once native tool calls land (finding 1).
- **confidence:** 0.85

##### 9. Consumer groups, claim RPC, leases, heartbeats and lease scans for one worker in one process

- **kind:** over-engineering
- **severity:** medium
- **claim:** The worker design is a distributed competing-consumer protocol (claim request/reply, lease renewal on every step and every 30s, a per-second lease scan, redelivery on crash) but the deployed configuration is workers=1 on the in-memory bus in a single process, and the project's own history shows this machinery generated more incidents (lease expiry resurrecting finished tasks, preemption killing the task it postponed, the 300s handler timeout acting as every task's wall budget) than it prevented.
- **evidence:**
  - simorgh/orchestration/worker.py:192-210 subscribe(TASK_AVAILABLE, group='workers', max_inflight=1, max_handler_seconds=UNBOUNDED); :279 `reply = await self._bus.request_or_error(claim_req, timeout=2.0)`; :350-378 _heartbeat_loop publishes task.lease_heartbeat every min(heartbeat_s, lease/3)
  - simorgh/planning/scheduler.py:233-247 scan_leases on every system.tick.second; planning/store.py:355-374 refresh_lease appends lease_refreshed per task.step and per heartbeat
  - simorgh/orchestration/config.py:1-45 docstring: lease_seconds, max_depth, max_children_concurrent, needs_human_timeout_s 'declared ... but no code path reads them yet'
  - ~/.simorgh/simorgh.toml has no [orchestration] or [bus] section: workers=1, bus backend=memory
  - Measured task:5ad4ce1cce7d: 16 lease_refreshed for 10 task.step
- **why it matters:** For one laptop the same guarantees (one task at a time, crash detection, resume) come from a task.started without a matching terminal event at boot; the lease protocol adds a write per step, a scan per second, and a family of race conditions with no second process to justify them.
- **recommendation:** Keep Planning as the queue owner and keep the message contracts, but when workers==1 and the bus is in-memory: do not heartbeat, do not refresh the lease per step, and treat 'started, no outcome, worker gone' at boot as the crash signal. Re-enable the lease path only under local-multi mode where it is actually needed.
- **confidence:** 0.8

##### 10. The 2026-style loop features are built and all switched off by default

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** Re-grounding via progress note, parallel read-only tool batches, clean revisions, in-process delegation and strong-tier escalation are implemented in session.py but every one defaults off in config.py and the live simorgh.toml sets none of them, so production runs one tool per step with an unbounded transcript until Cognition raises context_too_large and a forced reground rescues it.
- **evidence:**
  - simorgh/orchestration/config.py:60 `reground_every_steps: int = 0`, :64 `clean_revisions: bool = False`, :67 `delegation: bool = False`, :74 `parallel_read_tools: int = 1`, :77 `escalate_from_attempt: int = 0`, each annotated 'Off until its benchmark arm wins'
  - simorgh/orchestration/session.py:898-907 the only reground in production is the forced one after a context_too_large error
  - simorgh/orchestration/session.py:1425-1480 _delegate and :1385-1420 _read_batch/_run_batch exist and are tested (tests/simorgh/orchestration/test_delegate.py, test_parallel_reads.py, test_reground.py)
  - ~/.simorgh/simorgh.toml: no [orchestration] section
- **why it matters:** State-of-the-art harnesses in 2026 are exactly these three things: compaction on a schedule, parallel independent tool calls, and bounded sub-agents with fresh context. Simorgh has them and runs without them, so its measured behaviour (steps burned, context blowups, cost) is that of a 2024 loop.
- **recommendation:** Default reground_every_steps=8 and parallel_read_tools=4 for task profiles now (they are cheap and low-risk); enable delegation for research/patch; run the benchmark arm to tune, not to gate.
- **confidence:** 0.85

##### 11. session_id is never sent on cognition.think, so per-session compaction summaries and working memory key on None

- **kind:** bug
- **severity:** low
- **claim:** SessionRunner._think builds the think payload without a session_id, so Cognition's layer-5 summary stream cognition:summaries:<session_id> and the memory 'working' kind's session filter cannot engage per task.
- **evidence:**
  - grep -n session_id simorgh/orchestration/session.py -> no occurrences in the _think payload (session.py:1225-1290)
  - simorgh/cognition/service.py:303-306 `session_id=payload.get("session_id")` passed to the compactor; compaction.py:334 _store_summary keyed by session_id
  - simorgh/memory/store.py:266-272 working-memory retrieval requires filters['session_id']
- **why it matters:** Layer 5 is the last-resort compaction that a long chat turn relies on (allow_summarize is set for chat); its summaries are stored under a null key and are unusable for continuity, and working memory is unreachable from the loop.
- **recommendation:** Pass `session_id: session.task_id` in the think payload and in the memory.retrieve requests.
- **confidence:** 0.8


### measurements

- ledger stream prefixes in ~/.simorgh/ledger/streams (118,215 files, 1.4G): `88356 trace / 26737 action / 2431 task / 350 verify / 310 reflect`
- trace-stream fragmentation: `trace streams: 88356 / 1 events: 67421 / 2 events: 16517 / 3 events: 4011 / 8 events: 1 / >=10 events: 406`
- one chat turn with 4 tool calls (task 01d310a3, 7 ledger events on task:<id>): trace stream `events: 67`: 15 memory.retrieve, 15 memory.retrieve.reply, 10 task.step, 5 cognition.think, 5 cognition.think.reply, 4 action.proposed, 4 action.approved, 4 action.result, 1 task.started, 1 task.completed, 1 memory.store, 1 turn.completed, 1 self.observation
- one real task (task:5ad4ce1cce7d): `{'created': 1, 'claimed': 2, 'task.step': 10, 'task.started': 2, 'lease_refreshed': 16, 'status_changed': 2, 'lease_expired': 1, 'task.failed': 1}`
- one action stream (action:c15efdc8dd7f): 3 events `received / decided / verified`
- rendered fixed prompt per THINK (scaffolds.render + cognition _tool_instruction_block, estimate_tokens): `CHAT/cli tools= 72 task_rules= 13013 chars ~3254 tok | tool_instructions= 10095 chars ~2524 tok | total ~5778 tok`; `VOICE_CHAT/voice tools= 58 ... total ~5841 tok`; `PATCH tools= 25 ... total ~2841 tok`; `RESEARCH tools= 31 ... total ~2739 tok`
- `first line of CHAT task_rules: 'Right now it is Friday 18 September 2026, 18:47.'`
- chat sessions that orphaned edits: `uuid-keyed (chat) task streams: 2328 | task.edits_kept events: 2 | task.blocked with 'uncommitted': 2`; kept paths `['simorgh/voice/config.py']` and `['simorgh_skills/hot_stocks.py']`
- session.py: 1942 lines, 527 comment lines, 11 `re.compile`; `git log --oneline --since=2026-09-01 -- simorgh/orchestration/session.py | wc -l` = 80 (all 80 commits the file has), numstat `added 2091 deleted 149`
- tests/simorgh/orchestration: 34 files, 367 `def test_`
- cognition ledger streams: cognition:calls.jsonl 9379 lines; cognition:budget:together 6991; cognition:budget:ollama 1360; cognition:budget:claude_code_cli 1034
- `grep -rn 'cache_control|prompt_cach|cache_read|cache_creation' simorgh/cognition/` -> 0 matches
- prior review docs: grep counts in docs/architecture-audit-2026.md / docs/architecture-review-2026-09-18.html for marker=0/0, native tool|function calling=0/0, prompt cache=0/0, resume=0/0, lease=0/0, fsync=0/0, compaction|reground=0/0
- ~/.simorgh/simorgh.toml sections present: [voice] [interface] [execution] [cognition] [cognition.providers.ollama] (only_purposes=['chat'], num_ctx=8192); no [orchestration], [bus] or [ledger] section, so orchestration/bus/ledger run on code defaults (workers=1, memory bus, jsonl ledger with fsync=True)

