# refute:correctness:session_id is never sent on cognition.th

*Workflow: review · Phase: Refute · Agent id: `a72991570161218e7` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Grep session_id across the cited files | ---cognition--- simorgh/cognition/service.py:311: session_id=payload.get("session_id"), purpose=purpose.value, simorgh/cognition/service.py:428: session_id=mess |
| 2 | Bash | Locate the think payload and all cognition.think senders | 656: self._think_timeout_s = think_timeout_s 898: # *after* `_think()` already had its reply -- during the real 909: think_reply = await self._think(session, pe |
| 3 | Bash | Read the think payload and cognition's session_id use |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 4 | Bash | Check summary readers, working-memory retrieval, and loop memory requests | === readers of cognition:summaries / summary_ref === simorgh/cognition/service.py:397: "summary_ref": compacted.summary_ref, simorgh/cognition/service.py:433: " |
| 5 | Bash | Check summary readback, compacted-messages use, and working-memory writers | === compaction.py reads of ledger (read/replay) === 338: ref = await self._ledger.put_blob(text.encode("utf-8"), content_type="text/plain") 342: await self._led |
| 6 | Bash | Check the kind each memory.store sender uses |  # nothing ever wrote one. procedure = procedure_from(session, outcome) if procedure: await self._bus.publish(Message.new( topics.MEMORY_STORE, source=self._bus |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The bare fact holds: SessionRunner._think (simorgh/orchestration/session.py:1219-1291) builds the cognition.think payload with purpose/messages/tools/task_rules/expected/budget/allow_summarize/etc. and no session_id; `grep -n session_id simorgh/orchestration/session.py` returns nothing at all, and cognition/service.py:311 forwards `payload.get("session_id")`, i.e. None. But the three consequences the finding draws are each wrong or overstated. (1) Summaries are not keyed on None: compaction.py:293 does `sid = session_id or "unspecified"`, so the stream is `cognition:summaries:unspecified`. (2) "Unusable for continuity" is moot: nothing in the codebase ever reads a `cognition:summaries:*` stream back (the only occurrences are the writer at compaction.py:342-345; compaction.py has no ledger read at all, and orchestration never touches summary_ref). Layer 5 itself is not broken by the missing id -- service.py:339-341 appends `compacted.text` into the messages sent to the model for that same think call, so a long chat turn still gets its last-resort compaction. The only degradation is a ledger record nobody consumes landing under a shared stream name. (3) Working memory is unreachable for reasons unrelated to session_id: the assembler's three memory.retrieve requests (context.py:247-265) ask for kinds ["episodic","semantic"] only, never "working", and no publisher anywhere stores kind "working" (every MEMORY_STORE sender -- worker.py:500, learning/pipeline.py:182, curiosity/service.py:259, reflection/service.py:346 -- uses procedural/semantic/episodic). Adding session_id to memory.retrieve, as recommended, would change nothing. That half of the finding is the already-known "no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py)" item -- working memory is the designed slot for that buffer, unwired on both ends. Net: a real but cosmetic omission (a ledger stream name), not the functional continuity bug described; severity should go below the stated "low".

### evidence

- simorgh/orchestration/session.py:1234-1291 -- think payload keys: purpose, messages, tools, task_rules, expected, tool_hints, budget, require_real_provider, last_step, steps_left, allow_summarize, tier; no session_id. `grep -n session_id simorgh/orchestration/session.py` -> (no output)
- simorgh/cognition/service.py:308-312 -- `compacted = await self._compactor.compact(payload["messages"], ..., session_id=payload.get("session_id"), purpose=purpose.value)`
- simorgh/cognition/compaction.py:293 -- `sid = session_id or "unspecified"`; the stream becomes cognition:summaries:unspecified, not None
- simorgh/cognition/compaction.py:334-345 -- _store_summary is the only writer; `grep -rn "cognition:summaries\|summary_ref" simorgh --include='*.py'` shows no reader: only compaction.py (writer), service.py:397/433 (echoes summary_ref in reply), api.py:135 and contracts/messages/cognition.py:56 (field declarations)
- simorgh/cognition/compaction.py -- `grep -n "self._ledger\."` -> lines 338, 342, 391 only, all writes (put_blob/append); no read/replay of prior summaries
- simorgh/cognition/service.py:339-341 -- `if compacted.text: think_messages.append({"role": "user", "content": compacted.text})`: layer-5 output is used in-call regardless of session_id
- simorgh/orchestration/context.py:247-265 -- the three MEMORY_RETRIEVE requests use kinds ["episodic","semantic"] / ["episodic"]; "working" is never requested
- simorgh/memory/store.py:266-272 -- working-kind branch needs filters["session_id"], but is only entered if "working" is in kinds
- `grep -rn '"working"' simorgh --include='*.py' | grep -v ^simorgh/memory/` -> only contracts/messages/memory.py:9 (enum) and an unrelated docstring in execution/domainstatus.py:51; no MEMORY_STORE sender uses kind working (worker.py:500-506 procedural; learning/pipeline.py:182-184 procedural; curiosity/service.py:259-261 semantic; reflection/service.py:346-348 episodic)
- simorgh/orchestration/worker.py:403,525 -- session.task_id is the chat session_id (percept session_id -> task_id; TURN_COMPLETED sends session_id=session.task_id), so the one-line fix is available but its only effect today would be the ledger stream name

**severity adjustment:** lower

**corrected claim:** SessionRunner._think omits session_id from the cognition.think payload, so any layer-5 compaction summary is appended to the ledger under the shared stream cognition:summaries:unspecified (compaction.py:293) instead of a per-session stream. This is cosmetic today: no code reads those summary streams back, and the compacted text is still injected into the same think call (service.py:339-341), so chat continuity and layer-5 compaction are unaffected. The memory "working" kind is unreachable for a different reason that session_id does not fix: the assembler never requests kind "working" (context.py:247-265) and nothing ever stores it -- an unconnected wire on both ends that is the already-known "no in-prompt sliding dialogue buffer" finding.

