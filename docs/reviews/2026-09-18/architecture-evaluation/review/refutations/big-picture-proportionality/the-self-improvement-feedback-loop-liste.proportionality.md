# refute:proportionality:The self-improvement feedback loop liste

*Workflow: review · Phase: Refute · Agent id: `a15efbe0c59d8d980` · Tool calls: 6*

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
    "title": "The self-improvement feedback loop listens on a topic the real self-patch path never publishes",
    "kind": "right-design-undermined",
    "severity": "critical",
    "claim": "World Model, Curiosity, Reflection and Planning all subscribe to `learn.self_patch.applied`, which is published only by learning/pipeline.py's PatchPipeline, which only runs on `learn.pipeline.run`, which nothing publishes; the path that actually lands Sim's code (orchestration/session.py `_land` via `worktree_land`) emits only a generic `task.completed`, so 94 real self-modifications are invisible to the subsystems whose job is to learn from them.",
    "evidence": [
      "simorgh/learning/service.py:98-116 -- \"Nothing anywhere publishes `learn.pipeline.run` ... The real `improve <path> <description>` path goes through `TASK_CREATE` to Orchestration's ordinary agent loop and never touches Learning at all.\"",
      "grep -rn LEARN_SELF_PATCH_APPLIED simorgh --include='*.py' | grep -v contracts/ -> the only publisher is simorgh/learning/pipeline.py:196; subscribers: simorgh/worldmodel/service.py:121, simorgh/planning/service.py:179, simorgh/curiosity/service.py:159, simorgh/reflection/service.py:193",
      "simorgh/orchestration/session.py:790-810 `_land` -> Outcome(\"completed\") only; simorgh/orchestration/worker.py:456-460 maps that to topics.TASK_COMPLETED; simorgh/worldmodel/service.py:382-388 `_on_task_finished` only calls update_goals, never add_change",
      "git log --format=%an | sort | uniq -c -> \"94 Simorgh\"; git log --author=Simorgh --shortstat -> \"files 96 ins 8069 del 512\"",
      "cat ~/.simorgh/worldmodel/self/SELF.md (v42, 2026-09-18 17:09) -> \"## What I've changed about myself (last 10)\\n(none recorded yet)\"",
      "tests/simorgh/learning/test_service.py:5 asserts the gap as documented behaviour (\"nothing anywhere publishes `learn.pipeline.run`\") rather than failing on it"
    ],
    "why_it_matters": "This is the stated purpose of the system. The Self Model's change history, Curiosity's growth events, Reflection's self-patch counters and Planning's follow-ups are all built and tested, and all fed by a pipeline that was superseded by the worktree loop. The architecture's growth layer is a spec'd machine bolted next to the machine that runs.",
    "recommendation": "Delete learning/pipeline.py and correlator.py (the superseded pipeline) and the `draft_candidate`-shaped topics with them. Have orchestration's `_land` (session.py:790) publish `learn.self_patch.applied` (or rename it `self.patch.landed`, owned by orchestration) with subject, commit sha and test counts on success and `...reverted` on a gate rollback (simloader already knows the rollback; worldmodel/service.py:133 `_ingest_loader_rollback` shows the seam). Add one seam test: run a fake patch task through Orchestration with a stub Execution and assert SELF.md gains a change_history entry.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Find publishers and subscribers of the self-patch topics | simorgh/learning/service.py:6:and knowledge distillation are not yet built -- `learn.pipeline.run{kind: simorgh/learning/service.py:35: topics.LEARN_PIPELINE_RU |
| 2 | Bash | Read learning service subscription and pipeline publish site |  for sub in self._subs: await sub.unsubscribe() self._subs.clear() #: Why this subsystem cannot currently do the thing it exists for. #: Two independent reasons |
| 3 | Bash | Read landing path, worker outcome mapping, worldmodel handlers, SELF.md, git authors, and the learning test |  -- the session edits the live tree as before, and the step says so rather than pretending.""" call = {"tool": "worktree_open", "args": {}} ok, summary, detail  |
| 4 | Bash | Check alternative change_history feeds, ledger occurrences, and self-commit stats | ---- add_change callers simorgh/worldmodel/service.py:335: m = add_change( simorgh/worldmodel/service.py:345: lambda m, now: add_change( simorgh/worldmodel/serv |
| 5 | Bash | Scan ledger streams for the topic and read task-completed handlers and pipeline dependents | ---- ledger streams action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl  |
| 6 | Bash | Check execution's skill publisher, superseded code size, worktree_land output, improve dispatch, and rollback seam | ---- execution skill acquired return announced async def _load_skill(self, name: str, *, path: str) -> object \| None: """Register the one named skill as a `skil |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line was re-read and holds. The only publisher of `learn.self_patch.applied` in simorgh/ outside contracts/ is simorgh/learning/pipeline.py:196, inside PatchPipeline, which is only constructed by the `learn.pipeline.run` handler (learning/service.py:84); the service's own UNREACHABLE constant (service.py:98-118) documents that nothing publishes that topic and `draft_candidate` is not a registered tool, and health() returns degraded on that basis. The real path is `improve` -> interface/dispatch.py:268 `TASK_CREATE{kind:"patch"}` -> Orchestration; session.py:790-810 `_land` returns Outcome("completed") and worker.py:456-460 maps it to `task.completed` only. Consumers exist and are wired (worldmodel/service.py:121,333-340 add_change; reflection/service.py:193,445-450; curiosity/service.py:159; planning/service.py:179) but nothing feeds them: the 1.4 GB ledger (118,215 streams) contains 0 occurrences of `learn.self_patch.applied` against 5,630 `task.completed`; ~/.simorgh/worldmodel/self/SELF.md v42 (2026-09-18 17:09) shows "## What I've changed about myself (last 10) / (none recorded yet)"; git shows 94 commits authored "Simorgh" (96 files, +8069/-512). I also checked for back-door feeds and found none: worldmodel's `_on_self_observation` explicitly ignores kind "change" (service.py:323-326), so Reflection's SELF_OBSERVATION re-publish would not help even if it fired; `_on_task_finished` (382-388) only touches goals; curiosity/planning `_on_task_completed` handle backlog/store transitions, not growth. Proportionality lens: this is not over-built for one laptop/one family; the consumers are already written and tested, and the fix is one publish in `_land` using fields `worktree.py` already returns (`Landed.commit`, landed count, gate note at worktree.py:250). The deletion half of the recommendation is cheap (pipeline.py 227 + correlator.py 38 lines + test_pipeline.py 296 lines) and safe: the live LEARN_SKILL_ACQUIRED publisher is Execution's apply_skill path (execution/service.py:622), not pipeline.py:169, and nothing else imports pipeline/correlator. Minor caveat: "94 real self-modifications" counts git author, not proof each landed via worktree_land (that path exists only since 2026-09-11), but the ledger's zero count makes the loop's openness independent of that. Design is right, implementation superseded it without moving the publish: right-design-undermined, severity kept because the system's stated thesis is the part that is silent, and the fix is proportionate.

### evidence

- grep -rn LEARN_SELF_PATCH_APPLIED simorgh --include='*.py' | grep -v contracts/ -> sole publisher simorgh/learning/pipeline.py:196; subscribers worldmodel/service.py:121, planning/service.py:179, curiosity/service.py:159, reflection/service.py:193
- simorgh/learning/service.py:98-118 UNREACHABLE = "no publisher for learn.pipeline.run, and draft_candidate is not a registered tool -- PatchPipeline cannot run; `improve` uses Orchestration's agent loop instead"; health() returns Health.degraded(self.UNREACHABLE) when idle
- simorgh/interface/dispatch.py:251-269: `improve` builds payload {kind:"patch", origin:"human", mode:"execute"} and publishes topics.TASK_CREATE
- simorgh/orchestration/session.py:790-810 `_land`: on ok returns Outcome("completed", ...) with no bus publish; simorgh/orchestration/worker.py:456-460 maps "completed" -> topics.TASK_COMPLETED
- simorgh/worldmodel/service.py:323-326 `_on_self_observation`: `if p.get("kind") != "limitation": return  # restart/change/success/failure are handled by their real producers directly` -- so Reflection's kind:"change" re-publish is not a back-door feed; :382-388 `_on_task_finished` only calls update_goals
- grep -rh -c 'learn.self_patch.applied' ~/.simorgh/ledger/streams | sum -> "applied events: 0"; grep -rh -c '"task.completed"' -> "task.completed events: 5630"; ledger is 1.4G, 118215 stream files
- ~/.simorgh/worldmodel/self/SELF.md line 1: "# Simorgh — Self Model (v42, 2026-09-18 17:09)"; lines 15-16: "## What I've changed about myself (last 10)" / "(none recorded yet)"
- git log --format=%an | sort | uniq -c -> 761 Saeed, 94 Simorgh, 1 iSK; git log --author=Simorgh --shortstat -> files 96 ins 8069 del 512; sample self-commits dated 2026-09-15/16
- simorgh/execution/worktree.py:250 `return Landed(True, f"landed {landed} commit(s) on main: {main_sha[:12]} -> {new_main[:12]}{gate_note}", ...)` -- sha and gate outcome already available to `_land`
- simorgh/execution/service.py:622: the live LEARN_SKILL_ACQUIRED producer is apply_skill's re-publish in Execution, so deleting pipeline.py:169 loses nothing; grep for importers of learning.pipeline/correlator -> only learning/service.py and tests/simorgh/learning/test_pipeline.py
- wc -l -> pipeline.py 227, correlator.py 38, test_pipeline.py 296: the superseded code the recommendation deletes
- tests/simorgh/learning/test_service.py:1-10 docstring asserts the unreachability as intended health behaviour rather than failing on it

**severity adjustment:** keep

