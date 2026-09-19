# refute:correctness:Reflection's critiques undo Memory's own

*Workflow: review · Phase: Refute · Agent id: `aa6886445bc4e0192` · Tool calls: 5*

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
    "title": "Reflection's critiques undo Memory's own 'no task text in episodic memory' rule and land in family chat prompts",
    "kind": "bug",
    "severity": "medium",
    "claim": "Memory refuses to store non-chat turns as episodic memory, but Reflection writes every patch/skill/research/project critique into the same episodic kind with no person tag, so they pass the voice-channel ownership filter and compete for the six 'most recent' slots that are a chat's only conversational context.",
    "evidence": [
      "simorgh/memory/service.py:217-222 -- `if str(payload.get(\"kind\") or \"chat\") != \"chat\": return` ('A task's own model session ends with turn.completed too; its description is not something a person said')",
      "simorgh/reflection/service.py:346-349 -- `MEMORY_STORE {\"kind\": \"episodic\", \"content\": critique.what_changed, \"tags\": [\"self_critique\", f\"task:{task_id}\"]}`",
      "simorgh/orchestration/context.py:251-254 (recent recall: `query=\"\"`, `kinds=[\"episodic\"]`, k=6, pure recency) and :288-294 (`_theirs` admits any item with no `person:` tag)",
      "ledger measurement: `self_critique episodic: 125`; `125 critiques; 122 within 10 min of a human chat turn`; sample content: `'Honest final status: **no source change was applied, and the task is not complete.**\\n\\nWhat I did this session: ...'`"
    ],
    "why_it_matters": "This is the 'one side fixed, the other side undone' shape in miniature: a self-critique about a failed code patch is exactly the text that should never be recalled into a child's spoken turn as 'what we were just saying'. It also skews the recency window that was added specifically to keep corrections ('March 6th, not 4th') in view.",
    "recommendation": "Store critiques as `procedural` (or a new `reflective` kind) tagged `origin:reflection`, and have the chat recall in context.py request `kinds=[\"episodic\"]` with `filters={\"tags\": ...}` that excludes them; five lines in each place.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read Memory turn filter and Reflection store call |  said this turn there is nothing worth remembering, so an empty pair is skipped rather than filling episodic memory with blanks from the honest-floor path (`flo |
| 2 | Bash | Read context recall and ownership filter; check memory recall filters |  (see `_MEMORY_RECENT_K`), so without the second one a fact told two turns ago is only remembered if the current sentence happens to share vocabulary with it. T |
| 3 | Bash | Check recall constants, self_critique references, engine recency path, ledger layout | 34:_MEMORY_MATCHED_K = 8 66:_MEMORY_RECENT_K = 6 68:_MEMORY_PERSON_K = 5 ---- (eval):1: no matches found: --include=*.py ---- ugrep: warning: simorgh/memory/eng |
| 4 | Bash | Read retrieve empty-query path, store handler, find self_critique refs, list memory streams |  async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict \| None) -> tuple[list[MemoryItem], bool]: """Rank what is remembered against `q |
| 5 | Bash | Inspect empty-query scoring and count critiques in episodic ledger stream | 1: wanted_tags = set(filters["tags"]) if filters.get("tags") else None 6: for kind in kinds: 14: candidates.append((self._score(query_pair, content, item, now,  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is accurate today. simorgh/memory/service.py:217-222 refuses to write a non-chat turn.completed into episodic memory, with a comment explaining exactly the harm (task descriptions recalled as conversation). simorgh/reflection/service.py:346-349 publishes MEMORY_STORE with kind "episodic", tags ["self_critique", "task:<id>"], for every task critique. simorgh/memory/service.py:177-193 (_on_store) applies no kind/tag policy: anything that is not "working" is stored verbatim. simorgh/orchestration/context.py:251-254 issues the recent recall with query="" and kinds=["episodic"], k=_MEMORY_RECENT_K=6 (line 66); simorgh/memory/store.py retrieve() sets similarity=1.0 when the query is empty, so ranking is confidence + recency only, with no tag exclusion. context.py:288-294 `_theirs` returns True for any item with no `person:` tag, and critiques carry none, so on the voice channel they survive the ownership filter that was added to keep one family member's turns from another. The only reference to "self_critique" anywhere in simorgh/ is the write site in reflection/service.py; nothing reads or excludes that tag. Live ledger: 2,746 episodic records, 125 tagged self_critique, 0 of them with a person tag; the three most recent critiques are code-patch status reports ("Honest final status: no source change was applied..."). The 30 most recent episodic records at this moment are all chat (first tag is a session id), so displacement of the 6-slot window is intermittent rather than constant, which matches the reader's "122 within 10 min of a human chat turn" framing and a medium severity. Not in the known-findings list. Classification: (b) design right (Memory's rule), implementation undermined by another subsystem writing into the same kind; the fix is genuinely small. One small nuance: the recency recall is not "pure recency" but similarity=1.0 * confidence + recency_weight*recency_bonus, so a critique with a lower confidence field could rank below an equally recent chat turn; this does not change the conclusion since critiques are stored without confidence (reflection passes none) and get the default.

### evidence

- simorgh/memory/service.py:217-222 -- `if str(payload.get("kind") or "chat") != "chat": return` with comment 'its description is not something a person said'
- simorgh/memory/service.py:177-193 -- `_on_store` stores any non-working kind verbatim; no tag or origin policy
- simorgh/reflection/service.py:346-349 -- `MEMORY_STORE {"kind": "episodic", "content": critique.what_changed, "tags": ["self_critique", f"task:{task_id}"]}` for every critiqued task
- simorgh/orchestration/context.py:34,66,68 -- _MEMORY_MATCHED_K=8, _MEMORY_RECENT_K=6, _MEMORY_PERSON_K=5; :251-254 recent recall is query="", kinds=["episodic"], k=6 with no filters
- simorgh/orchestration/context.py:288-294 -- `_theirs` returns `not owners or ...`; an item with no person: tag passes for every voice speaker
- simorgh/memory/store.py:238-262 and ~300 -- `query_pair = ... if query else None`; `if query_pair is None: similarity = 1.0`; `wanted_tags` only includes, never excludes
- `grep -rn self_critique simorgh/` -> only simorgh/reflection/service.py:348 (write site); no reader or exclusion anywhere
- python3 scan of ~/.simorgh/ledger/streams/memory%3Aepisodic.jsonl: 'episodic records 2746 self_critique 125 with person tag 737' (0 critiques carry a person: tag); newest critique content: 'Honest final status: **no source change was applied, and the task is not complete.**\n\nWhat I did this session: ...'
- same scan: the 30 most recent episodic records are all chat (session-id first tag), so displacement of the 6 recent slots is intermittent, occurring when tasks complete near a chat turn

**severity adjustment:** keep

