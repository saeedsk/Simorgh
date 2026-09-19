# refute:correctness:Execution and the camera watcher run too

*Workflow: review · Phase: Refute · Agent id: `a031bef9556aee29e` · Tool calls: 14*

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
    "title": "Execution and the camera watcher run tools directly, outside Guardian and the action ledger",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "Seven call sites invoke `tool.run()` with synthetic action ids and no proposal, approval, token or `action:*` stream, so casting to the TV at boot, starting ffmpeg transcodes, polling Ring's cloud, taking snapshots and calling a vision model on every motion event are effects Guardian never sees and the ledger never records as actions.",
    "evidence": [
      "simorgh/execution/service.py:484 `result = await tool.run({\"on\": True}, ctx=ctx)` (ring_watch, action_id=\"ring-watch-boot\"); :517 (cam_watch, \"cam-watch-boot\"); :543 (cast_show, \"tv-show-boot\"); :561 (tv_charts, f\"charts-{message.id}\" on ui.dash.state)",
      "simorgh/execution/vision.py:235, :475, :515 `await tool.run(...)` for cam_snapshot/ring_snapshot/camera_describe on world.camera.event",
      "Ledger measured over 26,737 action streams: camera_describe proposed 0 times, cam_watch 1, ring_watch 5, cast_show 114 - yet the watch and describe paths run on every boot and event (vision.py module docstring: 'Sim takes a couple of stills ... asks a model that can actually see them')",
      "Design statement being undermined: simorgh/execution/home/cameras.py docstring 'Every call is a tool call, so Guardian sees it -- the siren above all'; mcp.py docstring 'Guardian sees every call'"
    ],
    "why_it_matters": "The two invariants the whole architecture is sold on - one approver, one append-only record of effects - are false for the subsystem that carries 99% of real use (cameras/TV). A vision call per motion event is a paid-model spend with no BudgetRule and no action stream; a boot-time cast to the family TV is exactly the kind of unattended effect the posture/ModeRule exist for. Anyone auditing the ledger will conclude the cameras were barely used.",
    "recommendation": "Add one helper in execution/service.py, `_propose_internal(tool, args, rationale)`, that publishes action.proposed with proposed_by=\"execution:boot\"/\"execution:vision\" and awaits the result (interface/dispatch.py `_run_tool` already implements this pattern; reuse it via a contracts helper). Route the seven sites through it. If a synchronous boot path cannot wait on Guardian, at least append a `started` event with the tool name to `execution:inflight` so the record is complete. Two hours.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Find direct tool.run call sites in execution package | simorgh/execution/vision.py:235: result = await tool.run({"camera": camera}, ctx=ctx) simorgh/execution/vision.py:475: result = await tool.run({}, ctx=ctx) simo |
| 2 | Bash | Read the boot-time tool call sites in execution service |  await client.close() return self._mcp_clients.append(client) for spec in specs: tool = McpToolProxy(client, server, spec) self._registry[tool.name] = tool awai |
| 3 | Bash | Read the approved-action execution path |  return max(items, key=lambda i: i.get("ts", 0.0))["content"] async def _replay_inflight(self) -> None: events = await self._ctx.ledger.read(INFLIGHT_STREAM) st |
| 4 | Bash | Read vision.py docstring and the three tool.run sites | Exit code 1 """What the cameras saw. A camera event says "channel 3, person". That is a fact, and it is not what happened: a person at the side gate at two in t |
| 5 | Bash | Read the three vision.py tool.run sites |  def __init__(self, config, **kwargs) -> None: self._config = config self._kwargs = {k: v for k, v in kwargs.items() if k in ("env", "secrets", "clock", "settin |
| 6 | Bash | Inspect describe_stills, the watcher subscription, and tool reversibility flags | 151:async def describe_stills(paths: list[str], *, camera: str, bus, kinds=(), timeout: float = 60.0, 152- template: str = "", baseline: str = "") -> tuple[str, |
| 7 | Bash | Check tool flags, watcher wiring, cited docstrings, in-tool ledger appends, dispatch helper | == simorgh/execution/home/ring.py:563 1: name = "ring_snapshot" == simorgh/execution/home/ring.py:747 1: name = "ring_watch" == simorgh/execution/home/cameras.p |
| 8 | Bash | Get tool reversibility flags, watcher wiring, docstrings, and check prior reviews for this finding | simorgh/execution/home/ring.py 563 ring_snapshot read_only= None rev= None simorgh/execution/home/ring.py 747 ring_watch read_only= None rev= None simorgh/execu |
| 9 | Bash | Import tool classes for flags, inspect ledger layout, scan prior reviews and Guardian rules | ring_snapshot read_only= False reversibility= reversible ring_watch read_only= False reversibility= reversible cam_snapshot read_only= False reversibility= reve |
| 10 | Bash | Inspect ledger stream directory and Guardian's mode/pause rules | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl 118215 0 /Users/saee |
| 11 | Bash | Count action streams in the ledger and proposals per camera/TV tool | action streams: 26737 camera_describe 0 cam_watch 1 ring_watch 5 cast_show 114 tv_charts 2 cam_snapshot 5 ring_snapshot 9 cam_list 15 ring_list 5 top: [('ring_l |
| 12 | Bash | Check non-action ledger streams, bus journaling, dispatch proposal helper, config toggles, cognition budget handling | 88356 trace: 2431 task: 350 verify: 181 reflect:drift: 125 reflect:critique: 1 voice:turns.jsonl 1 system.jsonl 1 schedule.jsonl 1 reflect:patterns.jsonl 1 refl |
| 13 | Bash | Check config values, sample a trace stream, find trace writers and the dispatch helper | ##### toml /Users/saeed/.simorgh/secrets.toml /Users/saeed/.simorgh/simorgh.toml /Users/saeed/.simorgh/simorgh.toml:20:cast_device = "Family Room TV" ##### trac |
| 14 | Bash | Check whether boot TV show is enabled anywhere, who writes traces, and what traces record | ##### sim.sh / env for tv_show simorgh/execution/config.py:466: tv_show_on_start: bool = False simorgh/execution/config.py:60: # `SIMORGH_EXECUTION_REPO_ROOT` e |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core mechanism is confirmed in today's code: seven `tool.run()` call sites in the Execution package build a synthetic ToolContext (action_id "ring-watch-boot", "cam-watch-boot", "tv-show-boot", f"charts-{message.id}", f"camera-vision-{ts}-{i}", f"camera-baseline-{ts}") and run the tool with no action.proposed, no Guardian decision, no token verification, no `action:<id>` stream, no `execution:inflight` started/finished, no tool.invoked, and no `_paused` check -- everything the approved path in `_on_approved` (service.py:758-855) does. The ledger numbers the reader quoted are exact (26,737 action streams; camera_describe 0, cam_watch 1, ring_watch 5, cast_show 114), and no trace stream mentions cam_snapshot/ring_snapshot/cognition.think either, so the record really is absent. All six tools are `read_only=False, reversibility="reversible"`, so Guardian's ModeRule (observe/locked/plan) and PausedRule would gate them if proposed; the bypass skips those gates. This is not in the known-findings list (the audit md praises "Every effect is published as action.proposed"). Four corrections, though, that lower the severity: (1) vision.py:235 is inside `CameraDescribeTool.run`, a composite tool invoking snapshot sub-tools with the ctx of its own already-approved action -- nesting, not a bypass; and the motion-event path never calls camera_describe at all, it calls `describe_stills()` directly (vision.py:151-183), so "camera_describe proposed 0 times" is explained by nobody asking, not by evasion. (2) The boot cast to the TV is gated by `tv_show_on_start`, which defaults False (execution/config.py:466) and is not set in ~/.simorgh/simorgh.toml, so it does not run in the creator's deployment today; ring_watch/cam_watch autostart (default True) do. (3) The per-event vision call is not unbudgeted: the cognition.think request carries `budget: {max_tokens: 200, max_cost_usd: 0.02}` (vision.py:171) and goes through Cognition's rolling budgets; Guardian's BudgetRule is per-action and no cognition.think from anywhere is an action, so this is the same footing as a chat turn. (4) "Anyone auditing the ledger will conclude the cameras were barely used" is false: ring_live alone has 22,849 proposals and cam_stream 721, all through Guardian -- the user-facing camera path IS recorded; what is missing is the autonomous watcher's snapshots and the boot-time watch starts. Classification stands as right-design-undermined (a genuine gap in the "one approver, one record" invariant for autonomous effects), but at medium rather than high.

**corrected claim:** Execution runs six tool invocations outside Guardian and the action ledger: at boot, `_autostart_ring_watch` (service.py:484) and `_autostart_cam_watch` (:517) start the Ring cloud poll and the NVR watch; `_autostart_tv_show` (:543) would cast the dashboard to the TV but is off by default (`tv_show_on_start=False`, config.py:466, unset in simorgh.toml); `_on_dash_state` (:561) runs tv_charts on any ui.dash.state charts view; and CameraVision runs cam_list/ring_list (vision.py:475) and cam_snapshot/ring_snapshot (:515) on every world.camera.event. Each builds a synthetic ToolContext and calls `tool.run()` directly, so no action.proposed, Guardian decision, HMAC verification, `action:*` stream, inflight record, tool.invoked or paused-check occurs -- unlike `_on_approved` (service.py:758-855). All six tools are reversible/non-read-only, so ModeRule/PausedRule would apply if proposed. The vision model call that follows is budgeted per call (max_cost_usd 0.02, vision.py:171) via Cognition, not Guardian. vision.py:235 is a composite tool's sub-call under an already-approved action and is not a bypass. Interactive camera use (ring_live 22,849 proposals, cam_stream 721) does go through Guardian; only the autonomous watcher/boot effects are unrecorded.

### evidence

- simorgh/execution/service.py:481-484, :514-517, :540-543, :558-561 -- `ctx = ToolContext(action_id="ring-watch-boot"|"cam-watch-boot"|"tv-show-boot"|f"charts-{message.id}", ...)` then `result = await tool.run(..., ctx=ctx)`; only `self._ctx.logger.info(...)` afterwards, no ledger.append, no bus publish of action.*
- simorgh/execution/service.py:758-855 (`_on_approved`) -- the contrasting approved path: `_fetch_proposal`, `self._verifier.verify`, `ledger.append(f"action:{action_id}", 'verified')`, `if self._paused: ...`, `ledger.append(INFLIGHT_STREAM, 'started')`, `_finish`, `_publish_result`, `TOOL_INVOKED`; none of it reached by the boot/dash sites
- simorgh/execution/vision.py:470-475 (cam_list/ring_list, action_id f"camera-baseline-{ts}") and :507-515 (cam_snapshot/ring_snapshot, action_id f"camera-vision-{ts}-{index}") -- direct `await tool.run(...)` from `CameraVision`, subscribed to CAMERA_EVENT at service.py:223
- simorgh/execution/vision.py:214-259 -- line 235 is inside `CameraDescribeTool.run` and reuses the caller's `ctx`; motion events call `describe_stills()` (vision.py:151-183) directly, never camera_describe
- simorgh/execution/vision.py:166-176 -- cognition.think request carries `"budget": {"max_tokens": 200, "max_cost_usd": 0.02}, "require_real_provider": True`
- simorgh/execution/config.py:466 `tv_show_on_start: bool = False`; :479 `ring_watch_on_start: bool = True`; :486 `cam_watch_on_start: bool = True`; `grep tv_show_on_start ~/.simorgh/simorgh.toml` -> no match (only `cast_device = "Family Room TV"` at line 20)
- python import of the tool classes: ring_snapshot, ring_watch, cam_snapshot, cam_watch, cast_show, tv_charts all `read_only=False reversibility=reversible`; simorgh/guardian/rules.py:245-269 ModeRule denies non-read-only tools in observe/locked/plan; :235-242 PausedRule denies when paused
- Ledger count (python over ~/.simorgh/ledger/streams, first 'received' event per action stream): action streams 26737; camera_describe 0, cam_watch 1, ring_watch 5, cast_show 114, tv_charts 2, cam_snapshot 5, ring_snapshot 9; top tools ring_live 22849, cam_stream 721; no stream named *boot*/*vision*/*baseline*; `grep -l cam_snapshot|cognition.think|cast_show trace%3A*` -> 0 files each
- simorgh/execution/home/cameras.py:28 'a tool call, so Guardian sees it -- the siren above all'; simorgh/execution/mcp.py:14-19 'Guardian's whole design is "a reviewed capability..." ... flows through the exact same `action.proposed` -> Guardian'
- docs/architecture-audit-2026.md:8 'Every effect is published as `action.proposed`' -- prior review treats the invariant as holding; no mention of autostart/tool.run bypass in the three prior review docs (grep -i 'autostart|tool.run(|ring-watch-boot|outside guardian' -> none)
- simorgh/interface/dispatch.py:1298 `_run_tool` publishes ACTION_PROPOSED with `proposed_by: f"interface:{session_id}"` -- the pattern the recommendation proposes reusing does exist

**severity adjustment:** lower

