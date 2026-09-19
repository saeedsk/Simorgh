# refute:correctness:The chat profile now binds 72 tools (58

*Workflow: review · Phase: Refute · Agent id: `abbd8e4b412bfd5a4` · Tool calls: 8*

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
    "title": "The chat profile now binds 72 tools (58 by voice) and grows by dated anecdote",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "orchestration/profiles.py CHAT offers 72 tools on every typed turn and VOICE_CHAT 58 on every spoken one (up from the 34 recorded by earlier reviews), including file writes, package installs and script execution with a 20-step budget; every addition in the file is justified by a quoted creator complaint, so the surface only ever grows.",
    "evidence": [
      "python3 -c 'from simorgh.orchestration import profiles as p; ...' -> \"CHAT 72 max_steps 20 / VOICE_CHAT 58 max_steps 6 / PATCH 25 / RESEARCH 31 / PLAN 9 / SKILL 9; distinct tools offered across profiles 88\"",
      "builtin_tools(Config()) -> \"98 registered ... read_only: 40 effectful: 58\"",
      "simorgh/orchestration/profiles.py:12-104 -- CHAT's tuple is interleaved with 14 dated comments of the form \"(the creator, 2026-09-16)\" each adding tools; :55-66 adds apply_source_patch/install_package/run_script to chat",
      "simorgh/orchestration/profiles.py:150-170 VOICE_CHAT docstring: \"the same drift was found once before, for the Music tools, and patched for those alone\""
    ],
    "why_it_matters": "Tool lists are prompt weight and error surface on every turn; a 72-tool chat profile is a task profile with a shorter name. The growth mechanism (add whatever the last complaint lacked) has no counter-pressure, which is the same shape as the config and topic findings.",
    "recommendation": "Route by intent instead of by channel: a cheap classifier (or the model's first step) picks one domain bundle (house / cameras+tv / files+code / knowledge+mail / self), each 10-20 tools, with a `more_tools` escape. Keep CHAT itself read-only plus `start_task`; anything that writes becomes a task, which the worktree/gate path already handles well.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count profile tools and step budgets |  257 simorgh/orchestration/profiles.py ['BY_KIND', 'CHAT', 'PATCH', 'PLAN', 'RESEARCH', 'SKILL', 'VOICE_CHAT'] BY_KIND <class 'dict'> 'dict' object has no attri |
| 2 | Bash | Read profiles module with line numbers |  1 """Per-kind Profiles (16 section 5). v1 kept its own per-agent step 2 ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); 3 these are  |
| 3 | Bash | Count dated comments and CHAT tool count over git history | --- dated comments inside CHAT block (lines 12-87) 7: # retired v1 tree left readable for reference (observer, 2026-09-08). 28: # got "I have no such tool" (liv |
| 4 | Bash | Count CHAT tool tuple size across history | 0fd25dd CHAT= ? VOICE_CHAT= ? 6677679 CHAT= ? VOICE_CHAT= ? 87df4aa CHAT= ? VOICE_CHAT= ? d70fd21 CHAT= ? VOICE_CHAT= ? aa96332 CHAT= ? VOICE_CHAT= ? caf692a CH |
| 5 | Bash | Count tools across history, read audit doc, find profile consumers | 0fd25dd CHAT= ? VOICE_CHAT= ? 6677679 CHAT= ? VOICE_CHAT= ? 87df4aa CHAT= ? VOICE_CHAT= ? d70fd21 CHAT= ? VOICE_CHAT= ? aa96332 CHAT= ? VOICE_CHAT= ? caf692a CH |
| 6 | Bash | Inspect offered_tools filter, audit mentions, history counts, builtin count | --- audit mentions of write/install in chat 102:- **Action:** Add a `_sync_tools()` method to the Self Model that queries `ToolsFacet` and populates `capabiliti |
| 7 | Bash | Check history files, locate offered_tools and builtin_tools definitions | total 0 drwxr-xr-x 14 saeed wheel 448 Sep 18 19:30 . drwx------ 41 saeed wheel 1312 Sep 18 19:30 .. --- offered_tools simorgh/orchestration/tools.py:607:def off |
| 8 | Bash | History counts via git show, scaffold tool rendering, builtin_tools signature | 0fd25dd CHAT=absent VOICE_CHAT=absent 6677679 CHAT=absent VOICE_CHAT=absent 87df4aa CHAT=absent VOICE_CHAT=absent d70fd21 CHAT=absent VOICE_CHAT=absent aa96332  |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

You've hit your session limit · resets 11:10pm (America/Los_Angeles)