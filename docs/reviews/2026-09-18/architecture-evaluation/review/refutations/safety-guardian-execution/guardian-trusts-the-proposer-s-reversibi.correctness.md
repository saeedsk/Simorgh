# refute:correctness:Guardian trusts the proposer's reversibi

*Workflow: review · Phase: Refute · Agent id: `ab50f612408054f45` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "safety-guardian-execution". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Guardian trusts the proposer's reversibility label and has no view of the tool registry",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "Guardian builds `ToolInfo` from `p[\"reversibility\"]` in the proposal (service.py:504, 522-526) and does not consume `tool.registered`; the label comes from Orchestration's `_TOOL_POLICY` (orchestration/tools.py:630-636, 693), and `simorgh/orchestration/` is writable and not protected, so a self-patch to one table (or one `replace_in_file`, approved reversible) re-labels `run_shell` as read_only and every mode/reversibility rule then treats it as a read.",
    "evidence": [
      "simorgh/guardian/service.py:97-110 `consumes` has no TOOL_REGISTERED; service.py:522-526 `ToolInfo(name=proposal.tool, read_only=proposal.reversibility == \"read_only\", reversibility=proposal.reversibility)`",
      "simorgh/orchestration/tools.py:693 `reversibility, network = _TOOL_POLICY.get(tool, (\"irreversible\", False))`",
      "Offline pipeline: `approved replace_in_file {'path': 'simorgh/orchestration/tools.py', ...}` (orchestration is not in DEFAULT_PROTECTED_SUBJECTS, guardian/config.py:21-41)",
      "contracts/home/policy.py:5-8 states the intent 'so Guardian never has to trust a label the proposer supplied' -- Guardian does exactly that"
    ],
    "why_it_matters": "The HMAC binds the decision to the args, but the decision itself was made on a label the (unprotected) proposer chose. The corrigibility boundary is drawn around guardian/execution/kernel/contracts, yet the input that most of the pipeline branches on originates outside it.",
    "recommendation": "Have Guardian subscribe to `tool.registered` and keep its own name->reversibility map (Execution is protected; its declarations are the trustworthy source), ignoring the proposal's field except for the `home_call` per-call classification, which Guardian should recompute itself with `classify_call`. Consider adding `simorgh/orchestration/tools.py` and `profiles.py` to the protected list.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read Guardian consumes list and ToolInfo construction |  question = question[:_QUESTION_MAX_CHARS - 1] + "…" return question class Service: name = "guardian" version = "0.1.0" consumes = ( topics.ACTION_PROPOSED, top |
| 2 | Bash | Read tool policy table, protected subjects, and home policy intent |  # one slow MCP server -- the intersection would drop every builtin # from every later session, leaving a patch session with no # read_file (observer, 2026-09-0 |
| 3 | Bash | Check whether Guardian consumes tool registration or recomputes home_call class, and where the policy table is fed | ---- 29:_TOOL_POLICY: dict[str, tuple[str, bool]] = { 346: # into `_TOOL_POLICY` by mistake instead of here -- a duplicate 580: return _TOOL_POLICY.get(tool, (" |
| 4 | Bash | Check who calls register_tool_policy, how rules use reversibility, whether Execution re-checks it, and whether the finding is already known | simorgh/execution/tools.py:2739: register_tool_policy` hardcoded every skill's marker arg to `"text"` simorgh/execution/tools.py:2785: # `orchestration/tools.py |
| 5 | Bash | Read mode rule free-form exemption, reversibility rule, Execution-side checks, and prior-review mentions | ---- rules 280-305 # *is* allowed to change. Found by a watched trial, 2026-09-07: # a plain `read_file` of simorgh/kernel/cli.py was denied with # "only the cr |
| 6 | Bash | Check code-arg keys, config overrides, whether orchestration is protected anywhere, and what Execution's verifier compares | 116:_CODE_ARG_KEYS = ("code", "command") 117- 118- 119-def _code_arg_text(value: object) -> str \| None: ---- toml ---- denylist mentions orchestration ---- exec |
| 7 | Bash | Check whether Execution compares approved reversibility to its own tool declaration | 86: wins, then the tool's own declared `timeout_s`, then the default. 93: declared = constraints.get("timeout_s") 94: if declared: 95: return float(declared) 17 |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line matches the current code. Guardian's `consumes` (guardian/service.py:97-110) has no TOOL_REGISTERED and nothing in simorgh/guardian/ references tool.registered or classify_call; ToolInfo is built purely from the proposal's reversibility field (service.py:504, 522-526). Orchestration derives that field from a static `_TOOL_POLICY` table (orchestration/tools.py:29, run_shell at :83, lookup at :693), and `register_tool_policy` (:635-636) only inserts when the name is absent, so Execution's own declaration on tool.registered never overrides the static label for a builtin -- the orchestration table is the effective source of truth. ReversibilityRule (guardian/rules.py:725-727) allows outright on read_only and ModeRule (:257-267) branches on ctx.tool.read_only. simorgh/orchestration/ is absent from DEFAULT_PROTECTED_SUBJECTS (guardian/config.py:21-41), ~/.simorgh/simorgh.toml sets no protected_subjects override, and Execution's verifier checks only the HMAC over args (execution/service.py:756, verifier.py:37) with no comparison of approved reversibility against the tool's declared reversibility. contracts/home/policy.py:5-8 states the intent that Guardian never trust a proposer label; Guardian does not call classify_call. One nuance the finding overstates: ProtectedRule (rules.py:296-300, _CODE_ARG_KEYS at :116 = code, command) never exempts a proposal carrying a code/command argument regardless of read_only, so a relabelled run_shell would still have its command scanned for protected paths and denylist patterns -- but the irreversible-requires-human gate and mode gating would be bypassed. Not on the known-findings list; the prior review only mentions the all-or-nothing irreversible gate.

### evidence

- simorgh/guardian/service.py:97-110 consumes tuple: ACTION_PROPOSED, GUARDIAN_REVIEW, SYSTEM_STATE_CHANGED, TASK_*, REFLECT_*, COGNITION_PROVIDER_STATUS, SYSTEM_RESUME, GUARDIAN_POSTURE_REQUEST, UI_PROMPT_ANSWERED -- no TOOL_REGISTERED
- grep -rn 'TOOL_REGISTERED|tool.registered|classify_call|reversibility_of' simorgh/guardian/ -> no output
- simorgh/guardian/service.py:504 reversibility=p["reversibility"]; :522-526 tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)
- simorgh/orchestration/tools.py:83 "run_shell": ("irreversible", True); :693 reversibility, network = _TOOL_POLICY.get(tool, ("irreversible", False))
- simorgh/orchestration/tools.py:635-636 `if name not in _TOOL_POLICY: _TOOL_POLICY[name] = ...` -- Execution's tool.registered declaration cannot override a static entry
- simorgh/guardian/rules.py:725-727 ReversibilityRule: `if r == "read_only": return Decision("allow", ...)`; :257-267 ModeRule uses `read_only = bool(ctx.tool and ctx.tool.read_only)`
- simorgh/guardian/config.py:21-41 DEFAULT_PROTECTED_SUBJECTS: guardian/, execution/, contracts/, kernel/, simorgh.toml, simloader.py, sim.sh -- no orchestration/; grep 'protected|orchestration' ~/.simorgh/simorgh.toml -> no output
- simorgh/execution/service.py:751-775 _on_approved: verifier.verify(approved, args, now) then dispatch; grep 'declared|mismatch|.reversibility' shows no cross-check of approved vs declared reversibility
- simorgh/contracts/home/policy.py:5-8 'so Guardian never has to trust a label the proposer supplied'
- Partial mitigation: simorgh/guardian/rules.py:116 _CODE_ARG_KEYS = ("code", "command"); :296-300 ProtectedRule does not exempt read_only tools when a code/command arg is present

**severity adjustment:** keep

**corrected claim:** Guardian builds ToolInfo solely from the proposal's reversibility field and never consumes tool.registered; that field comes from Orchestration's static _TOOL_POLICY table (which Execution's registration cannot override for builtins), and simorgh/orchestration/ is not a protected subject, so an approved reversible edit to that table can re-label run_shell as read_only and bypass ReversibilityRule's human gate and ModeRule's plan/autonomous gating. ProtectedRule still scans code/command arguments regardless of the label, so protected-path and denylist checks survive the re-label; the irreversible-requires-human gate does not.

