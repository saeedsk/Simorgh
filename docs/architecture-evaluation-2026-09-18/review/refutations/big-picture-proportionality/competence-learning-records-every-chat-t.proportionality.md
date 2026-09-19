# refute:proportionality:Competence learning records every chat t

*Workflow: review · Phase: Refute · Agent id: `a92831ae6abe025f5` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Competence learning records every chat turn as `unknown`, so 91% of the learning signal is noise",
    "kind": "bug",
    "severity": "high",
    "claim": "learning/outcomes.py derives task_type from the first event of `task:<task_id>`; chat turns get a task_id and a `task.completed` but no created event in a task stream, so 2,466 of 2,714 outcome rows are `unknown` with `succeeded=True`, and the Self Model's competence section reports 'unknown 97%'.",
    "evidence": [
      "simorgh/learning/outcomes.py:84-94 -- `task_type = \"unknown\"` then `kind = p.get(\"kind\", \"unknown\")` from `self._ledger.read(f\"task:{task_id}\")`; :119-124 on_task_completed records `succeeded=True, weight=1.0` regardless",
      "grep -o '\"task_type\":\"[a-z_:]*\"' ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl | sort | uniq -c -> \"2466 unknown / 125 research / 81 patch / 3 skill / 1 project\" of 2714 rows",
      "task streams: 103 `created` events vs 2334 `task.completed` events (ls | grep '^task%3A' | xargs cat | grep -o '\"type\":\"...\"') -- the difference is chat turns",
      "~/.simorgh/worldmodel/self/SELF.md -> \"## How well I do it\\n- unknown 97% (2466)\"",
      "docs/blueprint/07-post-cutover-review.md:100-103 named the same defect on 2026-09-06 (\"a floor reply and a great reply score identically\"); it is still current"
    ],
    "why_it_matters": "Curiosity's competence-gap drive, Reflection's calibration and the Self Model's 'how well I do it' all read this table. With 91% of rows typed `unknown` and always successful, every downstream 'learned' number is arithmetic on noise, and the creator cannot tell whether Sim is getting better.",
    "recommendation": "Do not record chat turns as competence outcomes at all (they have no verdict), or record them under kind `chat` only when a `verify.result` exists for the turn. Make OutcomeRecorder refuse to write a row whose task_type is `unknown` and count refusals in health. One assertion in the existing integration suite: after a chat turn, learn:outcomes gains no `unknown` row.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/learning/outcomes.py | 1 """`OutcomeRecorder`: turns `task.completed` / `task.failed` / `task.blocked` 2 (the terminal, or not-yet-terminal-but-informative, facts about a task) 3 into |
| 2 | Bash | Count task_type values in learn:outcomes ledger and show SELF.md competence | --- outcomes task_type counts 2466 "task_type":"unknown" 125 "task_type":"research" 81 "task_type":"patch" 9 "task_type":"patch:simorgh/persona" 7 "task_type":" |
| 3 | Bash | Check whether unknown rows are chat turns lacking created events | --- unknown & succeeded true 2403 --- task stream for last unknown id task%3A2de3c380-35cf-4ff3-8f9b-0a1537f8fcfa.jsonl trace%3A2de3c380-35cf-4ff3-8f9b-0a1537f8 |
| 4 | Bash | Locate chat task lifecycle writers and competence consumers | --- who writes created simorgh/planning/store.py:220: event = Event(stream=stream, type="created", ts=now, trace_id=tid, causation_id=None, payload=payload) --- |
| 5 | Bash | Read competence consumers and chat worker path | --- drives.py 20-80 class DriveEngine: config: Config def score_area(self, area_name: str, ctx: DriveContext, focus_multiplier: float = 1.0) -> dict[str, float] |
| 6 | Bash | Check whether unknown rows reach curiosity gaps and reflection calibration | --- reflection calibration source `summary()` and take the whole pass down with it -- `-3.0` indexed `bins[-30]` (IndexError), NaN and inf died in `int()` -- an |
| 7 | Bash | Check reflection and curiosity handling of unknown outcome rows |  async def _on_outcome_recorded(self, message: Message) -> None: p = message.payload self._patterns.add(p["task_type"], p["succeeded"], p.get("strategy"), messa |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual core is confirmed against code and the live ledger. Chat turns are deliberately run without a Planning task (simorgh/orchestration/worker.py:387-402 docstring: "a plain conversational percept has no Planning task behind it"), so their `task:<session_id>` stream begins with `task.started` whose payload is only `{task_id, worker_id}` (simorgh/orchestration/session.py:876) and never a `created` event carrying `kind` (only planning/store.py:220 writes `created`). OutcomeRecorder reads `events[0].payload.get("kind","unknown")` (outcomes.py:84-94) and records `succeeded=True, weight=1.0` on every task.completed regardless of verdict (outcomes.py:115-125). The live ledger has 2466/2714 rows typed `unknown`, and SELF.md line 10 reads "- unknown 97% (2466)". Notably the author engineered `run_index` precisely so that every chat turn IS recorded (outcomes.py:63-83), so this is a design that intends to score chat but never connected the `kind` wire -- the project's documented "unconnected wire" shape -- plus the older defect that chat has no verdict at all (blueprint 07:100-103, still current). Two corrections: (1) 2403, not 2466, of the unknown rows are succeeded=True (24 blocked, 39 failed). (2) The blast radius in "why_it_matters" is overstated. Curiosity's competence-gap drive matches gaps only where `g.task_type.startswith(area_name)` for code-area names (curiosity/drives.py:38-48), so `unknown` never matches any area and the drive is unaffected. Reflection's calibration records only rows with a numeric `confidence` (reflection/service.py:436-441) and 0 of the 2466 unknown rows carry `stated_confidence`, so calibration is unaffected too. What is actually polluted: the Self Model's competence section (worldmodel/selfmodel.py:375-378 sorts by samples, so `unknown` is always the headline), Reflection's pattern miner (`_patterns.add("unknown", True, ...)`), and the CompetenceTable itself. Typed rows for patch/research (125+81+~30 area-typed) remain usable. Proportionality lens: the recommendation is small (skip chat in OutcomeRecorder, or carry `session.kind` into the task.started payload and require a verdict; one integration assertion) -- it is not over-built for a one-laptop system, and it removes work rather than adding it. Because the two most consequential consumers are immune and the fix is trivial, severity should drop from high to medium: it is a genuine bug (c) sitting on a sound design (b), not an architectural error.

### evidence

- simorgh/learning/outcomes.py:84-94 -- task_type="unknown" default; kind read from events[0].payload of task:<id>; :115-125 on_task_completed records succeeded=True, weight=1.0 unconditionally, verdict="unknown" unless a cached verify ref exists
- simorgh/learning/outcomes.py:63-83 -- docstring: chat turn's task_id IS its session_id; run_index added so every turn is recorded (author intends chat to be scored)
- simorgh/orchestration/worker.py:387-402 -- run_percept_chat: "a plain conversational percept has no Planning task behind it"; Session(kind="chat") but kind never reaches the ledger stream
- simorgh/orchestration/session.py:876 -- task.started payload is {task_id, worker_id} only; grep 'type="created"' simorgh -> only simorgh/planning/store.py:220
- grep -o '"task_type":"[a-zA-Z_:/.-]*"' ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl | sort | uniq -c -> 2466 unknown, 125 research, 81 patch, 9 patch:simorgh/persona, 7 patch:simorgh/interface, ... of 2714 rows (wc -l)
- grep '"task_type":"unknown"' ... | grep -c '"succeeded":true' -> 2403 (24 verdict=blocked, 39 verdict=failed among unknown)
- cat ~/.simorgh/ledger/streams/task%3A*.jsonl | grep -o '"type":"..."' | sort | uniq -c -> 103 created vs 2334 task.completed vs 2454 task.started
- ~/.simorgh/ledger/streams/task%3A2de3c380-...jsonl (the newest unknown row's stream) contains only task.started, task.step, task.completed -- no created event
- ~/.simorgh/worldmodel/self/SELF.md:9-10 -> "## How well I do it\n- unknown 97% (2466)"; tail -200 of learn:outcomes -> 199 unknown (still current, not historical)
- simorgh/curiosity/drives.py:38-48 -- _gap matches only g.task_type.startswith(area_name); 'unknown' matches no code area, so the competence-gap drive is NOT corrupted
- simorgh/reflection/service.py:436-441 -- calibration recorded only when payload has numeric confidence; grep -c stated_confidence on unknown rows -> 0, so calibration is NOT corrupted; _patterns.add("unknown", ...) IS fed
- simorgh/worldmodel/selfmodel.py:375-378 -- competence section sorts by samples desc, so 'unknown' is always the headline row
- docs/blueprint/07-post-cutover-review.md:100-103 -- "Chat completions feed learn.outcome.recorded{succeeded: True} unconditionally ... noise dressed as learning" (2026-09-06), still true

**severity adjustment:** lower

**corrected claim:** Chat turns run without a Planning task (worker.py:387-402), so their task:<session_id> stream has no `created` event and OutcomeRecorder (outcomes.py:84-94) types them `unknown`; on task.completed it records succeeded=True regardless of any verdict (outcomes.py:115-125). Today 2466 of 2714 learn:outcomes rows are `unknown` (2403 of them succeeded=True), and SELF.md's competence section reads "unknown 97% (2466)". The author intended chat to be scored (run_index was added so every turn is recorded, outcomes.py:63-83) but never carried session.kind into the stream and chat has no verdict, so the chat rows carry no signal. Blast radius is narrower than claimed: Curiosity's gap drive only matches code-area task_types (drives.py:38-48) and Reflection's calibration only ingests rows with a stated confidence (reflection/service.py:439-441; none of the unknown rows have one), so both are unaffected. What is polluted is the Self Model competence section, Reflection's pattern miner, and the CompetenceTable's aggregate. Fix is small and proportionate: skip chat in OutcomeRecorder unless a verify.result exists (or carry kind and require a verdict), refuse `unknown` rows, one integration assertion.

