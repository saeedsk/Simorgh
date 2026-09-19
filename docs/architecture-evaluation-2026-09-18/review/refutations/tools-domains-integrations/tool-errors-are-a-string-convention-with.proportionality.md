# refute:proportionality:Tool errors are a string convention with

*Workflow: review · Phase: Refute · Agent id: `ae3b001aaae152a67` · Tool calls: 9*

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
| 1 | Bash | Read the cited ToolResult, read-file, home and camera lines |  scope: dict constraints: dict data_dir: Path clock: Clock logger: Logger ledger: Ledger bus: Bus \| None = None # composite tools (drafting loops) may request c |
| 2 | Bash | Find consumers of refused prefix, retry logic, and metadata kind usage | == consumers of the refused: prefix outside constructors == (eval):1: no matches found: --include=*.py == retry logic on tool results == simorgh/orchestration/s |
| 3 | Bash | Look for prefix consumers, session handling of failures, and ledger record shape | == consumers sniffing the prefix == simorgh/execution/tools.py:160: ok = not content.startswith("[refused:") simorgh/execution/tools.py:201: ok = not content.st |
| 4 | Bash | Inspect was_denied, boot probes, and action.result contract | == was_denied == simorgh/orchestration/session.py:40:def was_denied(detail: str) -> bool: simorgh/orchestration/session.py:40:def was_denied(detail: str) -> boo |
| 5 | Bash | Read the action contract, probe path and tool.unavailable consumers | == action.py contract == """`action.*` -- the guarded action path (section 4.6; docs/blueprint/ 02 section 3). Only guardian may consume `action.proposed`; only |
| 6 | Bash | Check probe classification, tool-list filtering, retry logic and failure rendering | == connector probes: is 'not configured' a probe outcome? == 17:- **not configured** -- nothing has been set up, and the probe says the 19:- **configured but no |
| 7 | Bash | Read connector status model, unavailable note, and session failure rendering | == domainstatus header + ConnectorStatus + HA probe == """Is each domain switched on, and does it actually work? `capabilities` answers that for Node and Docker |
| 8 | Bash | Check unavailable feeder, ConnectorStatus fields, and uniformity of the refused convention | == scaffolds _UNAVAILABLE feeder == """ from __future__ import annotations from .api import Profile from .tools import offered_tools # Filled at runtime from `c |
| 9 | Bash | Read probe-to-prompt wiring, the not-configured instruction, and the render sniffer | == orchestration/service.py 180-215 == """Same seam, same fix, for the other stream Execution announces before we are listening. Execution's capability probes ( |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The observation is accurate and, if anything, understated: ToolResult carries no failure kind, 365 `ok=False` sites exist in simorgh/execution of which only ~185 use the `refused:` prose prefix, the prefix has two spellings (`refused:` x197, `[refused:` x8), and three machine consumers classify failures by sniffing text (tools.py:160/201, session.py:40-41 `was_denied`, verification/checks/render.py:32,50). That is a genuine implementation inconsistency. But the 'wrong-design' framing and the recommendation do not survive the code around it. (1) Policy refusals are already structured: Guardian publishes ActionDenied with an 8-value `layer` enum; the `refused:` strings are tool-internal refusals (path safety etc.), a different path. (2) 'Unconfigured' is already a first-class state at the connector layer: domainstatus.py deliberately separates 'not configured' from 'configured but not working' and ConnectorStatus carries a `missing` tuple. The only gap is one unconnected wire: `_probe_tools` maps only PROBES, so a connector's not-configured status never reaches `scaffolds.unavailable_note`'s 'Do not spend steps on these' line. That is a one-line fix, not a 365-site migration. (3) No per-tool retry exists anywhere in orchestration; 'the session cannot auto-retry a transient' describes a mechanism nobody built. Retries are task-level by design. (4) 'Drop the tool after unconfigured' directly contradicts the creator's `_RESOURCEFUL` rule (scaffolds.py:383-400: 'do not stop at "not configured"'). (5) 'The ledger cannot be queried' is overstated: `error` is on ActionResult and a prefix query works on JSONL. At this scale (one model as the main consumer, which reads prose fine; three machine consumers) an additive `kind: str = ""` on the frozen dataclass is cheap and reasonable, but the migration and the proposed session behaviour changes are disproportionate and partly wrong.

**corrected claim:** ToolResult (simorgh/contracts/protocols.py:184-191) carries no failure kind; of 365 `ok=False` sites in simorgh/execution only ~185 use a `refused:` prose prefix, in two spellings, and three machine consumers sniff error text (execution/tools.py:160,201; orchestration/session.py:40-41; verification/checks/render.py:32,50). However, policy refusals are already typed (ActionDenied.layer enum) and 'unconfigured' is already typed at the connector layer (ConnectorStatus.missing, execution/domainstatus.py); the actual gap is that `_probe_tools` (execution/service.py:58-60) never maps connector probes to tools, so a not-configured domain never reaches the model's 'Do not spend steps on these' note. No transient-retry logic exists to be unblocked, and dropping a tool after 'unconfigured' would violate the project's _RESOURCEFUL rule (orchestration/scaffolds.py:383-400). An additive `kind` default field is cheap; the site migration and session behaviour changes are not warranted.

### evidence

- simorgh/contracts/protocols.py:184-191 `class ToolResult: ok, output, output_ref, error, side_effects, metadata` - no kind field (confirmed)
- `grep -rn 'error=f"refused\|error="refused' simorgh/execution | wc -l` -> 197 (finding said 186); `grep -rn 'ok=False' simorgh/execution | wc -l` -> 365; of those `| grep -c refused` -> 185; `grep -rn '"\[refused' simorgh | grep -v tests/ | wc -l` -> 8 (two spellings of the prefix)
- simorgh/execution/tools.py:160 and :201 `ok = not content.startswith("[refused:")` (confirmed)
- simorgh/orchestration/session.py:37-41 `DENIED_PREFIX = "denied: "` / `def was_denied(detail): return (detail or "").startswith(DENIED_PREFIX)` - a second prose sniffer the finding did not cite
- simorgh/verification/checks/render.py:32,50 `_UNAVAILABLE = ("no `node` executable", "could not locate Puppeteer")` ... `if any(marker in error for marker in _UNAVAILABLE)` - a third prose sniffer
- simorgh/contracts/messages/action.py:12 `DENY_LAYER = Enum("policy","denylist","immunity","budget","paused","scope","classifier","token")` and :33-47 ActionDenied carries `layer` - policy refusals are already typed
- simorgh/execution/domainstatus.py:14-21 docstring: 'Two states are deliberately distinguished ... not configured ... configured but not working'; :159-163 HomeConnector.probe returns ConnectorStatus(False, 'needs Home Assistant, which is not configured', client.missing(), fix=...)
- simorgh/contracts/connector.py:41-55 ConnectorStatus has `ok`, `detail`, `missing` tuple, `fix` - unconfigured is structured at the connector layer
- simorgh/execution/service.py:58-60 `_probe_tools(name)` looks up only `PROBES`, so `connector_probe(c)` results (service.py:325) publish `tools: []` and never populate scaffolds._UNAVAILABLE; simorgh/orchestration/scaffolds.py:45-58 `unavailable_note` renders 'Do not spend steps on these' only from that dict
- `grep -rln transient simorgh | grep -v tests/` hits no file under simorgh/orchestration; `grep -rn 'consecutive\|repeated.*fail\|failed twice' simorgh/orchestration/*.py` -> nothing: no per-tool retry or repeat-failure logic exists for a kind to drive
- simorgh/orchestration/scaffolds.py:383-400 `_RESOURCEFUL`: 'A missing capability is not a denial ... do not stop at "not configured" or "needs an API key"' - contradicts the recommendation to drop a tool after `unconfigured`
- simorgh/contracts/messages/action.py:50-58 ActionResult carries `ok`, `error` on the ledger; `error` prefix is queryable, so 'the ledger cannot be queried' is overstated

**severity adjustment:** keep

