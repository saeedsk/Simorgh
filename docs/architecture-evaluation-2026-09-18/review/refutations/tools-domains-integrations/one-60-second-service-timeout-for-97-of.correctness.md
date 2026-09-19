# refute:correctness:One 60-second service timeout for 97 of

*Workflow: review · Phase: Refute · Agent id: `a6bab399a713262d1` · Tool calls: 8*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/service.py (from line 70) | 70 `_store_rows` already writes every row to `results/<id>.json` and 71 caps that file at `results_max_rows`. Blobbing the SAME list again 72 here made the cap  |
| 2 | Bash | Locate timeout_s uses in execution and contracts | simorgh/execution/service.py:86: wins, then the tool's own declared `timeout_s`, then the default. simorgh/execution/service.py:88: Nothing in Guardian or Orche |
| 3 | Bash | Read the timeout handling, config, and slow tool code paths |  # restart), so resolve it from the `skill_dir/<name>.py` # convention `ApplySkillTool`/`SkillPipeline` both use, rather # than reporting a false "unknown tool" |
| 4 | Bash | Check worktree timeout declaration, Tool protocol, constraint setters, and known findings | class WorktreeLandTool: name = "worktree_land" description = ("Land this task's worktree on main: rebase, run the whole suite, fast-forward. " "Refuses a dirty  |
| 5 | Bash | Check constraint setters, known-findings overlap, tool counts, and inflight finish | ---CONSTRAINT-SETTERS simorgh/interface/service.py:1206: await self._ctx.clock.sleep(p.get("timeout_s", 0) or 0) # injected Clock, not raw asyncio.sleep -- Fake |
| 6 | Bash | Read _finish, guardian constraint construction, and locate the six named slow tools |  async def _finish(self, action_id: str) -> None: await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "finished", {"action_id": action_i |
| 7 | Bash | Check guardian constraints and the remaining slow tools' timeouts | ---CONTAINER 97: "timeout_s": {"type": "number"}, 132: if not await asyncio.to_thread(self._daemon_available): 144: timeout = min(float(args.get("timeout_s") or |
| 8 | Bash | Check container timeout default and whether Guardian emits constraints | 555: container_timeout_s: float = 300.0 simorgh/guardian/api.py:73: constraints: dict = field(default_factory=dict) |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core mechanism is verified against today's code: `timeout_for` (service.py:84-99) reads `constraints.timeout_s` first, then `getattr(tool, "timeout_s")`, then `default_timeout_s` (config.py:54 = 60.0). Nothing in guardian/ sets a constraint (the only `constraints` reference in simorgh/guardian is the empty-default field at api.py:73; no writer anywhere), so the tool attribute or the 60s default is the real bound. The run path (service.py:800-806) wraps `tool.run` in `asyncio.wait_for`, and on `asyncio.TimeoutError` calls `_finish` (which appends an inflight "finished" event, service.py:936-937) and publishes error="timeout". Tools that do their work via `asyncio.to_thread` (install_package at packages.py:304 with pip timeout=300 at :366; kb_sources at knowledge/tools.py:411 with max_files=100_000 at sources.py:80/119; run_container at container.py:159 with container_timeout_s=300 at config.py:555; sec_self at security/tools.py:135) cannot be cancelled by wait_for, so the thread keeps running after the ledger has already recorded "finished" and the model has been told "timeout". That is a genuine bug and is not in the known-findings list (zero hits for "timeout" in docs/architecture-audit-2026.md or docs/architecture-review-2026-09-18.html). Two details are wrong: (1) not only RunTestsTool declares `timeout_s`; WorktreeLandTool also does (worktree.py:373-376, wired at service.py:156 with test_timeout_s+60), so it is two tools not one, and the "97 of 98" figure is unsupported (I count 104 `class *Tool` declarations in simorgh/execution, 20 files using to_thread; the exact registered-tool count was not established). (2) Two tools (remote.py:188, render.py:213) do read `ctx.constraints["timeout_s"]` inside their own run, but since nothing sets it that is moot. The ring_setup and cam_recordings members of the "six slow tools" were not confirmed as to_thread-backed (ring.py uses an awaited WebRTC call, cameras.py had no to_thread hits in my grep), so the recommendation's list is partly speculative. Severity stays medium: the honesty violation is real (ledger says "finished" while the thread runs), the retry-doubles-a-pip-install consequence is plausible but not demonstrated.

### evidence

- simorgh/execution/service.py:84-99 timeout_for: constraints.timeout_s -> getattr(tool,'timeout_s') -> default_s; docstring itself says 'Nothing in Guardian or Orchestration sets constraints.timeout_s (checked 2026-09-10)'
- simorgh/execution/service.py:793 `timeout = timeout_for(tool, approved.get("constraints") or {}, self._config.default_timeout_s)`; :800-806 wait_for + except asyncio.TimeoutError -> _finish(action_id) then publish error="timeout"
- simorgh/execution/service.py:936-937 `_finish` appends inflight event "finished" -- so on timeout the ledger records finished while a to_thread worker is still running
- simorgh/execution/config.py:54 `default_timeout_s: float = 60.0`; :296 `package_install_timeout_s: float = 300.0`; :555 `container_timeout_s: float = 300.0`
- `grep -rn "def timeout_s" simorgh/` -> exactly 2 hits: simorgh/execution/tools.py:1230 (RunTestsTool, returns test_timeout_s+30) and simorgh/execution/worktree.py:373 (WorktreeLandTool) -- the claim's 'every tool except run_tests' is off by one
- `grep -rn constraints simorgh/guardian/` -> only simorgh/guardian/api.py:73 `constraints: dict = field(default_factory=dict)`; no writer of timeout_s anywhere in guardian/ or orchestration/
- simorgh/execution/packages.py:304 `completed = await asyncio.to_thread(self._install, manager, spec)`; :366 subprocess `timeout=self._config.package_install_timeout_s`
- simorgh/execution/knowledge/tools.py:407-411 comment 'Scanning is blocking file and sqlite work' + `report = await asyncio.to_thread(_work)`; knowledge/sources.py:80,119 `max_files: int = 100_000`
- simorgh/execution/container.py:144-161 timeout = min(args.timeout_s, container_timeout_s=300) then `await asyncio.to_thread(...)`; simorgh/execution/security/tools.py:135 `await asyncio.to_thread(self._collect, ...)`
- simorgh/contracts/protocols.py:195-202 `class Tool(Protocol)` has name/description/read_only/reversibility/args_schema/run -- no timeout_s member
- `grep -c -i timeout docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html` -> 0 and 0: not in the known-findings list
- simorgh/execution/remote.py:188 and render.py:213 read ctx.constraints.get("timeout_s", ...) themselves -- the constraint slot exists in the schema (contracts/messages/action.py:31) but has no writer: the project's 'unconnected wire' shape

**severity adjustment:** keep

**corrected claim:** `timeout_for` (execution/service.py:84-99) bounds every tool at `default_timeout_s = 60` unless the tool declares its own `timeout_s`; only two do (RunTestsTool, tools.py:1230; WorktreeLandTool, worktree.py:373), and the `constraints.timeout_s` slot in the action.approved schema has no writer in Guardian or Orchestration. At least four tools whose real work runs in `asyncio.to_thread` with a longer internal budget (install_package 300s, run_container 300s, kb_sources up to 100k files, sec_self) are reported as error="timeout" at 60s and the ledger's inflight stream records "finished" (service.py:803, 936) while the thread continues, uncancellable and unrecorded. The Tool protocol (contracts/protocols.py:195) has no timeout member, so each slow tool must rediscover this by hand.

