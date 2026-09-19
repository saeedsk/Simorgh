# refute:correctness:Tool errors are a string convention with

*Workflow: review · Phase: Refute · Agent id: `a9aa834fcc0c7777a` · Tool calls: 7*

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
    "title": "Tool errors are a string convention with no kind, so callers cannot tell 'unconfigured' from 'transient' from 'refused'",
    "kind": "wrong-design",
    "severity": "low",
    "claim": "ToolResult has ok/error only; 186 sites construct `error=\"refused: ...\"` and ReadFileTool decides `ok` by sniffing `content.startswith(\"[refused:\")`, so the session, the retry logic and the model all classify failures by reading prose.",
    "evidence": [
      "simorgh/contracts/protocols.py:185-192 ToolResult fields: ok, output, output_ref, error, side_effects, metadata - no kind",
      "`grep -rn 'error=f\"refused\\|error=\"refused' simorgh/execution | wc -l` -> 186; simorgh/execution/tools.py:163 `ok = not content.startswith(\"[refused:\")`",
      "simorgh/execution/home/tools.py:75-83 'refused: Home Assistant is not configured' and cameras.py:56-58 'needs reolink-aio' are the same `ok=False` as a network failure"
    ],
    "why_it_matters": "A model that sees 'refused: not configured' three times in a turn has no structured signal to stop; the session cannot auto-retry a transient without also retrying a policy refusal; the ledger cannot be queried for 'how often does tool X fail for lack of setup'.",
    "recommendation": "Add `kind: str = \"\"` to ToolResult with five values (refused, unconfigured, bad_args, transient, failed) and a helper `refused(msg)`/`unconfigured(msg)` in contracts; migrate call sites opportunistically (the `refused:` prefix can be derived from kind during the transition). Then orchestration/session.py drops a tool from the offered list for the rest of the turn after `unconfigured`, and retries once on `transient`.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read ToolResult definition and refused-sniffing site |  scope: dict constraints: dict data_dir: Path clock: Clock logger: Logger ledger: Ledger bus: Bus \| None = None # composite tools (drafting loops) may request c |
| 2 | Bash | Check cited call sites and whether any caller classifies errors structurally |  value = None if value: return str(value) return str(self._env.get(env_name) or "") def _aliases(self) -> dict: return dict(getattr(self._config, "home_aliases" |
| 3 | Bash | Check cameras site, other string-sniff sites, retry logic, and known-findings list | SNAPSHOT_DIR = Path("workspace/cameras") _PTZ = {"left": "Left", "right": "Right", "up": "Up", "down": "Down", "stop": "Stop", "zoom_in": "ZoomInc", "zoom_out": |
| 4 | Bash | Check session error handling, retry logic, and the tool result event schema |  now = ctx.clock.now() cutoff = now - self._config.web_search_window_s while self._recent_calls and self._recent_calls[0] < cutoff: self._recent_calls.pop(0) if |
| 5 | Bash | Check cameras call site, session result handling, and tool.unavailable structured event |  return self._given if self._prefs.nvr is None: ok, why = available() if not ok: raise RuntimeError(why) host, user, password = self._secret(SECRET_HOST), self. |
| 6 | Bash | Check probe-time structured unavailability and how cameras converts errors |  "fix": result.fix, "missing": list(result.missing)} with contextlib.suppress(Exception): await self._ctx.bus.publish(Message.new( topics.TOOL_PROBED, source="e |
| 7 | Bash | Check how unavailable tools reach the offered list and whether prior reviews cover ToolResult errors | 45:def unavailable_note(offered: tuple[str, ...] \| list[str]) -> str: 46- """What to tell the model about tools it is being offered that are 47- known not to wo |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core claim is true of the code today: ToolResult (simorgh/contracts/protocols.py:184-191) carries only ok/output/output_ref/error/side_effects/metadata, with no kind; the action.result wire schema mirrors that (error is a nullable string, no kind). ReadFileTool decides ok by sniffing the content prefix (tools.py:160 and again at :201, not :163). The session consumes a tool result by reading `ok` and the `error` string and pasting it into the model's view (session.py:1655-1670) with no classification. Home Assistant's `_unconfigured` (home/tools.py:78-85) and the Reolink path (cameras.py:56-58 -> `raise RuntimeError(why)` at :270-272 -> `error=f"refused: {exc}"` at :402/:435) both surface as the same `ok=False, error="refused: ..."` as a network exception. websearch.py:359-362 documents the exact consequence the finding predicts (model read a refusal as transient and re-issued 26 searches) and fixed it with more prose. Not in the known-findings list; no prior review mentions ToolResult. Three corrections: (1) my count of `error="refused`/`error=f"refused` sites in simorgh/execution is 197, not 186; (2) there is no per-call retry logic in the session at all -- retries exist only at task-attempt level (worker.py) -- so "the retry logic classifies by prose" is overstated: nothing retries per call, prose-read or otherwise; (3) materially, the system ALREADY has a structured 'not configured' vs 'configured but broken' vocabulary at probe time -- ConnectorStatus.missing (contracts/connector.py:44-60, domainstatus.py:14-21), the `tool.unavailable` event (execution/service.py:357-393), and scaffolds.unavailable_note (scaffolds.py:45-56) which tells the model 'Do not spend steps on these'. That signal is probe-time and free-probes-only; it never propagates to the per-call ToolResult/action.result. So the design gap is narrower than 'no structured signal': the kind exists in one layer and is dropped at the call boundary. Severity low is right for one laptop.

**corrected claim:** ToolResult (contracts/protocols.py:184-191) and the action.result schema carry only ok + a free-text error; ~197 sites in simorgh/execution build `error="refused: ..."`, ReadFileTool sniffs `content.startswith("[refused:")` (execution/tools.py:160, :201), and the session forwards the error string to the model unclassified (orchestration/session.py:1655-1670). 'Not configured' (home/tools.py:78-85, cameras.py:270-272 -> :402) and a network exception are indistinguishable per call. The project already distinguishes unconfigured-vs-broken structurally at probe time (ConnectorStatus.missing, tool.unavailable, scaffolds.unavailable_note) but that never reaches the per-call result, and there is no per-call retry logic at all, so nothing can retry a transient. websearch.py:359-362 records the live consequence (26 re-issued searches) and patched it with more prose.

### evidence

- simorgh/contracts/protocols.py:184-191 -- `class ToolResult: ok: bool; output: str; output_ref: str; error: str | None; side_effects; metadata` -- no kind field
- simorgh/contracts/schema/action.result.v1.json -- `error: [string, null]`, `ok: boolean`; no kind on the wire either
- `grep -rn 'error=f"refused\|error="refused' simorgh/execution | wc -l` -> 197 (reader said 186)
- simorgh/execution/tools.py:160 and :201 -- `ok = not content.startswith("[refused:")` (two sites; reader cited :163)
- simorgh/execution/home/tools.py:78-85 -- `_unconfigured` returns `ToolResult(ok=False, error="refused: Home Assistant is not configured...")`
- simorgh/execution/home/cameras.py:56-58 `available()` -> (False, 'needs reolink-aio'); :270-272 `raise RuntimeError(why)`; :402/:435 `return ToolResult(ok=False, error=f"refused: {exc}")` -- same shape as any exception
- simorgh/orchestration/session.py:1655-1670 -- reads `payload.get("ok")` and `payload.get("error")`, concatenates error into the model-visible text; no classification
- `grep -n retry simorgh/orchestration/session.py simorgh/orchestration/worker.py` -- only attempt-level retries (worker.py:36, :430); no per-call retry exists
- simorgh/execution/websearch.py:359-362 -- comment: 'Without it the model reads a refusal as a transient failure and re-issues the same search: 26 steps of one GAIA run, 2026-09-10' -- fixed by adding prose
- simorgh/contracts/connector.py:44-60 ConnectorStatus.missing: 'non-empty means nothing is set up, which is not a fault; empty while ok is false means set up and not answering' -- structured distinction exists at probe time
- simorgh/execution/service.py:357-393 `_announce_unavailable` publishes `tool.unavailable {name, reason}` for failed free probes only; simorgh/orchestration/scaffolds.py:45-56 `unavailable_note` tells the model 'Do not spend steps on these'
- `grep -n ToolResult docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md` -> no hits; not in the known-findings list

**severity adjustment:** keep

