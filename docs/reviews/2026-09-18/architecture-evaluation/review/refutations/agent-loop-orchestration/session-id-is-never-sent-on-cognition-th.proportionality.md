# refute:proportionality:session_id is never sent on cognition.th

*Workflow: review · Phase: Refute · Agent id: `aa1e49d2a37d75d46` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "session_id is never sent on cognition.think, so per-session compaction summaries and working memory key on None",
    "kind": "bug",
    "severity": "low",
    "claim": "SessionRunner._think builds the think payload without a session_id, so Cognition's layer-5 summary stream cognition:summaries:<session_id> and the memory 'working' kind's session filter cannot engage per task.",
    "evidence": [
      "grep -n session_id simorgh/orchestration/session.py -> no occurrences in the _think payload (session.py:1225-1290)",
      "simorgh/cognition/service.py:303-306 `session_id=payload.get(\"session_id\")` passed to the compactor; compaction.py:334 _store_summary keyed by session_id",
      "simorgh/memory/store.py:266-272 working-memory retrieval requires filters['session_id']"
    ],
    "why_it_matters": "Layer 5 is the last-resort compaction that a long chat turn relies on (allow_summarize is set for chat); its summaries are stored under a null key and are unusable for continuity, and working memory is unreachable from the loop.",
    "recommendation": "Pass `session_id: session.task_id` in the think payload and in the memory.retrieve requests.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Grep session_id across cited files | --- 311: session_id=payload.get("session_id"), purpose=purpose.value, 428: session_id=message.payload.get("session_id"), --- 24: `cognition:summaries:<session_i |
| 2 | Bash | Inspect think payload construction and session_id producers |  assembled = await self._assembler.assemble( purpose=purpose.value, messages=payload["messages"], task_rules=payload.get("task_rules", ""), last_step=payload.ge |
| 3 | Bash | Read _think payload and working-memory paths |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 4 | Bash | Check working-memory writers, think senders, and summary readers | simorgh/memory/service.py:185: self.engine.working.add(session_id, "", payload["content"], ts=self._ctx.clock.now()) simorgh/memory/store.py:123: self.working = |
| 5 | Bash | Verify working-memory senders, contract fields, and summary readers |  for i in items ], "truncated": truncated, }) async def _on_store(self, message: Message) -> None: payload = message.payload if payload["kind"] == "working": #  |
| 6 | Bash | Check ledger for summary streams and the learning store kind | blobs heads idem index.json LOCK snapshots streams --- # description later (Execution's `memory.retrieve{kinds: # [procedural]}` lookup on load). await self._pu |
| 7 | Bash | Look for cognition summary streams in the live ledger | cognition%3Abudget%3Aclaude_code_cli.jsonl cognition%3Abudget%3Agemini.jsonl cognition%3Abudget%3Aollama.jsonl cognition%3Abudget%3Atogether.jsonl cognition%3Ac |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The literal claim holds: `grep -c session_id simorgh/orchestration/session.py` returns 0, and the `cognition.think` payload built in `SessionRunner._think` (session.py:1233-1290) never sets the optional `session_id` field the contract allows (contracts/messages/cognition.py:16 `O("session_id", Str)`). But every consequence the finding draws from it is overstated or already known. (1) The key is not None: compaction.py:293 `sid = session_id or "unspecified"`, so summaries would land in `cognition:summaries:unspecified`. (2) Nothing reads that stream: `grep -rn "summaries" simorgh --include='*.py'` outside compaction.py hits only unrelated benchmark/memory docstrings; the layer-5 summary is inlined into the compacted messages returned in the same reply (compaction.py:303-310) and `summary_ref` is only echoed back in the reply payload (service.py:397,433). Per-session keying therefore has no consumer, so passing `session_id` would change nothing observable. (3) Layer 5 has never fired live: `ls ~/.simorgh/ledger/streams | grep -ci summar` is 0 across the real ledger, so no summary has ever been stored under any key. (4) The working-memory half is a separate, already-documented unconnected wire, not a consequence of the missing session_id: context.py:247-265 requests only `kinds: ["episodic","semantic"]`, never "working"; store.py:52-64 states no producer publishes `memory.store{kind:"working"}` outside tests (still true: the only non-test MEMORY_STORE publisher, learning/pipeline.py:182, stores "procedural"); and service.py:184 keys working turns by `tags[0]`, not by a session_id filter. Even with the recommended fix, retrieval would hit an empty window. Furthermore, CLI chat mints a fresh session_id per typed line (context.py:40-43), so a session-keyed working memory would hold at most one turn. Verdict: a real but inert omission of an optional field; the recommendation would add plumbing with no behavioural effect until the real (already-known) gaps -- no working-memory producer and no in-prompt dialogue buffer -- are fixed. Not an architectural problem at this scale.

### evidence

- `grep -c session_id /Users/saeed/ws/Simorgh/simorgh/orchestration/session.py` -> 0; think payload at simorgh/orchestration/session.py:1233-1290 has no session_id key
- simorgh/contracts/messages/cognition.py:16 `O("session_id", Str)` -- the field is optional in the contract
- simorgh/cognition/compaction.py:293 `sid = session_id or "unspecified"` -- the stream key is 'unspecified', not None
- simorgh/cognition/compaction.py:303-310 and simorgh/cognition/service.py:397,433 -- the summary text is inlined into the returned messages; summary_ref only echoed in the reply; no code reads `cognition:summaries:*` (grep -rn summaries simorgh --include=*.py, excluding compaction.py, shows only unrelated docstrings)
- `ls ~/.simorgh/ledger/streams | grep -ci summar` -> 0; only cognition:budget:* and cognition:calls streams exist -- layer 5 has never stored a summary live
- simorgh/orchestration/context.py:247-265 -- all three memory.retrieve requests use kinds ["episodic","semantic"] or ["episodic"]; "working" is never requested
- simorgh/memory/store.py:52-64 docstring: no producer publishes memory.store{kind:"working"} outside tests; confirmed: only non-test MEMORY_STORE publisher is simorgh/learning/pipeline.py:182 with kind "procedural"
- simorgh/memory/service.py:184 -- working turns are keyed by `tags[0]`, not by a session_id filter, so the recommended retrieve-side change alone would not connect them
- simorgh/orchestration/context.py:40-43 -- CLI chat mints a fresh session_id per typed line, so session-keyed working memory would hold at most one turn

**severity adjustment:** lower

**corrected claim:** SessionRunner._think omits the optional `session_id` field from cognition.think, so any layer-5 compaction summary would be filed under `cognition:summaries:unspecified`. This is inert today: no code reads that stream (the summary is inlined in the reply), layer 5 has never fired in the live ledger (zero summary streams), and working memory is unreachable for the separate, already-known reason that nothing produces `memory.store{kind:"working"}` and the context assembler never requests kind "working". Passing session_id alone would change no behaviour.

