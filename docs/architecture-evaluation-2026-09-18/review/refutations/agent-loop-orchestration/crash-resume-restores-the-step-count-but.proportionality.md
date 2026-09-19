# refute:proportionality:Crash-resume restores the step count but

*Workflow: review · Phase: Refute · Agent id: `afc1e49b38c31a132` · Tool calls: 8*

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
| 2 | Bash | Read config, context assembly, session use of reground and progress note |  session. """ from __future__ import annotations from dataclasses import dataclass @dataclass(frozen=True) class Config: workers: int = 1 # Whether Verification |
| 3 | Bash | Check config wiring and where resumed steps feed the model context | /Users/saeed/.simorgh/simorgh.toml 1:[voice] 15:[interface] 18:[execution] 22:[cognition] 24:[cognition.providers] 26:[cognition.providers.ollama] --- (eval):1: |
| 4 | Bash | Check config wiring, callers of restore_session, the step log and the cited test | simorgh/orchestration/worker.py:138: reground_every_steps: int = 0, keep_recent_steps: int = 2, clean_revisions: bool = False, simorgh/orchestration/worker.py:1 |
| 5 | Bash | Read the THINK message assembly, worker resume call site, Session fields and ledger layout |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 6 | Bash | Check the rest of assemble, scaffolds, design doc stance on resume, and ledger stream layout |  why=unavailable)}) # Live-caught by the same audit: this was sent on the *first* step # only (`session.py` clears `pending_user_text` after one use) and # neve |
| 7 | Bash | Read design doc's resume section and measure real crash-resumes in the ledger | - The ledger has `task.progress`. - The assembled prompt for a 30-step scripted session stays under a bound. ## 4. Change B: clean retries A retry starts from t |
| 8 | Bash | Read the note-based crash-resume test and heartbeat references |  self.assertIn("grep for callers", text, "a step after the note is still listed") self.assertNotIn("read tokenizer.py", text, "steps the note summarised are not |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The code says what the finding says. In simorgh/orchestration/resume.py:117-144 the crash branch (`if last["ended"] is None`) replays every prior step into `session.steps` and sets `session.budget.steps_used = len(last["steps"])`, but the only thing that reaches the model's transcript is the progress note (`session.messages = [...]` at :131, guarded by `if last.get("note")`), and `session.carried` is rendered from `attempts[:-1]` only (:132-133), so the crashed attempt's own steps are never rendered anywhere the model can see. Assembler.assemble (context.py:141-186) injects only the memory block, the task text, `session.carried` and `session.messages`; nothing reads `session.steps` into the prompt (grep of session.py shows `session.steps` used only for verification payloads, cost sums, and mechanical checks). The note is never written in production: config.py:60 `reground_every_steps: int = 0`, ~/.simorgh/simorgh.toml has sections [voice] [interface] [execution] [cognition] only, and the only readers of `reground_every_steps` are the pass-through in service.py:85 -> worker.py:177 -> session.py:643 with no env override. Even with regrounding on, the implementation is short of its own design: docs/plans/long-run-context-design.md:132-134 says a crash resume "restores the note and the last keep_recent_steps steps", but resume.py:126-131 restores the note alone and the steps after `note_at` (still in `last["steps"]`, still charged) are dropped from context. The tests confirm the count and the note case only (test_attempts.py:65-73, test_clean_retries.py:59-66); none asserts the steps are visible. On the skeptic lens: this is a genuine bug of the project's named "unconnected wire" shape, not an over-built design, and the recommended fix is a one-line call to the renderer that already exists (`carried_note([last])`), so it is proportionate. The measured frequency argues against "high": a scan of the real ledger (2,431 task streams, 2,454 attempts) finds 8 crash-resumes across 5 tasks (~0.3% of attempts), all with steps already spent (median 15, max 58) and none with a note. So it is real, cheap to fix, but rare on this one-laptop system. The finding also overstates that crash-resume is "the reason the lease/heartbeat/claim machinery exists at all" (worker.py:304-367 uses the lease for crash detection and preemption too), which does not change the bug.

### evidence

- simorgh/orchestration/resume.py:117-125: crash branch replays `last["steps"]` into session.record() and sets `session.budget.steps_used = len(last["steps"])`
- simorgh/orchestration/resume.py:126-131: `if last.get("note"):` is the only place session.messages is populated on crash-resume
- simorgh/orchestration/resume.py:132-133: `if len(attempts) > 1: session.carried = carried_note(attempts[:-1])` -- the crashed attempt itself is excluded
- simorgh/orchestration/context.py:168-186: assemble() appends task, then `session.carried`, then `blocks.extend(session.messages)`; no reference to session.steps
- grep -n 'session.steps' simorgh/orchestration/session.py: only verification payload (:1864), delegate count (:1477), cost sums (:1914-1917), pause (:1900) -- none feed the prompt
- simorgh/orchestration/config.py:60 `reground_every_steps: int = 0`; grep -n '^\[' ~/.simorgh/simorgh.toml -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama] (no [orchestration])
- grep -rn reground_every_steps simorgh -> only config.py:60, service.py:85, worker.py:138/177, session.py:608/643 (pass-through, no env override)
- docs/plans/long-run-context-design.md:132-134: 'A crash resume, the same attempt continuing, also restores the note and the last keep_recent_steps steps rather than an empty transcript' -- code restores the note only
- tests/simorgh/orchestration/test_attempts.py:65-73 asserts spent==2, steps_used==2, len(steps)==2, carried=='' -- nothing about the model's view; tests/simorgh/orchestration/test_clean_retries.py:59-66 covers only the with-note case
- Ledger scan (python over ~/.simorgh/ledger/streams/task%3A*.jsonl): 'task streams 2431 attempts 2454 / crash-resumes (unended attempt followed by another start) 8 of which with >=1 step 8 with note 0 tasks affected 5 / steps lost on resume: median 15.0 max 58'

**severity adjustment:** lower

**corrected claim:** Crash-resume (resume.py:117-144) restores the step count and charges the budget for the dead worker's steps, but renders none of those steps into the model's context unless a progress note exists; the note is never written in production (reground_every_steps=0, no [orchestration] section in simorgh.toml), and even with a note the steps after it are dropped, contrary to the design doc. It is a real but rare defect: 8 of 2,454 attempts in the live ledger (5 tasks), each losing a median of 15 already-charged steps of context. The fix is one line using the existing carried_note renderer, so severity is medium rather than high.

