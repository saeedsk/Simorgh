# refute:proportionality:The chat profile now binds 72 tools (58

*Workflow: review · Phase: Refute · Agent id: `a1f537d4a46af50f0` · Tool calls: 7*

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
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/orchestration/profiles.py | 1 """Per-kind Profiles (16 section 5). v1 kept its own per-agent step 2 ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); 3 these are t |
| 2 | Bash | Count tools per profile and dated comments | CHAT 72 max_steps 20 read_only False dups 0 VOICE_CHAT 58 max_steps 6 read_only False dups 0 PATCH 25 max_steps 20 read_only False dups 0 RESEARCH 31 max_steps  |
| 3 | Bash | Read what prior reviews already recorded about tool count |  - `execution/home/` + `execution/media/` → `execution/environment/` - **Note:** The in-process memory bus makes this less urgent than it appears — inter-subsys |
| 4 | Bash | Read audit's tool-overload recommendation and find where profile.tools is consumed | - The dataclass default in `config.py:103` is `irreversible_requires_human: bool = True`. - **Actual runtime default: human approval required.** The documentati |
| 5 | Bash | Read offered_tools and how the tool list is rendered into the prompt |  _REGISTERED.add(name) def forget_registered() -> None: _REGISTERED.clear() def offered_tools(profile_tools: tuple[str, ...]) -> tuple[str, ...]: """The profile |
| 6 | Bash | Measure rendered tool-block size and check whether native tool schemas are also sent | Exit code 1 CHAT lines 72 noted 72 chars 8349 ~tokens 2087 VOICE_CHAT lines 58 noted 58 chars 6789 ~tokens 1697 ---- session 1215-1240 if not text or reply.payl |
| 7 | Bash | Check how Cognition consumes tool names, existing routing hooks, and prompt size | ---- cognition tools use simorgh/cognition/service.py:41: return {"kind": "markers", "markers": tuple(payload.get("tools") or ())} simorgh/cognition/service.py: |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

You've hit your session limit · resets 11:10pm (America/Los_Angeles)