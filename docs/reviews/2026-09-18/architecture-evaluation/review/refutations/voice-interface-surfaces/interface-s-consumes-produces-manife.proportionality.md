# refute:proportionality:Interface's `consumes`/`produces` manife

*Workflow: review · Phase: Refute · Agent id: `aed2aabd6d672b396` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read manifest and count subscriptions/readers |  alone; `None` means "not an answer, handle normally.""" lowered = typed.lower() for option in options: if lowered == option.lower(): return option if {o.lower( |
| 2 | Bash | Check readers, publishes, subscribes, and module-map source | == raw readers of .consumes/.produces == tests/simorgh/integration/test_self_model_completeness.py:11:`.patterns.py`, `.critique.py`) but `Service.consumes` nev |
| 3 | Bash | Check publish forms, the scanning tool, test_contracts, and whether the gate uses the manifests | == TASK_CANCEL / UI_COMMAND_REPLY / BENCHMARK in interface == simorgh/interface/dispatch.py:141: """`TASK_CANCEL` is fire-and-forget, and Planning's own handler |
| 4 | Bash | Run the static drift scanner and check whether the bus enforces a per-topic publisher policy | Traceback (most recent call last): File "<string>", line 3, in <module> File "/opt/homebrew/anaconda3/lib/python3.12/json/__init__.py", line 293, in load return |
| 5 | Bash | Run scanner's declarations section and read the bus publish policy | == may_publish == def source_name(source: str) -> str: """`orchestration@w3` -> `orchestration` (the subsystem identity).""" return source.split("@", 1)[0] def  |
| 6 | Bash | Get scanner section 1b output and size of the enforced publish policy | == sections available == 75: """`TASK_CREATE` -> `task.create`, from contracts/topics.py.""" 90: """The topic a first argument names, if it names one statically |
| 7 | Bash | Run the scanner's declaration-drift section programmatically for all subsystems | Exit code 127 def main(argv: list[str]) -> int: want = {a for a in argv if not a.startswith("-")} as_json = "--json" in argv topics_scan = scan_topics() result  |
| 8 | Bash | Run the scanner's declaration-drift section for all subsystems | simorgh/benchmark/service.py: sub-not-decl=0 decl-not-sub=6 pub-not-decl=6 decl-not-pub=1 simorgh/curiosity/service.py: sub-not-decl=0 decl-not-sub=23 pub-not-d |
| 9 | Bash | Check which services the scanner silently skips and reconcile the interface manifest independently | simorgh/benchmark/service.py: {'consumes': 'Assign', 'produces': 'Assign'} simorgh/bus/service.py: {'consumes': 'AnnAssign', 'produces': 'AnnAssign'} simorgh/co |
| 10 | Bash | Check for transient subscriptions and whether the bus exposes live subscriptions | (eval):1: no matches found: simorgh/interface/tv*.py == does bus expose live subscriptions? == == kernel factory reads Service attrs? == simorgh/bus/service.py: |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** Interface's `consumes`/`produces` manifests are out of date (16 declared consumed vs 28 distinct subscribed topics, 13 of them undeclared; 12 declared produced vs at least 18 undeclared publish/request/reply topics), and no runtime code (Kernel, registry, selfcheck, bus enforcement) reads them. However "nothing in the codebase reads .consumes" is wrong: the creator already built exactly the checker the finding recommends -- tools/scan_half_wired.py section 1b compares declared consumes/produces with actual subscribe/publish calls -- but it only matches `ast.Assign`, so it silently skips the 11 of 18 services (interface, kernel, cognition, orchestration, planning, persona, memory, ledger, reflection, worldmodel, bus) that declare them as annotated `consumes: tuple[str, ...] = (...)`. The one reader is itself half-wired, which is the materially new part. The manifests are documentation, not the enforced contract: the bus's real publish/subscribe policy is `PUBLISH_ONLY_BY`/`SUBSCRIBE_ONLY_BY` in contracts/topics.py (9 and 2 entries) enforced by bus/enforcement.py:87, so the drift is a docs-truthfulness problem, not a safety one.

**reasoning:** Verified the counts directly: simorgh/interface/service.py:110-123 declares 16 consumed / 12 produced topics; `grep -c 'ctx.bus.subscribe('` on service.py gives 23 and the whole package gives 33 subscribe calls covering 28 distinct topics. My own AST/regex reconciliation shows 13 subscribed-but-undeclared topics (ACTION_RESULT, BENCHMARK_PROGRESS, DASH_STATE, TASK_BLOCKED/CLEARED/CREATED/FAILED, TV_SPEECH, TV_STATE, UI_DASH_KEY, VOICE_LISTENING/SPOKEN/TRANSCRIPT) and at least 18 published/requested-but-undeclared topics (TASK_CANCEL, UI_COMMAND_REPLY, TASK_CREATE, all VOICE_*_REQUEST, CURIOSITY_INTEREST_*, SYSTEM_STATUS_REQUEST, plus ACTION_PROPOSED, DASH_STATE, UI_HOOK_RECEIVED, SYSTEM_RESTART, SYSTEM_SCHEDULE_ADD/CANCEL from the plain publish grep). So the "decorative and out of date" part is confirmed.

The "nothing reads .consumes" evidence is partly refuted. tests/simorgh/bus/test_contracts.py:19 iterates `Service.produces` (base class only), test_service_and_factory.py:72-73 and test_tool_unavailable_is_announced.py:94 assert on them, and tools/scan_half_wired.py:255-297 (`scan_declarations`) is precisely a declared-vs-actual reconciler. But running it shows only 7 services (the `ast.Assign` ones: benchmark, curiosity, execution, guardian, learning, verification, voice) -- interface never appears because its declaration is an `ast.AnnAssign`. That means the project's own drift detector has a blind spot exactly where the drift is, which reinforces the finding's "designed slot, nobody writes it" framing rather than refuting it. The scanner is also not run in any gate (`grep -rn scan_half_wired` finds only its own docstring and one test docstring).

On the lens question (is it a problem at one-laptop/one-family scale?): the manifests are not the enforced boundary -- may_publish/may_subscribe use PUBLISH_ONLY_BY/SUBSCRIBE_ONLY_BY in contracts/topics.py:357-368, enforced at bus/enforcement.py:87 -- so a wrong manifest cannot cause an unsafe message. The harm is confined to documentation and to any future tool built on the manifests; docs/module-map.md already sidestepped them by grepping `topics.*`. That makes "medium" too high; this is a low-severity truthfulness issue.

The recommendation is disproportionate as written. Failing the boot gate on live-subscription mismatch is heavier than needed and slightly wrong-shaped: the Bus does not currently expose a subscriptions listing (no `subscriptions`/`_subscriptions` accessor in simorgh/bus/*.py), and request/reply helpers in dispatch.py publish topics that a runtime subscription check would not see. The cheap, proportionate fix is a two-line change: make `scan_declarations` also match `ast.AnnAssign`, then wrap it as a unit test that fails when any service's declared set differs from its static subscribe/publish set. Or, since the enforced policy lives in contracts/topics.py, delete the tuples and let the module map keep deriving edges from code.

### evidence

- simorgh/interface/service.py:110-123: `consumes: tuple[str, ...] = (` with 16 topics; `produces: tuple[str, ...] = (` with 12 topics (both ast.AnnAssign)
- `grep -c 'ctx.bus.subscribe(' simorgh/interface/service.py` -> 23; `cat simorgh/interface/*.py | grep -c 'bus.subscribe('` -> 33; distinct subscribed topics = 28
- AST/regex reconciliation of simorgh/interface/*.py: subscribed-not-declared = ['ACTION_RESULT','BENCHMARK_PROGRESS','DASH_STATE','TASK_BLOCKED','TASK_CLEARED','TASK_CREATED','TASK_FAILED','TV_SPEECH','TV_STATE','UI_DASH_KEY','VOICE_LISTENING','VOICE_SPOKEN','VOICE_TRANSCRIPT']; declared-not-subscribed = ['SYSTEM_HEALTH']
- Published/requested but not in `produces`: simorgh/interface/dispatch.py:161 `_publish(bus, topics.TASK_CANCEL`, dispatch.py:589 `_request(bus, topics.BENCHMARK_RUN_REQUEST`, service.py:785/789 `bus.reply(message, type=topics.UI_COMMAND_REPLY`; plain-publish grep also shows ACTION_PROPOSED, DASH_STATE, UI_HOOK_RECEIVED, SYSTEM_RESTART, SYSTEM_SCHEDULE_ADD, SYSTEM_SCHEDULE_CANCEL
- Readers DO exist: tests/simorgh/bus/test_contracts.py:19 `for t in Service.produces`; tests/simorgh/bus/test_service_and_factory.py:72-73; tests/simorgh/execution/test_tool_unavailable_is_announced.py:94; tools/scan_half_wired.py:255-297 `scan_declarations()` compares declared consumes/produces against actual subscribe()/publish() calls
- tools/scan_half_wired.py:266-268 only matches `isinstance(node, ast.Assign)`; running `scan_declarations(scan_topics())` lists only benchmark, curiosity, execution, guardian, learning, verification, voice -- interface and 10 other services (AnnAssign form) are silently skipped
- `grep -rn scan_half_wired` outside the tool itself -> only a docstring in tests/simorgh/execution/test_tool_unavailable_is_announced.py:10; the scanner is not part of any gate
- No runtime reader: `grep -n 'consumes\|produces' simorgh/kernel/*.py` shows only the kernel Service's own declaration (kernel/service.py:111,117) and unrelated configcheck comments; simorgh/kernel/selfcheck.py contains no reference
- Enforced contract is elsewhere: simorgh/contracts/topics.py:357-368 `may_subscribe`/`may_publish` use SUBSCRIBE_ONLY_BY (2 entries) / PUBLISH_ONLY_BY (9 entries); enforced at simorgh/bus/enforcement.py:87; `interface` is allowed publisher only for system.pause/reload/restart/resume/stop
- docs/module-map.md:9-12: edges drawn 'by walking every `topics.*` reference in `simorgh/` and classifying publish vs. subscribe' -- confirms the map bypasses the manifests
- No Bus accessor for live subscriptions: `grep -n 'def subscriptions\|self._subscriptions' simorgh/bus/*.py` -> nothing, so the recommended boot-gate comparison needs new Bus API

**severity adjustment:** lower

