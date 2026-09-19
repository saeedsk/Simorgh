# refute:correctness:Decorative metadata: read_only contradic

*Workflow: review · Phase: Refute · Agent id: `aa2eb04dd4fd44ecc` · Tool calls: 8*

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
| 1 | Bash | Grep guardian rules for read_only, reversibility, network | 132: reached `needs_human` (reversibility only) with no denylist reason 168:# in free-form code denies the call: without this, fixing "the read_only 219: # all, |
| 2 | Bash | Read guardian rules sections and grep tools.py policy table |  # would be denied as an attempt on Execution's source. return [t for t in _PATHISH.findall(text or "") if not t.startswith("tests/")] # A crude sign that a `co |
| 3 | Bash | Read policy table entries, read_only declarations, and network consumers |  "git_discard": ("reversible", False), # A shell can reach the network and anything else on the machine; # Guardian gates every call on `irreversible` (executio |
| 4 | Bash | Locate sandbox policy rows, read_only declarations, network consumers, and known-findings mentions | 48: "run_python_sandboxed": ("reversible", False), 49: "run_js_sandboxed": ("reversible", False), 50: "run_tests": ("reversible", False), 318: "run_tests": "a t |
| 5 | Bash | Find sandbox ToolSpec declarations, scope consumption in Execution, and prior-review mentions | 129: read_only = True 130: reversibility = "read_only" 190: read_only = True 191: reversibility = "read_only" 232: read_only = True 233: reversibility = "read_o |
| 6 | Bash | Read sandbox tool declarations, reproduce the import measurement, find scope.network consumers, check prior reviews |  is correct for standalone code, structurally wrong for a self-patch's normal cross-module imports, which is why self-patches are verified by the isolated test  |
| 7 | Bash | Check the no-network-rule comment, pipeline order, how Guardian learns tool.read_only, and prior-review mentions |  link-local/reserved/multicast addresses after DNS resolution (SSRF protection); bounded in time and response size; rate-limited over a rolling window; identifi |
| 8 | Bash | Check how Guardian derives read_only, where ToolSpec.read_only is consumed, and the git order of the two changes |  task_id=p.get("task_id"), task_mode=task.mode, origin=task.origin, ) ctx = DecisionContext( now=self._ctx.clock.now(), system_state=self._system_state, posture |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Both halves of the metadata inconsistency exist in today's code, but the causal story linking the sandbox `read_only=True` to Guardian's code-argument scan is wrong. (1) The three sandbox ToolSpecs really do declare `read_only = True` alongside `reversibility = "reversible"` (execution/tools.py:1026-1027, 1091-1092, 1222-1223); I reproduced the import measurement. However Guardian never reads that class attribute: guardian/service.py:524 builds `ToolInfo(read_only=proposal.reversibility == "read_only", ...)`, and `proposal.reversibility` comes from orchestration's `_TOOL_POLICY` (orchestration/tools.py:48-50 list all three as `("reversible", False)`; line 693 reads that tuple into the proposal). So Guardian already sees these tools as NOT read-only; ModeRule (rules.py:257-268) denies them in locked/plan mode and ReversibilityRule treats them as reversible. The recommendation "derive read_only from reversibility" is therefore already implemented at the Guardian boundary. The ProtectedRule carve-out (`_CODE_ARG_KEYS`, rules.py:296-300 -- ProtectedRule, not ModeRule as the finding says) is defence in depth against a case the derivation already precludes for these tools; its 2026-09-08 comment describes the ToolSpec flag, which is now dead metadata only published into `tool.registered` bus/ledger events (execution/service.py:170,175,450,658). What remains true and new: there are two sources of truth for reversibility (ToolSpec.reversibility vs `_TOOL_POLICY`), and the ToolSpec `read_only` flag is decorative and self-contradicting. (2) The network half is fully confirmed: `scope.network` is computed from `_TOOL_POLICY` and stored on every proposal (orchestration/tools.py:693,715), `grep -n network simorgh/guardian/rules.py` returns nothing, `ScopeRule` unconditionally abstains (rules.py:337-349), Execution reads only `scope["kind"]` (execution/tools.py:1790), and execution/tools.py:565-568 states outright "there is no independent network-scope rule yet". Not in the known-findings list (no `read_only`/`scope.network` mention in docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html or docs/architecture-third-opinion-2026-09-18.md), though it is an instance of the already-known "unconnected wire" shape. Severity stays low: no live safety gap results because Guardian's derivation neutralises the contradiction.

### evidence

- Reproduced by import: python3 -c '...inspect simorgh.execution.tools...' -> [('run_js_sandboxed', True, 'reversible'), ('run_python_sandboxed', True, 'reversible'), ('run_tests', True, 'reversible')]; _TOOL_POLICY -> {'run_python_sandboxed': ('reversible', False), 'run_js_sandboxed': ('reversible', False), 'run_tests': ('reversible', False)}
- simorgh/execution/tools.py:1026-1027 `read_only = True` / `reversibility = "reversible"` (run_python_sandboxed); same at 1091-1092 (run_js_sandboxed) and 1222-1223 (run_tests)
- simorgh/guardian/service.py:522-526: `tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)` -- Guardian derives read_only from the proposal's reversibility, never from ToolSpec.read_only
- simorgh/orchestration/tools.py:693 `reversibility, network = _TOOL_POLICY.get(tool, ("irreversible", False))` and :715 `"scope": {"paths": paths, "network": network, ...}` -- proposal reversibility and scope.network both come from _TOOL_POLICY
- simorgh/guardian/rules.py:257 `read_only = bool(ctx.tool and ctx.tool.read_only)` (ModeRule); rules.py:296-300 the `_CODE_ARG_KEYS` carve-out lives in ProtectedRule, not ModeRule
- `grep -n network simorgh/guardian/rules.py` -> no output; simorgh/guardian/rules.py:337-349 ScopeRule.evaluate always returns Decision("abstain")
- simorgh/execution/tools.py:565-568: 'Guardian's `ReversibilityRule` allows read-only actions unconditionally -- there is no independent network-scope rule yet'
- simorgh/execution/tools.py:1790 `kind = str((ctx.scope or {}).get("kind") or "")` -- the only scope field Execution reads; no consumer of scope["network"] outside container.py's own args
- simorgh/execution/service.py:170,175,450,658 -- the only places ToolSpec.read_only is consumed (tool.registered bus payload and ledger record)
- grep -i 'read_only|scope.*network' over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md -> no hits (not previously reported)

**severity adjustment:** keep

**corrected claim:** The three sandbox ToolSpecs (run_python_sandboxed, run_js_sandboxed, run_tests) declare `read_only=True` with `reversibility="reversible"` (execution/tools.py:1026-1027, 1091-1092, 1222-1223), but that flag is dead metadata: Guardian derives `ToolInfo.read_only` from `proposal.reversibility == "read_only"` (guardian/service.py:524), and the proposal's reversibility comes from orchestration's `_TOOL_POLICY`, which lists all three as `("reversible", False)` (orchestration/tools.py:48-50, 693). So Guardian already treats them as non-read-only; the `_CODE_ARG_KEYS` carve-out in ProtectedRule (rules.py:296-300, not ModeRule) is defence in depth, not a patch around a live contradiction. The real defect is two sources of truth for reversibility (ToolSpec vs `_TOOL_POLICY`) plus a ToolSpec `read_only` flag that is only ever published into `tool.registered` events (execution/service.py:170,175). Separately and fully confirmed: `scope.network` is computed and stored on every proposal (orchestration/tools.py:715) but no Guardian rule reads it, ScopeRule always abstains (rules.py:337-349), Execution reads only `scope["kind"]` (execution/tools.py:1790), and execution/tools.py:565-568 acknowledges "there is no independent network-scope rule yet".

