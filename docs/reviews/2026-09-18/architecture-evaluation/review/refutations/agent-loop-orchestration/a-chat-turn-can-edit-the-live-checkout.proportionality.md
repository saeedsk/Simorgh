# refute:proportionality:A chat turn can edit the live checkout,

*Workflow: review · Phase: Refute · Agent id: `a212fb48cb3cec279` · Tool calls: 9*

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
| 1 | Bash | Read profile tool list and worktree kinds |  "sim_command", # "did you read your git log?" -- Sim: "I can't run git from here" # (the creator, 2026-09-16). Read-only: the three write tools # stay in the t |
| 2 | Bash | Read uncommitted-outcome and _continues/_keep_uncommitted code |  # "says it changed a file, and no edit was applied". complete_log=session.attempt <= 1 and not session.carried, ) if claims: step = Step(session.next_step_no() |
| 3 | Bash | Find where uncommitted is populated and how chat sessions are constructed | 96: session.uncommitted.add(path) 105: session.uncommitted.discard(path) ---- 13:399- `if session.kind == "chat": publish turn.completed` branch. 16:402- sessio |
| 4 | Bash | Read uncommitted tracking, chat session construction, and where edits_kept is consumed |  kind, _, path = str(effect).partition(":") if not path: continue if kind in ("file_write", "file_create"): session.wrote.add(path) # Scratch is written, never  |
| 5 | Bash | Check write scopes, edits_kept consumers, ledger counts, and current state of the kept files | 85: # Readable, never writable by a patch: `write_scopes_source` does 90: # off; writable too (`write_scopes_source` below) -- the one 99: # question that `writ |
| 6 | Bash | Check chat special-casing, write scopes, event dates, fate of kept files, and resume reader | 890: if (session.profile.scaffold != "chat" and session.messages and not session.budget.is_last_step 913: and session.profile.scaffold != "chat" and session.mes |
| 7 | Bash | Check what became of the two orphaned chat edits and count chat task streams | c13d6d6 2026-09-12 06:54:50 -0700 Saeed Sim's voice can come out of the TV, the TV page stays awake, and a spoken "cast something" gets cast 67da1ac 2026-09-12  |
| 8 | Bash | Count chat task streams and check whether the orphaned voice config flip got swept into a creator commit | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl 0 ---- 2026-09-11 co |
| 9 | Bash | Count chat vs planned task streams and inspect the creator commit that followed the orphaned config edit | 2328 103 ---- da8d9bc config diff 40:--- a/simorgh/voice/config.py 41:+++ b/simorgh/voice/config.py 46:- enabled: bool = False 47:+ # Listen on boot. "auto" (th |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every link in the chain checks out in the current code, and the ledger shows it happened twice on real chat turns, both times cleaned up by the human, not the system. (1) CHAT profile grants apply_source_patch/replace_in_file/install_package/run_script and no git_commit; the comment right above it says the write tools "stay in the task profiles where a commit belongs" -- a deliberate decision that was later undermined when chat was given write tools on 2026-09-09 without revisiting the uncommitted-edit path. (2) WORKTREE_KINDS is {"patch","skill"}, so a chat session edits the live checkout, and write_scopes_source covers simorgh/, simorgh_skills/, tests/, tools/, docs/ (not just workspace/). (3) session.py converts completed+uncommitted into blocked with UNCOMMITTED_REASON; _continues has no kind check and returns True for attempt 1 (< KEEP_EDITS_UNTIL_ATTEMPT=6) when reason starts with UNCOMMITTED_REASON; _keep_uncommitted then appends task.edits_kept. (4) run_percept_chat builds an ephemeral Session keyed by the percept's session_id; the only consumer of EDITS_KEPT is resume.py, which is driven by Planning re-offering a task -- and Planning never created this id (the docstring says so explicitly), so nothing re-claims it. (5) Ledger: 2328 uuid-keyed chat task streams vs 103 planned ones; exactly two chat streams carry task.edits_kept: a95dbcd9 (2026-09-11 18:55, simorgh/voice/config.py, reply "Done -- the flag is flipped") and f4a2a9d3 (2026-09-15 22:13, simorgh_skills/hot_stocks.py, reply "Done -- the hot_stocks skill is built"). The voice/config.py file was next touched by the creator's own commit da8d9bc at 19:52 the same evening (enabled: False -> "auto"), i.e. the dirty edit sat in the gated live tree for an hour and was resolved by hand; hot_stocks.py appears in no commit on any ref and no longer exists on disk, so it was deleted by hand. On the skeptic lens: frequency is low (2 of 2328 chat turns, ~0.1%), so "high" is arguable, but each occurrence dirties the exact checkout simloader gates and rolls back, the operator's memory note records the pain, and the fix is one line -- the recommendation is not disproportionate. One caveat on the recommended fix: `return False` for chat triggers _discard_uncommitted, which would have deleted hot_stocks.py, a skill the user asked for and was told was done; refusing/redirecting source writes from chat (or granting chat git_commit for simorgh_skills/) is the better of the two options offered. Classification: (b) right design (chat cannot commit; code changes go through worktrees) undermined by a later profile change, plus (c) a genuine bug in _continues.

### evidence

- simorgh/orchestration/profiles.py:41-44 comment: 'the three write tools stay in the task profiles where a commit belongs'; :59 CHAT tools tuple = 'apply_source_patch', 'replace_in_file', 'install_package', 'run_script' -- no git_commit anywhere in the tuple (lines 40-70)
- simorgh/orchestration/session.py:63 `WORKTREE_KINDS = frozenset({"patch", "skill"})`
- simorgh/execution/config.py:120-126 write_scopes_source = ('simorgh/', 'simorgh_skills/', 'tests/', 'tools/', 'docs/', SCRATCH_PREFIX) -- chat's apply_source_patch (execution/tools.py:1685) writes with these scopes
- simorgh/orchestration/session.py:83-96 file_write/file_create adds path to session.uncommitted unless is_scratch(path)
- simorgh/orchestration/session.py:712-735 `if session.uncommitted and outcome.kind == "completed"` -> Outcome('blocked', reason=UNCOMMITTED_REASON...)
- simorgh/orchestration/session.py:827-841 _continues: `if session.attempt >= KEEP_EDITS_UNTIL_ATTEMPT or outcome.kind != "blocked": return False` then `return reason.startswith((CONTINUATION_REASON, VERIFICATION_REASON, UNCOMMITTED_REASON, LANDING_REASON))` -- no kind/profile check; :389 KEEP_EDITS_UNTIL_ATTEMPT = 6
- simorgh/orchestration/session.py:843-856 _keep_uncommitted appends EDITS_KEPT with task_id and paths
- simorgh/orchestration/worker.py:387-410 run_percept_chat: Session(task_id=session_id, kind='chat', ...); docstring: 'a plain conversational percept has no Planning task behind it ... an id Planning never created'
- grep -rn EDITS_KEPT simorgh --include='*.py': only consumer outside session.py is simorgh/orchestration/resume.py:63, which is read on a Planning re-offer
- simorgh/orchestration/worker.py:69 user-facing reply suffix `(Not finished: {outcome.reason})`
- ls ~/.simorgh/ledger/streams | grep -cE '^task%3A[0-9a-f]{8}-[0-9a-f]{4}-' -> 2328 (uuid-keyed chat streams); 12-hex planned task streams -> 103
- Ledger scan over 118215 stream files: task.edits_kept on chat (uuid) streams = 2: task:a95dbcd9-... ts 1789178120 (2026-09-11 18:55:20) paths ['simorgh/voice/config.py'], result_summary 'Done -- the flag is flipped'; task:f4a2a9d3-... ts 1789535639 (2026-09-15 22:13:59) created+paths ['simorgh_skills/hot_stocks.py'], result_summary 'Done -- the hot_stocks skill is built ... and live-tested'. Matching task.blocked 'finished with uncommitted changes' on the same two streams.
- git log -- simorgh/voice/config.py: next commit after the 18:55 chat edit is da8d9bc 2026-09-11 19:52:32 by Saeed, changing `enabled: bool = False` -> `enabled: bool | str = "auto"` -- the orphaned flip was resolved by the human's own commit ~1h later
- git log --all -- simorgh_skills/hot_stocks.py -> empty; ls simorgh_skills/hot_stocks.py -> No such file or directory: never committed, removed by hand
- git status at session start: simorgh/voice/config.py clean, no simorgh_skills/hot_stocks.py present

**severity adjustment:** keep

**corrected claim:** Mechanism as stated is correct in current code and occurred twice in ~2328 chat turns (2026-09-11 simorgh/voice/config.py; 2026-09-15 simorgh_skills/hot_stocks.py), each left dirty in the live checkout until the creator cleaned it up by hand. Note the recommended `if session.kind == "chat": return False` would discard the edit, which for hot_stocks.py would delete a skill the user asked for and was told was done; refusing/redirecting source writes from chat into a patch worktree via start_task, or granting chat git_commit for simorgh_skills/, fits better than silent discard.

