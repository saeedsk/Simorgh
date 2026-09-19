# refute:correctness:Interface's `consumes`/`produces` manife

*Workflow: review · Phase: Refute · Agent id: `ac9b9bc7177df3f21` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Interface's `consumes`/`produces` manifests are decorative and out of date",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "The Subsystem manifest lists 16 consumed and 12 produced topics while the package actually subscribes 33 times (23 in service.py alone) and publishes topics not in `produces` (ACTION_PROPOSED, DASH_STATE, UI_HOOK_RECEIVED, TASK_CANCEL, UI_COMMAND_REPLY); nothing in the codebase reads `.consumes`, so the contract the module map is supposed to be drawn from cannot be trusted.",
    "evidence": [
      "simorgh/interface/service.py:110-123: AST count `consumes 16`, `produces 12`",
      "`grep -c 'ctx.bus.subscribe(' simorgh/interface/service.py` -> 23; `cat simorgh/interface/*.py | grep -c 'bus.subscribe('` -> 33",
      "`grep -rn '\\.consumes\\b\\|\\.produces\\b' simorgh --include='*.py'` (excluding the tuple declarations) -> 0 readers; kernel/selfcheck.py, registry.py, kernel.py contain no reference",
      "docs/module-map.md header: 'the message edges by walking every `topics.*` reference in `simorgh/` and classifying publish vs. subscribe' (i.e. by grep, not from the manifests)"
    ],
    "why_it_matters": "A manifest that lies is worse than none: the architecture docs, the self-check and any future 'which subsystem may this topic reach' rule will be built on it. This is the same 'designed slot, nobody writes it' shape the project already knows, applied to its own architectural metadata.",
    "recommendation": "Either enforce or delete. Enforcing is cheap: in `kernel/selfcheck.py`, after boot, compare each service's live subscriptions (the Bus already knows them) with `consumes` and fail the boot gate on a mismatch; generate `produces` from the Bus's publish policy the same way. Then regenerate docs/module-map.md from the manifests instead of grep.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read Interface manifest and count subscriptions and manifest readers |  alone; `None` means "not an answer, handle normally.""" lowered = typed.lower() for option in options: if lowered == option.lower(): return option if {o.lower( |
| 2 | Bash | List published/subscribed topics in interface and search for manifest readers | == publish topics in interface == 2 topics.SYSTEM_RESUME 2 topics.SYSTEM_PAUSE 1 topics.UI_PROMPT_ANSWERED 1 topics.UI_HOOK_RECEIVED 1 topics.TASK_CANCEL 1 topi |
| 3 | Bash | Check manifest readers in kernel/tests, locate unlisted publishes, read module-map header | == getattr/consumes in kernel/tests/tools == simorgh/kernel/service.py:233: # subsystem's `start()` produces -- so it is built and its simorgh/kernel/configchec |
| 4 | Bash | Check for test-side readers of manifests, kernel/selfcheck refs, Subsystem protocol, and bus publish policy | == tests asserting on .consumes/.produces == tests/simorgh/integration/test_self_model_completeness.py:11:`.patterns.py`, `.critique.py`) but `Service.consumes` |
| 5 | Bash | Read the test that reads produces, the publish policy, and who enforces it | """Contract tests (docs/blueprint/05 section 5): every type the bus produces validates against the catalog; the bus's declared produces refer to real types; pub |
| 6 | Bash | Check whether prior reviews already reported the manifest drift | exit: done |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every checkable assertion holds against today's code, and the drift is actually larger than the finding states. The manifest at simorgh/interface/service.py:110-123 declares 16 consumed / 12 produced topics. The package subscribes to 28 distinct topics (33 subscribe calls; 23 in service.py), so 13 subscribed topics are missing from `consumes` (ACTION_RESULT, BENCHMARK_PROGRESS, DASH_STATE, TASK_BLOCKED, TASK_CLEARED, TASK_CREATED, TASK_FAILED, TV_SPEECH, TV_STATE, UI_DASH_KEY, VOICE_LISTENING, VOICE_SPOKEN, VOICE_TRANSCRIPT). It publishes 10 topics absent from `produces`: the five the finding names (ACTION_PROPOSED dispatch.py:1330, DASH_STATE httpapi.py:333, UI_HOOK_RECEIVED httpapi.py:496, TASK_CANCEL dispatch.py:161, UI_COMMAND_REPLY via bus.reply service.py:785/789) plus SYSTEM_RESTART (dispatch.py:213, service.py:677), SYSTEM_TICK_IDLE (dispatch.py:350), SYSTEM_SCHEDULE_ADD (dispatch.py:746), SYSTEM_SCHEDULE_CANCEL, CURIOSITY_INTEREST_ADD (dispatch.py:365). No runtime code reads `.consumes` or `.produces`: kernel/selfcheck.py, kernel/registry.py, kernel/kernel.py, bus/enforcement.py contain no reference; the Bus's real publish gate is the separate, hand-written `PUBLISH_ONLY_BY` table (contracts/topics.py:295-304, 9 topics) enforced at bus/enforcement.py:87, which never consults a manifest. docs/module-map.md:9-12 confirms the edges were produced by walking `topics.*` references, not from the manifests. Two small corrections: (1) "0 readers" is true of runtime only; three unit tests do read `.produces` (tests/simorgh/bus/test_contracts.py:19 checks the base bus Service's produces are catalog types; tests/simorgh/execution/test_tool_unavailable_is_announced.py:94 and tests/simorgh/bus/test_service_and_factory.py:72-73 assert individual entries), but none compares a manifest with live subscriptions/publishes, so they cannot catch this drift. (2) The recommendation's "generate produces from the Bus's publish policy" will not work as written: PUBLISH_ONLY_BY restricts only 9 topics, so it cannot enumerate what a subsystem produces; the live Bus subscription table can generate `consumes`, but `produces` would need a grep/AST pass or a publish-time recorder. The finding is not in the known list (no prior review mentions consumes/produces/manifest), though it is a specific instance of the already-known "unconnected wire" shape. Classification "right design undermined" is correct: a per-subsystem contract manifest is a sound idea at this scale; it is simply unenforced and stale.

### evidence

- simorgh/interface/service.py:110-123 — `consumes` tuple has 16 topics, `produces` tuple has 12 (read directly)
- `grep -c 'ctx.bus.subscribe(' simorgh/interface/service.py` -> 23; `cat simorgh/interface/*.py | grep -c 'bus.subscribe('` -> 33
- Distinct subscribed topics across simorgh/interface/*.py = 28; 13 absent from `consumes`: ACTION_RESULT, BENCHMARK_PROGRESS, DASH_STATE, TASK_BLOCKED, TASK_CLEARED, TASK_CREATED, TASK_FAILED, TV_SPEECH, TV_STATE, UI_DASH_KEY, VOICE_LISTENING, VOICE_SPOKEN, VOICE_TRANSCRIPT
- Published but not in `produces`: ACTION_PROPOSED (simorgh/interface/dispatch.py:1330), DASH_STATE (httpapi.py:333), UI_HOOK_RECEIVED (httpapi.py:496), TASK_CANCEL (dispatch.py:161), UI_COMMAND_REPLY via bus.reply (service.py:785,789), SYSTEM_RESTART (dispatch.py:213, service.py:677), SYSTEM_TICK_IDLE (dispatch.py:350), SYSTEM_SCHEDULE_ADD (dispatch.py:746), CURIOSITY_INTEREST_ADD (dispatch.py:365), SYSTEM_SCHEDULE_CANCEL
- `grep -rn 'consumes\|produces' simorgh/kernel/selfcheck.py simorgh/kernel/kernel.py simorgh/kernel/registry.py simorgh/kernel/service.py` -> only the Kernel's own tuple declarations at kernel/service.py:111,117; no reader
- Real publish gate is independent of manifests: simorgh/contracts/topics.py:295-304 `PUBLISH_ONLY_BY` (9 topics) and :361 `may_publish`, called only at simorgh/bus/enforcement.py:87
- Test-side readers exist but do not cross-check drift: tests/simorgh/bus/test_contracts.py:19 (`for t in Service.produces: assertIn(t, CATALOG)` on the base bus Service), tests/simorgh/execution/test_tool_unavailable_is_announced.py:94, tests/simorgh/bus/test_service_and_factory.py:72-73
- docs/module-map.md:9-12: 'the message edges by walking every `topics.*` reference in `simorgh/` and classifying publish vs. subscribe'
- `grep -n -i 'consumes\|produces\|manifest' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md` -> no matches (not previously reported)

**severity adjustment:** keep

**corrected claim:** The Interface Subsystem manifest (service.py:110-123) declares 16 consumed / 12 produced topics, but the package subscribes to 28 distinct topics (13 undeclared) and publishes 10 topics not in `produces` (ACTION_PROPOSED, DASH_STATE, UI_HOOK_RECEIVED, TASK_CANCEL, UI_COMMAND_REPLY, SYSTEM_RESTART, SYSTEM_TICK_IDLE, SYSTEM_SCHEDULE_ADD, SYSTEM_SCHEDULE_CANCEL, CURIOSITY_INTEREST_ADD). No runtime code reads `.consumes`/`.produces`; the Bus's actual publish gate is the separate 9-entry PUBLISH_ONLY_BY table in contracts/topics.py. Only three unit tests touch `.produces`, none against live subscriptions, so the drift is undetectable today and docs/module-map.md was drawn by grep instead. Enforcement fix: compare live Bus subscriptions with `consumes` in selfcheck; `produces` cannot be derived from PUBLISH_ONLY_BY (too sparse) and needs an AST walk or a publish-time recorder.

