# refute:correctness:A chat turn can edit the live checkout,

*Workflow: review · Phase: Refute · Agent id: `a0507257e3e9a04b7` · Tool calls: 8*

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
    "title": "A chat turn can edit the live checkout, cannot commit, and leaves the edit orphaned 'for a next attempt' that never comes",
    "kind": "bug",
    "severity": "high",
    "claim": "The CHAT profile offers apply_source_patch and replace_in_file but not git_commit, chat is not a worktree kind, and on completion with uncommitted edits the runner converts the outcome to blocked and _continues returns True on attempt 1, so _keep_uncommitted leaves a source edit in the live tree with a task.edits_kept record on a task stream no worker will ever re-claim.",
    "evidence": [
      "simorgh/orchestration/profiles.py:59 CHAT tools include 'apply_source_patch', 'replace_in_file', 'install_package', 'run_script'; the tuple contains no 'git_commit'",
      "simorgh/orchestration/session.py:63 `WORKTREE_KINDS = frozenset({\"patch\", \"skill\"})` so chat edits the live tree",
      "simorgh/orchestration/session.py:712-735 completed + uncommitted -> Outcome('blocked', reason=UNCOMMITTED_REASON...)",
      "simorgh/orchestration/session.py:827-841 _continues: attempt 1 < KEEP_EDITS_UNTIL_ATTEMPT (:389 = 6) and reason startswith UNCOMMITTED_REASON -> True; :846 _keep_uncommitted appends task.edits_kept",
      "worker.py:run_percept_chat: a chat session is ephemeral; nothing re-offers its task id",
      "Measured in ~/.simorgh/ledger: `uuid-keyed (chat) task streams: 2328 | task.edits_kept events: 2 | task.blocked with 'uncommitted': 2`, kept paths: ['simorgh/voice/config.py'] and ['simorgh_skills/hot_stocks.py']",
      "The creator's own memory note 'Live checkout, keep it committed: sim.sh boots from the repo I edit; half-done edits get gated and block rollback' is the operator-side symptom"
    ],
    "why_it_matters": "A chat turn silently modified simorgh/voice/config.py in the running checkout that simloader gates and rolls back; the user was told '(Not finished: finished with uncommitted changes)' and the file stayed dirty. This is the exact failure the worktree design was built to prevent, reachable from the most common entry point.",
    "recommendation": "Either refuse source writes from a chat session (Execution already receives scope.kind='chat', execution/tools.py:1791 uses it for start_task) and route them through start_task into a patch worktree, or make _continues return False for kind=='chat' so the edit is discarded and the reply says so. Smallest safe change: `if session.kind == \"chat\": return False` at session.py:832 plus a profile tweak restricting chat writes to workspace/.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read CHAT profile tools and session constants |  "sim_command", # "did you read your git log?" -- Sim: "I can't run git from here" # (the creator, 2026-09-16). Read-only: the three write tools # stay in the t |
| 2 | Bash | Read completion, _continues, _keep_uncommitted |  # "says it changed a file, and no edit was applied". complete_log=session.attempt <= 1 and not session.carried, ) if claims: step = Step(session.next_step_no() |
| 3 | Bash | Trace uncommitted population and chat-kind handling | 96: session.uncommitted.add(path) 105: session.uncommitted.discard(path) 712: if session.uncommitted and outcome.kind == "completed": 725: f"answered as finishe |
| 4 | Bash | Read uncommitted tracking, chat session creation, finishing-tools branch, and chat write scopes |  kind, _, path = str(effect).partition(":") if not path: continue if kind in ("file_write", "file_create"): session.wrote.add(path) # Scratch is written, never  |
| 5 | Bash | Check write scopes, start_task chat check, known-findings docs, ledger layout | 1556:def _write_scoped_file(config: Config, subject: str, code: str, *, write_scopes: tuple[str, ...], 1559: `subject`, refusing anything outside `write_scopes` |
| 6 | Bash | Check write scopes config, ledger streams, edits_kept usage, resume path | 85: # Readable, never writable by a patch: `write_scopes_source` does 90: # off; writable too (`write_scopes_source` below) -- the one 99: # question that `writ |
| 7 | Bash | Measure ledger: chat task streams, edits_kept events, and current state of kept paths |  # docstring in `src/cognition/__init__.py` in the real repo, which # is effort spent on a tree nobody will ever run again. write_scopes_source: tuple[str, ...] |
| 8 | Bash | Inspect the two chat streams with kept edits and the user-facing reply text | == task%3Aa95dbcd9-8473-45d9-bd1e-8eb77e96457e.jsonl 15 task%3Aa95dbcd9-8473-45d9-bd1e-8eb77e96457e.jsonl "type":"task.started" "type":"task.step" "type":"task. |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out against the code as it is today, and the ledger evidence reproduces exactly. CHAT's tool tuple (profiles.py:59) includes apply_source_patch and replace_in_file but no git_commit; Execution's write scope for those tools is write_scopes_source (execution/config.py:120: "simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/", workspace), so a chat turn can legally write anywhere in the source tree. WORKTREE_KINDS at session.py:59 is {"patch","skill"} and :754 gates worktree opening on it, so chat edits the live checkout. session.py:94-96 puts any non-scratch write into session.uncommitted; :712-735 turns a "completed" outcome with uncommitted edits into blocked with UNCOMMITTED_REASON; :744-746 then asks _continues, which at :827-841 returns True for attempt 1 (< KEEP_EDITS_UNTIL_ATTEMPT=6 at :389) and a reason starting with UNCOMMITTED_REASON, with no check of session.kind; :846-859 _keep_uncommitted writes task.edits_kept. worker.py:403 builds the chat Session with task_id=session_id (a percept uuid) that Planning never created, so nothing re-offers it. Notably the code ALREADY special-cases chat for the sibling CONTINUATION_REASON path (session.py:940-946, "A chat has no next attempt") — but that path returns Outcome("completed"), which then falls straight into the :712 conversion, so even the chat-aware branch ends in an orphaned kept edit. This makes it a genuine bug (an inconsistency, not a design choice), not a historical one. The two uuid-keyed streams in the live ledger end with edits_kept + blocked and no later event, on 2026-09-11 and 2026-09-15 (after the worktree landing), and the user-facing text at worker.py:69 is exactly "(Not finished: finished with uncommitted changes: ...)". None of the known-findings list covers this; it is a concrete instance of the "unconnected wire" shape but materially new (a specific reachable path from the primary entry point that dirties the checkout simloader gates).

### evidence

- simorgh/orchestration/profiles.py:59 — CHAT tools: "apply_source_patch", "replace_in_file", "install_package", "run_script"; grep of the tuple shows no git_commit (comment at :41-43 says the write git tools 'stay in the task profiles')
- simorgh/execution/config.py:120 — write_scopes_source = ("simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/", SCRATCH_PREFIX); execution/tools.py:1685 and :2309 apply this scope to apply_source_patch/replace_in_file, so chat writes are not limited to workspace/
- simorgh/orchestration/session.py:59 WORKTREE_KINDS = frozenset({"patch", "skill"}); :754 `if not self._worktrees or session.kind not in WORKTREE_KINDS ...` — chat never gets a worktree
- simorgh/orchestration/session.py:94-96 — non-scratch file_write/file_create adds to session.uncommitted; :110 UNCOMMITTED_REASON = "finished with uncommitted changes"
- simorgh/orchestration/session.py:712-735 — `if session.uncommitted and outcome.kind == "completed"` -> Outcome("blocked", reason=UNCOMMITTED_REASON...), no kind check
- simorgh/orchestration/session.py:827-841 — _continues: `if session.attempt >= KEEP_EDITS_UNTIL_ATTEMPT or outcome.kind != "blocked": return False` then `return reason.startswith((CONTINUATION_REASON, VERIFICATION_REASON, UNCOMMITTED_REASON, LANDING_REASON))`; :389 KEEP_EDITS_UNTIL_ATTEMPT = 6; no session.kind check
- simorgh/orchestration/session.py:940-946 — the CONTINUATION path already says 'A chat has no next attempt' and returns Outcome("completed") from _wrap_up — which then hits :712 and is converted to blocked+kept anyway
- simorgh/orchestration/worker.py:403 — Session(task_id=session_id, kind="chat", ...); docstring :395-399 says the id is one 'Planning never created'
- simorgh/orchestration/worker.py:60-69 — _turn_text returns f"{summary}\n\n(Not finished: {outcome.reason})" for blocked outcomes
- Command `ls ~/.simorgh/ledger/streams | grep -E '^task%3A[0-9a-f]{8}-[0-9a-f]{4}-' | wc -l` -> 2328 uuid-keyed task streams (of 2431 task streams)
- Command `grep -l '"task.edits_kept"' task%3A*.jsonl` -> 8 streams; the two uuid-keyed ones are task:a95dbcd9-... (paths ["simorgh/voice/config.py"], reason 'finished with uncommitted changes: simorgh/voice/config.py', ts 1789178095 ≈ 2026-09-11) and task:f4a2a9d3-... (paths ["simorgh_skills/hot_stocks.py"], ts 1789535586 ≈ 2026-09-15); event sequence for both: task.started, task.step..., task.edits_kept, task.blocked — nothing after
- `git status --short simorgh/voice/config.py simorgh_skills/hot_stocks.py` is clean today, i.e. the creator manually resolved the dirty files (consistent with the memory note 'Live checkout, keep it committed')

**severity adjustment:** keep

