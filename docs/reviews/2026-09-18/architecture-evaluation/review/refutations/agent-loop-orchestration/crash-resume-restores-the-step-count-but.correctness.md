# refute:correctness:Crash-resume restores the step count but

*Workflow: review · Phase: Refute · Agent id: `ad68be1f95f3da65f` · Tool calls: 7*

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
    "title": "Crash-resume restores the step count but not the context: the resumed model starts blind with fewer steps",
    "kind": "bug",
    "severity": "high",
    "claim": "restore_session rebuilds session.steps and steps_used from the ledger after a worker crash, but session.messages is only populated when a progress note exists (re-grounding is off by default) and session.carried is rendered only from earlier attempts, so the new worker asks the model to continue a task whose previous steps it cannot see while charging it for them.",
    "evidence": [
      "simorgh/orchestration/resume.py:117-136: `if last[\"ended\"] is None:` restores steps and `session.budget.steps_used = len(last[\"steps\"])`; :127-131 sets session.messages only `if last.get(\"note\")`; :132-133 `if len(attempts) > 1: session.carried = carried_note(attempts[:-1])` (the crashed attempt itself is never rendered)",
      "simorgh/orchestration/config.py:60 `reground_every_steps: int = 0` and ~/.simorgh/simorgh.toml has no [orchestration] section, so no note is ever written in production",
      "simorgh/orchestration/context.py:141-160 assemble() only injects task, carried and session.messages",
      "tests/simorgh/orchestration/test_attempts.py:65 `test_a_crashed_attempt_is_continued_with_its_steps_counted` asserts the count, not that the model can see the steps"
    ],
    "why_it_matters": "Crash-resume is the reason the lease/heartbeat/claim machinery exists at all; as built it produces a session that is worse than a fresh retry (less budget, no memory of what was done, edits in the tree it does not know about). The 'unconnected wire' shape the project already names: the resume slot is designed, the budget side is written, the context side is not.",
    "recommendation": "In the crash branch, render the crashed attempt's steps with carried_note([last]) into session.carried (the same renderer retries use), and prefer to always write the progress note by turning reground_every_steps on. Add a test that a resumed session's first THINK contains the prior step summaries.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/orchestration/resume.py | 1 """What a Session inherits from the `task:<id>` stream before it runs. 2 3 Two different situations look alike from here -- a task whose last 4 worker died mi |
| 2 | Bash | Inspect config, context assembly and reground wiring |  session. """ from __future__ import annotations from dataclasses import dataclass @dataclass(frozen=True) class Config: workers: int = 1 # Whether Verification |
| 3 | Bash | Check whether session.steps or resumed_from_step reach the prompt |  "Their uncommitted edits to " + ", ".join(sorted(session.uncommitted)) + " are STILL IN THE TREE: do not re-apply them -- run the tests and commit them." ) els |
| 4 | Bash | Check worker resume path, session prompt build, and tests |  # a higher-weight task that became ready while this worker was # busy (`planning/scheduler.py::better_ready`). Everything below # -- the session, the heartbeat |
| 5 | Bash | Check message init in run, prior reviews, and crash-resume integration test | 890: if (session.profile.scaffold != "chat" and session.messages and not session.budget.is_last_step 913: and session.profile.scaffold != "chat" and session.mes |
| 6 | Bash | Check run() seeding and the crash-resume integration test assertions |  async def run(self, session: Session, *, user_text: str = "") -> Outcome: """Run the session, and never leave a change behind that nobody committed. Live-caugh |
| 7 | Bash | Check whether a resumed session reuses the crashed worker's worktree | 677: await self._open_worktree(session) 765: async def _open_worktree(self, session: Session) -> None: async def _open_worktree(self, session: Session) -> None: |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line reads as claimed in the current tree. simorgh/orchestration/resume.py:117-144 is the crash branch: it calls session.record(Step(...)) for each prior step (populating session.steps), sets session.budget.steps_used = len(last["steps"]) and resumed_from_step, but sets session.messages ONLY under `if last.get("note"):` (:126-131) and session.carried only from attempts[:-1] (:132-133) -- the crashed attempt itself is never rendered by carried_note. The Assembler (simorgh/orchestration/context.py:148-186) builds the THINK prompt from the memory block, the task text, session.carried (with the uncommitted-edits note nested INSIDE `if session.carried:`) and session.messages; nothing anywhere renders session.steps into a prompt (grep of session.steps across orchestration/ shows only budget, verification payload, cost and narration uses). session.py:660-690 run() does not seed messages from restored steps. In production the note is never written: config.py:60 `reground_every_steps: int = 0`, ~/.simorgh/simorgh.toml has sections [voice] [interface] [execution] [cognition]... and no [orchestration], and session.py:890-892 only calls _reground when `progress_note.due(...)` with self._reground_every (0 = never). So a crash-resumed session gets a THINK whose only user turn is the task description, with steps_used already charged and is_last_step (api.py:77-82) computed against the spent count. Nuance on 'edits in the tree it does not know about': worktree_open reopens the same task worktree at the same commit (session.py:765-768), so the dead worker's uncommitted edits ARE in the tree the resumed session edits, and because the tree note in context.py:171-179 is gated on session.carried (empty for a first-attempt crash) the model is not told. Tests: test_attempts.py:65-73 asserts count/steps length and carried=="" (it actually pins the blindness); test_clean_retries.py:59-66 covers only the note path; the integration test test_local_multi_worker_crash_resume.py:218-240 uses a scripted fake cognition that answers 'done', so it proves no re-execution, not that the model can see prior steps. Not in the known-findings list and grep of docs/architecture-audit-2026.md, architecture-review-2026-09-18.html and architecture-third-opinion-2026-09-18.md for 'resume'/'crash' returns nothing. Classification: (b) right design, implementation undermines it -- the project's own 'unconnected wire' shape. Severity: 'high' is defensible for the code-task path but the practical blast radius is bounded: it fires only when a worker actually dies mid-attempt (SIGKILL/crash, not a blocked/failed retry, which is handled well), the default max_steps for a chat task is small, and the retry path after the resumed attempt blocks does carry the crashed attempt's steps via carried_note(attempts). I would keep severity as is or lower to medium depending on how often crashes occur in practice; I did not measure crash frequency in the ledger.

### evidence

- simorgh/orchestration/resume.py:117-124: `if last["ended"] is None:` loops `session.record(Step(...))` over last["steps"] and sets `session.budget.steps_used = len(last["steps"])`
- simorgh/orchestration/resume.py:126-131: `if last.get("note"):` is the only place session.messages is assigned in the crash branch
- simorgh/orchestration/resume.py:132-133: `if len(attempts) > 1: session.carried = carried_note(attempts[:-1])` -- crashed attempt excluded
- simorgh/orchestration/context.py:148-186: assemble() appends memory block, `{"role":"user","content": task}`, the carried block (uncommitted-tree note only inside `if session.carried:`), then `blocks.extend(session.messages)`; session.steps never referenced
- grep -rn 'session\.steps' simorgh/orchestration/*.py: only budget/verification/cost/narration uses (session.py:285,300,323,331,355,694,1477,1515,1864,1900,1914,1917; worker.py:539) -- no prompt rendering
- simorgh/orchestration/config.py:60 `reground_every_steps: int = 0` with comment '0 is off, the default until its benchmark arm wins'
- grep -n '^\[' ~/.simorgh/simorgh.toml -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]; no [orchestration]
- simorgh/orchestration/session.py:890-892: _reground only when `progress_note.due(session.budget.steps_used, session.reground_at, self._reground_every)`; session.py:643 `self._reground_every = max(0, int(reground_every_steps or 0))`
- simorgh/orchestration/session.py:765-768 _open_worktree docstring: 'the same commit on a retry that resumes an earlier attempt's tree' -- resumed session works in the same task worktree
- simorgh/orchestration/api.py:77-82 is_last_step = steps_used >= max_steps, so the restored count shortens the resumed attempt
- tests/simorgh/orchestration/test_attempts.py:65-73 asserts spent==2, steps_used==2, len(steps)==2, carried=='' -- no assertion on messages/prompt
- tests/simorgh/integration/test_local_multi_worker_crash_resume.py:218-240 asserts one read_file proposal and result_summary 'done' from a scripted fake cognition; does not inspect worker 2's prompt
- grep -n -i 'resume\|crash' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> no matches

**severity adjustment:** keep

