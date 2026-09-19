# refute:correctness:The self-improvement feedback loop liste

*Workflow: review · Phase: Refute · Agent id: `ad23d41b8b7f2d702` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 2 | Bash | Show topic constants for self-patch in contracts | 160:LEARN_PIPELINE_RUN = "learn.pipeline.run" 167:LEARN_SELF_PATCH_APPLIED = "learn.self_patch.applied" 168:LEARN_SELF_PATCH_REVERTED = "learn.self_patch.revert |
| 3 | Bash | Read learning service gap comment, pipeline publish, and pipeline.run publishers |  for sub in self._subs: await sub.unsubscribe() self._subs.clear() #: Why this subsystem cannot currently do the thing it exists for. #: Two independent reasons |
| 4 | Bash | Read the _land path, worker outcome mapping, and worldmodel handlers |  -- the session edits the live tree as before, and the step says so rather than pretending.""" call = {"tool": "worktree_open", "args": {}} ok, summary, detail  |
| 5 | Bash | Find every writer of change_history and every other landing/observation path | simorgh/worldmodel/service.py:25: add_change, simorgh/worldmodel/service.py:335: m = add_change( simorgh/worldmodel/service.py:345: lambda m, now: add_change( s |
| 6 | Bash | Check git authorship counts, the live SELF.md change history, and the learning test |  1 iSK 761 Saeed 94 Simorgh ---- files 96 ins 8069 del 512 ---- total 8 drwxr-xr-x@ 3 saeed staff 96 Sep 9 21:27 . drwxr-xr-x@ 3 saeed staff 96 Sep 9 21:27 .. - |
| 7 | Bash | Check whether prior reviews already report this finding | docs/architecture-audit-2026.md:33: - **Target:** `simorgh/worldmodel/selfmodel.py` and `simorgh/learning/pipeline.py`. docs/architecture-audit-2026.md:36: - ** |
| 8 | Bash | Read what the prior reviews say about the self-patch pipeline | streams: dict # channel -&gt; subprocess.Popen (ffmpeg). A real unconnected wire it found independently learning/pipeline.py:74 dispatches tool="self_patch.draf |
| 9 | Bash | Check whether Execution publishes anything on land and whether any path tags improve-tasks for the Self Model |  if not task_id: return ToolResult(ok=False, error="refused: a worktree belongs to a task, and this call names none") try: landed = await self._manager.land(tas |
| 10 | Bash | Confirm improve goes to TASK_CREATE and read the Curiosity and Reflection self-patch handlers |  return Outcome(render_mod.command_panel(name, enabled=render_mod.color_enabled(), unicode=render_mod.unicode_mode() != "off")) if name == "improve": args, step |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every claim verifies against the code today, not history. (1) The only publisher of `learn.self_patch.applied` outside contracts/ is simorgh/learning/pipeline.py:196, inside PatchPipeline, which is only constructed in Learning's `_on_pipeline_run` handler (learning/service.py:84) for `learn.pipeline.run`; the only .py files that mention `learn.pipeline.run`/LEARN_PIPELINE_RUN are learning/service.py, contracts/topics.py, contracts/messages/learn.py and three tests -- no publisher exists. Learning's own health() returns degraded with `UNREACHABLE` saying exactly this (service.py:98-125). (2) Subscribers are real and all four do substantive work on that topic: worldmodel/service.py:121 -> `_on_self_patch_applied` (line 332-340) which is the ONLY caller of `add_change(kind="self_patch")`; planning/service.py:179; curiosity/service.py:159 -> `_on_growth_event` (277-283, offers growth + touches staleness); reflection/service.py:193 -> `_on_self_patch` (445-451). (3) The real path: `improve` in interface/dispatch.py:251-271 builds `{"kind":"patch"}` and publishes TASK_CREATE; orchestration/session.py:790-810 `_land` calls `worktree_land` and returns `Outcome("completed")`; orchestration/worker.py:456-460 maps that to plain `topics.TASK_COMPLETED` with no patch-specific payload; execution/worktree.py:392-394 only records a `side_effects` string, publishes nothing. worldmodel/service.py:382-388 `_on_task_finished` only calls `update_goals`, never `add_change`. Reflection's SELF_OBSERVATION `kind:"change"` (reflection/service.py:448) is itself only fired from the dead topic, and World Model discards non-limitation observations anyway (service.py:325). (4) Live state: `git log --format=%an | sort | uniq -c` -> 94 Simorgh / 761 Saeed; Simorgh's shortstat totals files 96, ins 8069, del 512; ~/.simorgh/worldmodel/self/SELF.md is v42 dated 2026-09-18 17:09 and its "What I've changed about myself (last 10)" section reads "(none recorded yet)". (5) tests/simorgh/learning/test_service.py:1-9 asserts the degraded report as intended behaviour. Already-known check: prior reviews (architecture-review-2026-09-18.html:103-107, third-opinion 4.3, audit item 2) report only the narrower "self_patch.draft tool not registered" fact about pipeline.py:74; none of them observes that the four consumer subsystems' self-patch handlers are fed solely by that dead pipeline while the live worktree landing path emits nothing to them, nor that 94 landed self-commits left SELF.md's change history empty. That is materially new. Minor nuance, not a refutation: the Self Model does learn that an improve task existed via `update_goals` (kind recorded at worldmodel/service.py:376), so Sim is not entirely blind to the task -- but it gets no subject/commit/tests and no change_history entry, and Curiosity/Reflection/Planning get nothing at all. Severity "critical" is defensible for a system whose stated purpose is self-improvement; the fix is small (publish one message from `_land`), so "critical" describes impact, not effort.

### evidence

- grep -rn LEARN_SELF_PATCH_APPLIED simorgh --include='*.py' | grep -v contracts/ -> sole publisher simorgh/learning/pipeline.py:196; subscribers worldmodel/service.py:121, planning/service.py:179, curiosity/service.py:159, reflection/service.py:193
- grep -rln 'LEARN_PIPELINE_RUN\|learn\.pipeline\.run' simorgh tools tests -> simorgh/learning/service.py, simorgh/contracts/topics.py, simorgh/contracts/messages/learn.py + 3 test files; no publisher
- simorgh/learning/service.py:98-119: UNREACHABLE = "no publisher for learn.pipeline.run, and draft_candidate is not a registered tool -- PatchPipeline cannot run; `improve` uses Orchestration's agent loop instead"; health() returns Health.degraded(self.UNREACHABLE) when idle
- simorgh/interface/dispatch.py:251-271: `improve` builds payload {"kind": "patch", "origin": "human", "mode": "execute"} and publishes topics.TASK_CREATE
- simorgh/orchestration/session.py:790-810 `_land`: on ok returns Outcome("completed", result_summary=...) -- no bus publish; simorgh/orchestration/worker.py:456-460 maps "completed" -> topics.TASK_COMPLETED with payload {task_id, result_summary, artifacts, verification_ref}
- simorgh/execution/worktree.py:392-394: WorktreeLandTool returns ToolResult(side_effects=(f"worktree_land:{landed.commit}",)) and publishes nothing
- grep -rn 'add_change\b' simorgh -> only callers are worldmodel/service.py:335 (_on_self_patch_applied), :345 (_on_self_patch_reverted), :356 (skill acquired); worldmodel/service.py:382-388 `_on_task_finished` calls only update_goals
- simorgh/worldmodel/service.py:325: `if p.get("kind") != "limitation": return` -- Reflection's SELF_OBSERVATION kind:"change" (reflection/service.py:445-451) is discarded, and is itself only emitted from the dead topic
- git log --format=%an | sort | uniq -c -> 1 iSK / 761 Saeed / 94 Simorgh; git log --author=Simorgh --shortstat totals: files 96 ins 8069 del 512; latest Simorgh commit bbaf8e6 2026-09-16
- ~/.simorgh/worldmodel/self/SELF.md (734 bytes, mtime Sep 18 17:09, header 'Self Model (v42, 2026-09-18 17:09)') line 15-16: '## What I've changed about myself (last 10)' / '(none recorded yet)'
- tests/simorgh/learning/test_service.py:1-9 docstring asserts 'nothing anywhere publishes `learn.pipeline.run`' as the expected degraded state
- Prior reviews (docs/architecture-review-2026-09-18.html:103-107; docs/architecture-third-opinion-2026-09-18.md:115-117; docs/architecture-audit-2026.md:33-36) only report the unregistered self_patch.draft tool at pipeline.py:74; none reports that the four consumers' self-patch handlers are orphaned or that the worktree landing path emits no learn/self-patch event

**severity adjustment:** keep

