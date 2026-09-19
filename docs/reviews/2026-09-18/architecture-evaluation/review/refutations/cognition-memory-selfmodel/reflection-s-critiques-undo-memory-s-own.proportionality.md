# refute:proportionality:Reflection's critiques undo Memory's own

*Workflow: review · Phase: Refute · Agent id: `a3b0b283eaeffa625` · Tool calls: 8*

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
| 1 | Bash | Read the three cited code regions |  said this turn there is nothing worth remembering, so an empty pair is skipped rather than filling episodic memory with blanks from the honest-floor path (`flo |
| 2 | Bash | Locate store handler, constants and any tag exclusion | 34:_MEMORY_MATCHED_K = 8 66:_MEMORY_RECENT_K = 6 68:_MEMORY_PERSON_K = 5 235: (see `_MEMORY_RECENT_K`), so without the second one a fact told 248: {"query": que |
| 3 | Bash | Check store handler, retrieve semantics, and ledger layout |  payload={"refs": refs, "reason": reason})) await self._ctx.bus.reply(message, type=topics.MEMORY_FORGET_REPLY, payload={"forgotten": len(refs), "refs": refs, " |
| 4 | Bash | Find memory engine retrieve and ledger streams | __init__.py __pycache__ api.py config.py consolidation.py embed.py embedders.py recall.py service.py store.py simorgh/memory/store.py:238: async def retrieve(se |
| 5 | Bash | Read retrieve implementation and measure critique share in episodic stream |  async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict \| None) -> tuple[list[MemoryItem], bool]: """Rank what is remembered against `q |
| 6 | Bash | Check empty-query scoring and measure how often critiques sit in the recency window |  if query_pair is None: similarity = 1.0 elif self._index.hashing: similarity = sims.get(position, 0.0) else: similarity = index.dense_similarity(position, quer |
| 7 | Bash | Check whether working memory is used for chat context, live reflection config, and any consumer of the self_critique tag | ---- ---- simorgh/reflection/config.py:22: critique_max_tokens: int = 400 simorgh/reflection/config.py:114: critique_max_tokens=int(data.get("critique_max_token |
| 8 | Bash | Check consumers of the critique tag, episodic keep limit, reflection enablement, and the memory block header | ---- simorgh/memory/service.py:19:DEFAULT_KEEP_PER_KIND = {"episodic": 2_000, "semantic": 2_000, "procedural": 500} simorgh/memory/service.py:37: self._keep_per |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out against the code as it is today, and the ledger confirms the effect is real, not historical. (1) simorgh/memory/service.py:217-222 drops non-chat turn.completed payloads from episodic memory, with a docstring saying exactly why: a task description "is not something a person said". (2) simorgh/reflection/service.py:346-349 publishes MEMORY_STORE with kind="episodic", tags ["self_critique", "task:<id>"] and no person: tag, for every task outcome; memory/service.py:177-193 `_on_store` stores any non-working kind verbatim with no filtering. (3) orchestration/context.py:251-254 issues the recency recall with query="" and kinds=["episodic"], k=6; memory/store.py:300-301 gives similarity=1.0 to every record when the query is empty, so ranking is purely confidence-decay + recency bonus (store.py:313-322), i.e. the 6 newest episodic records of any origin. (4) context.py:288-294 `_theirs` returns True for any item with no person: tag, so on the voice channel critiques pass the ownership filter that was added to keep one family member's lines away from another. Nothing else in the tree reads the self_critique tag (`grep -rn self_critique simorgh tests` hits only the writer), and the critique is already durably kept in its own reflect:critique:<task> stream (reflection/service.py:342-345), so the episodic copy has no consumer except accidental chat recall. context.py never uses the "working" kind (grep empty), consistent with the already-known absence of a sliding dialogue buffer, so the 6-slot recency recall really is the chat's only conversational context. Measured from ~/.simorgh/ledger/streams/memory%3Aepisodic.jsonl: 2,746 episodic records, 125 tagged self_critique, none person-tagged; 330 of 2,621 chat turns had at least one critique among the 6 episodic records immediately preceding them (worst case 4 of 6 slots), and 27 of 737 person-tagged (voice) turns did. Critique content is task-engineering prose ("Honest final status: **no source change was applied...**", "widened the except clause in _run's locked() wrapper..."), avg 307 chars, max 2,276. On the skeptic's lens: this is a genuine bug (kind c), not an over-built design; the fix is a kind/tag change on the writer plus one filter on the reader, trivially cheaper than the confusion it removes, so the recommendation is proportionate. One nuance: the last critique (ts 1789610310) predates the latest chat turn by ~46 h because no tasks have run since, so the live window is clean at this instant; the mechanism is intact and recurs the next time a task completes before a chat.

### evidence

- simorgh/memory/service.py:217-222 -- `if str(payload.get("kind") or "chat") != "chat": return` with comment 'its description is not something a person said'
- simorgh/memory/service.py:177-193 -- `_on_store` stores any kind other than 'working' verbatim: `ref = await self.engine.store(kind=payload["kind"], content=payload["content"], tags=payload.get("tags", []), ...)`
- simorgh/reflection/service.py:346-349 -- `await self._publish(message, topics.MEMORY_STORE, {"kind": "episodic", "content": critique.what_changed, "tags": ["self_critique", f"task:{task_id}"], "source_ref": f"reflect:critique:{task_id}"})`; :342-345 also appends the same critique to its own `reflect:critique:<task>` stream
- simorgh/orchestration/context.py:251-254 -- recency recall `{"query": "", "kinds": ["episodic"], "k": _MEMORY_RECENT_K}` with _MEMORY_RECENT_K = 6 (context.py:66)
- simorgh/memory/store.py:300-301 `if query_pair is None: similarity = 1.0` and :313-322 score = similarity*confidence(decayed) + recency_weight*recency_bonus -- empty query ranks by recency only
- simorgh/orchestration/context.py:288-294 -- `_theirs`: `return not owners or (bool(speaker) and speaker in owners)` -- an item with no person: tag passes for every voice speaker
- `grep -rn self_critique simorgh tests` -> only simorgh/reflection/service.py (no reader of the tag); `grep -n working simorgh/orchestration/context.py` -> no matches (working memory not used for chat context)
- ledger measurement (python over ~/.simorgh/ledger/streams/memory%3Aepisodic.jsonl): 'episodic records 2746 self_critique 125'; tag prefixes: person 755, self_critique 125, task 125; 'chat turns whose preceding-6 window contains >=1 critique: 330 of 2621 worst count 4'; 'voice (person-tagged) turns with a critique in preceding 6: 27 of 737'; 'critique lengths avg 306.9 max 2276'
- sample critique content in episodic stream: 'Honest final status: **no source change was applied, and the task is not complete.** | What I did this session: - Verified `simorgh/benchmark...'; 'In simorgh/ledger/backends/sqlite.py, widened the except clause in _run's locked() wrapper from sqlite3.OperationalError to sqlite3.Error'
- timing: last critique ts 1789610310.43, last chat ts 1789776569.54 -- window clean right now only because no task has completed in ~46 h

**severity adjustment:** keep

