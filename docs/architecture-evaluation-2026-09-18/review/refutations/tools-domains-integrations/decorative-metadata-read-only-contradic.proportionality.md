# refute:proportionality:Decorative metadata: read_only contradic

*Workflow: review · Phase: Refute · Agent id: `ab65244df2a2d0e94` · Tool calls: 7*

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
    "title": "Decorative metadata: read_only contradicts reversibility on the sandboxes, and the policy table's network flag is never read",
    "kind": "bug",
    "severity": "low",
    "claim": "run_python_sandboxed, run_js_sandboxed and run_tests declare `read_only=True` with `reversibility=\"reversible\"`, which Guardian's ModeRule had to patch around with a code-argument scan, and the `(reversibility, network)` tuple's second element becomes `scope.network` that no Guardian rule consults.",
    "evidence": [
      "Measured by import: `read_only flag vs reversibility label inconsistent: [('run_python_sandboxed', True, 'reversible'), ('run_js_sandboxed', True, 'reversible'), ('run_tests', True, 'reversible')]`",
      "simorgh/guardian/rules.py:286-300: '`run_python_sandboxed` is declared `read_only=True` and runs an arbitrary subprocess with no chroot; an observer proved this exact early return made today's code-payload scan a COMPLETE no-op' -> special-cased via `_CODE_ARG_KEYS`",
      "simorgh/orchestration/tools.py:715 `\"scope\": {\"paths\": paths, \"network\": network, ...}`; `grep -n network simorgh/guardian/rules.py` -> no output (guardian/config.py mentions network only in denylist regexes)"
    ],
    "why_it_matters": "Two booleans that disagree invite exactly the rule-by-rule patching already visible in rules.py; a flag that is computed, transported and stored on every action but never read is the 'unconnected wire' in miniature.",
    "recommendation": "Delete `read_only` from the protocol and derive it (`reversibility == \"read_only\"`), which also removes the sandbox contradiction; either make ScopeRule deny `scope.network` in `locked` posture or drop the column from `_TOOL_POLICY`. Thirty minutes plus the boundary test.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Grep for network in guardian and orchestration tools | ---rules.py network grep exit: 1 simorgh/guardian/config.py:49: r"\bsocket\.\b": "opens raw network sockets (Directive 1, Directive 5)", simorgh/guardian/config |
| 2 | Bash | Read tool policy table and action-building code |  MARKER_NO_ARGS, MARKER_SPLIT_FIRST_LINE, json_rest, strip_code_fence, ) # (reversibility, network) per known tool name -- conservative default # for anything u |
| 3 | Bash | Read ModeRule and search for read_only and network readers |  if ctx.system_state in ("paused", "stopping"): return Decision("deny", self.layer, (f"system is {ctx.system_state}",)) return Decision("abstain", self.layer) c |
| 4 | Bash | Read Guardian's read_only derivation, tool declarations, and network scope readers |  # unbounded map is a leak in a process meant to run for months # (`security.ReplayGuard` beside it evicts at 10,000). if len(self._decided) >= _MAX_DECIDED: fo |
| 5 | Bash | Find where execution declares and reads the read_only tool flag | simorgh/execution/config.py:620: read_only_tools=frozenset(server.get("read_only_tools", ())), simorgh/execution/container.py:88: read_only = False simorgh/exec |
| 6 | Bash | Check sandbox tool declarations, read_only consumers, ScopeRule, and re-measure inconsistency by import | =====sandbox tool decls 942: reversibility = "reversible" 1016:class RunPythonSandboxedTool: 1024: name = "run_python_sandboxed" 1026: read_only = True 1027: re |
| 7 | Bash | Check whether Execution or any consumer acts on the read_only flag |  # the same name is never shadowed by an optional package's. external = load_external_tools(self._config.external_tools, logger=ctx.logger) for tool in builtin_ |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The two factual observations hold, but the causal story and the framing do not. (1) The three sandbox tool classes really do declare `read_only = True` next to `reversibility = "reversible"` (simorgh/execution/tools.py:1026-1027, 1091-1092, 1222-1223; re-measured by import). But Guardian never reads that class attribute. simorgh/guardian/service.py:524 constructs `ToolInfo(read_only=proposal.reversibility == "read_only", ...)`, and the proposal's reversibility comes from orchestration's `_TOOL_POLICY` (simorgh/orchestration/tools.py:48-50, all three "reversible"). So for the sandboxes `ctx.tool.read_only` is False today, ModeRule (rules.py:257) already treats them as writing tools, and the `_CODE_ARG_KEYS` guard at rules.py:298 is no longer "patching around" the flag for them — it is redundant defense-in-depth. The finding's claim that "Guardian's ModeRule had to patch around it" is wrong twice: the scan lives in ProtectedRule, not ModeRule, and the rules.py:286-300 comment is a 2026-09-08 historical note, exactly the kind the ground rules warn against reporting as current state. The recommendation ("derive read_only from reversibility") is what Guardian already does at service.py:524; the declared flag's only remaining consumers are the tool.registered bus/Ledger payloads (execution/service.py:170,175) and the WorldModel ToolsFacet (worldmodel/facets/registry_facets.py:18), none of which decide anything on it. Decorative, yes; dangerous, no. (2) `scope.network` is genuinely never consulted by Guardian: `grep -n network simorgh/guardian/rules.py` prints nothing, and ScopeRule (rules.py:337-349) unconditionally abstains. But the author documents this gap in the code itself, in two places (rules.py:342-348 and execution/tools.py:565-571: "there is no independent network-scope rule yet ... the tool's own SSRF guard, size/rate caps ... are the actual safety boundary today"), so it is a known, deliberate deferral rather than an unnoticed unconnected wire. At one-laptop/one-family scale, the real network boundary is web_fetch's SSRF guard plus the denylist regexes in guardian/config.py:49-52, and the network-bearing tools are mostly read_only (web_fetch, web_search, cal_list, mail_*), so a "deny scope.network in locked posture" rule would be a real behavioural change worth designing, not a 30-minute tidy. Net: a cosmetic metadata inconsistency and a self-documented deferred rule; the alarming half of the claim (Guardian forced into rule-by-rule patching) is not the current code.

### evidence

- simorgh/execution/tools.py:1024-1027 `name = "run_python_sandboxed"` / `read_only = True` / `reversibility = "reversible"`; same shape at 1089-1092 (run_js_sandboxed) and 1217-1223 (run_tests). Re-measured by import: [('run_js_sandboxed', True, 'reversible', ('reversible', False)), ('run_python_sandboxed', True, 'reversible', ('reversible', False)), ('run_tests', True, 'reversible', ('reversible', False))]
- simorgh/guardian/service.py:522-526: `tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)` -- Guardian derives read_only from reversibility, never from the tool class's declared flag
- simorgh/orchestration/tools.py:48-50: `"run_python_sandboxed": ("reversible", False)`, `"run_js_sandboxed": ("reversible", False)`, `"run_tests": ("reversible", False)`; tools.py:693 `reversibility, network = _TOOL_POLICY.get(tool, ("irreversible", False))` -- the proposal's reversibility, hence Guardian's read_only, is "reversible"/False for all three
- simorgh/guardian/rules.py:257 `read_only = bool(ctx.tool and ctx.tool.read_only)` (ModeRule); rules.py:296-300 the `_CODE_ARG_KEYS` guard is in ProtectedRule, not ModeRule, and its comment (286-295) is dated 2026-09-08
- `grep -rn read_only simorgh --include=*.py` outside execution/guardian/contracts/tests: only worldmodel/facets/registry_facets.py:18 stores it; no consumer branches on the declared flag. execution/service.py:170,175 only publish it in tool.registered
- `grep -n network simorgh/guardian/rules.py` -> no output (exit 1). simorgh/guardian/rules.py:337-349 ScopeRule: `return Decision("abstain", self.layer)` unconditionally, with comment 'this rule always abstains rather than fabricate a boundary'
- simorgh/execution/tools.py:565-571 (web_fetch docstring): 'there is no independent network-scope rule yet (guardian/rules.py::ScopeRule notes the same kind of gap) ... The tool's own SSRF guard, size/rate caps, and honest logging are the actual safety boundary today' -- the gap is self-documented
- simorgh/guardian/config.py:49-52: denylist regexes for `socket.`, `urllib.request`, `requests.(get|post|...)` -- the actual network control on code payloads

**severity adjustment:** lower

**corrected claim:** Three sandbox tool classes (run_python_sandboxed, run_js_sandboxed, run_tests) carry a declared `read_only=True` that contradicts their `reversibility="reversible"`, but the flag is inert: Guardian derives `ToolInfo.read_only` from `proposal.reversibility` (guardian/service.py:524), so it already treats them as writing tools and the class attribute is only echoed into tool.registered and the WorldModel tools facet. Removing `read_only` from the Tool protocol would be a small cleanup, not a safety fix. Separately, `scope.network` is transported on every action but no Guardian rule reads it (ScopeRule always abstains, rules.py:337-349); the author documents this deferral in both rules.py and execution/tools.py:565-571, with web_fetch's SSRF guard and the config.py denylist as the actual network boundary.

