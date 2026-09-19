# refute:proportionality:One 60-second service timeout for 97 of

*Workflow: review · Phase: Refute · Agent id: `aec058c61836fbba2` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "One 60-second service timeout for 97 of 98 tools, while the cancelled work keeps running in a thread",
    "kind": "bug",
    "severity": "medium",
    "claim": "`timeout_for` falls back to `default_timeout_s = 60` for every tool except run_tests, so install_package (own subprocess budget 300s) and kb_sources scan (up to 100,000 files) are reported as 'timeout' at 60s while their `asyncio.to_thread` work continues invisibly, inviting a retry that runs a second pip install or a second sqlite writer.",
    "evidence": [
      "simorgh/execution/service.py:84-99 `timeout_for`: constraints.timeout_s ('Nothing in Guardian or Orchestration sets `constraints.timeout_s` (checked 2026-09-10)'), then `getattr(tool, \"timeout_s\", None)`, else default; `grep -rn \"self.timeout_s\\|\\.timeout_s = \" simorgh/execution` -> none; the only declaration is the RunTestsTool property at tools.py:1229-1240, whose docstring records this exact bug fixed for itself only",
      "simorgh/execution/config.py:54 `default_timeout_s: float = 60.0` vs :296 `package_install_timeout_s: float = 300.0`",
      "simorgh/execution/packages.py:304 `completed = await asyncio.to_thread(self._install, manager, spec)`; :358-368 `_install` runs pip/npm with timeout=300",
      "simorgh/execution/knowledge/tools.py:411 `report = await asyncio.to_thread(_work)` where `_work` calls scan_source with `max_files: int = 100_000` (knowledge/sources.py:79-80) and no time bound",
      "service.py:801-806: on `asyncio.TimeoutError` the service publishes error=\"timeout\" and returns; a thread started by to_thread cannot be cancelled and no event records that it is still running"
    ],
    "why_it_matters": "A tool that says 'timeout' while still installing a package is the 'succeeds while saying nothing true' failure the project's own honesty rules name, and the model's natural next move (retry) doubles the effect. The protocol has no place to declare cost, so every new slow tool repeats this until someone adds a property by hand.",
    "recommendation": "Make `timeout_s` part of the Tool protocol (contracts/protocols.py) with a class default per family (reads 15s, network 30s, subprocess/scan 330s), set it in the six slow tools (install_package, kb_sources, run_container, sec_self, cam_recordings, ring_setup), and on cancellation of a to_thread-backed tool publish error=\"timeout; still running in the background\" plus a `finished` inflight event when the thread ends. Two hours; add a test that a tool with timeout_s=0.1 wrapping a 1s thread reports the background note.",
    "confidence": 0.75
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read timeout_for and timeout config declarations |  `_store_rows` already writes every row to `results/<id>.json` and caps that file at `results_max_rows`. Blobbing the SAME list again here made the cap decorati |
| 2 | Bash | Find timeout_s declarations across tools and the timeout handling path in service | (eval):1: no matches found: --include=*.py ---- # restart), so resolve it from the `skill_dir/<name>.py` # convention `ApplySkillTool`/`SkillPipeline` both use, |
| 3 | Bash | Check timeout property declarations, constraint setters, package install and kb scan code paths, and config file | == timeout_s properties on tool classes == simorgh/execution/tools.py:1230: def timeout_s(self) -> float: simorgh/execution/worktree.py:373: def timeout_s(self) |
| 4 | Bash | Check the second timeout_s property, config wiring of the toml timeout, other slow tools, and existing tests | == worktree timeout_s == reversibility = "irreversible" args_schema = {"type": "object", "properties": {"task_id": {"type": "string"}}} def __init__(self, manag |
| 5 | Bash | Check internal budgets of the other named slow tools and whether Guardian populates constraints | == container == 132: if not await asyncio.to_thread(self._daemon_available): 144: timeout = min(float(args.get("timeout_s") or self._config.container_timeout_s) |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The code confirms the mechanism. `timeout_for` (simorgh/execution/service.py:84-99) takes `constraints.timeout_s`, then a tool's own `timeout_s` attribute, then `default_timeout_s = 60.0` (config.py:54). Nothing in Guardian populates `constraints` (grep "constraints" in simorgh/guardian/service.py returns no hits; the one guardian `timeout_s` at :627 is a UI prompt field, not an action constraint), and ~/.simorgh/simorgh.toml has no execution timeout override (its only `timeout_seconds` is under [cognition.providers.ollama]). So the 60s default is the live bound. Two corrections to the claim: (1) two tools, not one, declare `timeout_s` — RunTestsTool (tools.py:1230-1240) and the worktree land tool (worktree.py:373-376, whose docstring says "Same shape as RunTestsTool"), so it is "all but two" of ~100 tools; (2) the claim says "no event records that it is still running", but the reality is slightly worse: on `asyncio.TimeoutError` the service calls `_finish(action_id)` (service.py:803) which appends an inflight "finished" event (service.py:936-937) before publishing error="timeout" — the ledger affirmatively says finished while the `to_thread` worker continues. The slow-tool examples hold: install_package runs pip/npm via `asyncio.to_thread(self._install, ...)` with `package_install_timeout_s=300` (packages.py:304, :358-368); kb_sources scan runs `asyncio.to_thread(_work)` over `walk_source(max_files=100_000)` with no time bound (knowledge/tools.py:411, sources.py:79-80); run_container runs docker via to_thread with a 300s `container_timeout_s` (container.py:144-161) and its `_kill` at :166 only fires on the inner subprocess timeout, so a 60s outer cancel leaves the container running to 300s. sec_self is also to_thread (security/tools.py:135). Scale lens: at one-laptop scale a duplicated pip install is mostly harmless, but a second concurrent sqlite writer over the knowledge index or a second docker container are real, and the false "finished" ledger event breaks the project's own honesty rule. The fix is proportionate: the hook already exists and two tools have already hand-patched it, so a protocol-level `timeout_s` default plus an honest "still running" note is a small change, not a rewrite. Classification: (b) a right design (per-tool timeout slot) whose implementation is unfilled, plus a genuine bug (false finished event). Severity medium is right.

**corrected claim:** `timeout_for` falls back to `default_timeout_s = 60` for every tool except two (RunTestsTool at tools.py:1230 and the worktree land tool at worktree.py:373) because nothing sets `constraints.timeout_s` and no other tool declares `timeout_s`. Tools whose to_thread work has a larger internal budget (install_package 300s, run_container 300s, kb_sources scan unbounded, sec_self) are reported as 'timeout' at 60s, and the service writes an inflight "finished" event (service.py:803, :936-937) while the thread is in fact still running, so the ledger and the model are both told something false, inviting a retry that duplicates the work.

### evidence

- simorgh/execution/service.py:84-99 timeout_for: constraints.timeout_s -> getattr(tool,'timeout_s') -> default; docstring says nothing sets constraints.timeout_s (checked 2026-09-10)
- simorgh/execution/service.py:793 timeout = timeout_for(tool, approved.get('constraints') or {}, self._config.default_timeout_s); :801 asyncio.wait_for(tool.run(...), timeout=timeout); :802-806 on TimeoutError -> await self._finish(action_id) then publish error='timeout'
- simorgh/execution/service.py:936-937 _finish appends INFLIGHT 'finished' event -- written on timeout while the to_thread worker continues
- simorgh/execution/config.py:54 default_timeout_s: float = 60.0; :296 package_install_timeout_s = 300.0; :555 container_timeout_s = 300.0
- grep -rn 'def timeout_s' simorgh/ -> only tools.py:1230 (RunTestsTool) and worktree.py:373 (land tool: 'Same shape as RunTestsTool'); grep 'constraints' simorgh/guardian/service.py -> no hits
- ~/.simorgh/simorgh.toml: only timeout key is [cognition.providers.ollama] timeout_seconds = 60.0; no execution default_timeout_s override
- simorgh/execution/packages.py:304 completed = await asyncio.to_thread(self._install, manager, spec); :358-368 runs pip/npm with timeout=package_install_timeout_s (300)
- simorgh/execution/knowledge/tools.py:411 report = await asyncio.to_thread(_work); knowledge/sources.py:79-80 walk_source(max_files=100_000), no time bound
- simorgh/execution/container.py:144-161 docker run via asyncio.to_thread with timeout=min(args.timeout_s, container_timeout_s=300); :166 _kill only on inner TimeoutExpired, so outer 60s cancel leaves the container running
- simorgh/execution/security/tools.py:135 findings = await asyncio.to_thread(self._collect, ...)
- python3 count of 'name = "' declarations under simorgh/execution: 103 (roughly 100 tools, 2 declare timeout_s)

**severity adjustment:** keep

