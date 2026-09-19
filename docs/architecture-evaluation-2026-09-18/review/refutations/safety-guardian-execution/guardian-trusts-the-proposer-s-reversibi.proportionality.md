# refute:proportionality:Guardian trusts the proposer's reversibi

*Workflow: review · Phase: Refute · Agent id: `aa89e7f349a49e131` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "safety-guardian-execution". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Show Guardian consumes list and ToolInfo construction |  question = question[:_QUESTION_MAX_CHARS - 1] + "…" return question class Service: name = "guardian" version = "0.1.0" consumes = ( topics.ACTION_PROPOSED, top |
| 2 | Bash | Show tool policy table, protected subjects, home policy intent, TOOL_REGISTERED consumers |  # one slow MCP server -- the intersection would drop every builtin # from every later session, leaving a patch session with no # read_file (observer, 2026-09-0 |
| 3 | Bash | Check who consumes tool.registered, Guardian home recompute, name-based rules, Execution reversibility | simorgh/contracts/messages/tool.py:10:ToolRegistered = define(t.TOOL_REGISTERED, [ simorgh/worldmodel/service.py:47: topics.TOOL_REGISTERED, topics.TOOL_UNAVAIL |
| 4 | Bash | List rules, where read_only/reversibility is used, protected subjects config | 42:def _existing_text(subject: str) -> str \| None: 62:def _added_or_changed_lines(old: str, new: str) -> str: 119:def _code_arg_text(value: object) -> str \| Non |
| 5 | Bash | Read ModeRule, ProtectedRule, ReversibilityRule bodies | class ModeRule: name = "mode" layer = "mode" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: effective_mode = ctx.config.mode #  |
| 6 | Bash | Check which rules depend on label, Execution runtime checks, tests, live config | 116:_CODE_ARG_KEYS = ("code", "command") 117- 118- 119-def _code_arg_text(value: object) -> str \| None: ---- rules gating on read_only 257: read_only = bool(ctx |
| 7 | Bash | Check live Guardian mode, tests guarding the table, Execution write-time protection, landing gate | Exit code 1 ---- guardian config defaults 84: mode: str = "guarded" # observe \| plan \| guarded \| trusted \| locked 103: irreversible_requires_human: bool = True  |
| 8 | Bash | Check live config, auto-approve source, tests pinning labels, home_call path, Execution runtime verification | ---- live toml 27:model = "qwen3:4b-instruct" ---- auto approve source simorgh/kernel/registry.py:106: `SIMORGH_GUARDIAN_AUTO_APPROVE` docstring), the same simo |
| 9 | Bash | Check the tests that pin the policy table, the auto-approve default, and the landing gate |  for tool in knowledge_tools(Config()): with self.subTest(tool=tool.name): self.assertIn(tool.name, _TOOL_POLICY) self.assertIn(tool.name, _ACTION_TIMEOUTS) sel |
| 10 | Bash | Check whether builtin tool labels are pinned by tests and whether registration can override the table | Exit code 1 tests/simorgh/orchestration/test_tools_router.py:544: self.assertEqual(_TOOL_POLICY[tool.name][0], tool.reversibility) tests/simorgh/orchestration/t |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The cited facts check out: Guardian's `consumes` has no TOOL_REGISTERED (guardian/service.py:97-110; the only subscribers are worldmodel and orchestration), `ToolInfo` is built from `proposal.reversibility` (service.py:522-526), the label comes from Orchestration's `_TOOL_POLICY.get(tool, ("irreversible", False))` (orchestration/tools.py:693), `simorgh/orchestration/` is not in DEFAULT_PROTECTED_SUBJECTS (guardian/config.py:21-41), and there is no `classify_call` anywhere under simorgh/guardian/, so the comment at orchestration/tools.py:696-697 ("Guardian recomputes the same answer ... rather than trusting this") and contracts/home/policy.py:5-8 describe an intent nobody wired -- a genuine unconnected wire for `home_call`.

But the finding overstates what the label controls. Only two rules read it: `ModeRule` (rules.py:257, plan mode and locked posture) and `ReversibilityRule` (rules.py:725-740, read_only -> allow, irreversible -> escalate). `grep -n "ctx.tool" simorgh/guardian/rules.py` hits only lines 257 and 298. `ProtectedRule` explicitly refuses to honour `read_only` for any proposal carrying a `code`/`command` argument (rules.py:116 `_CODE_ARG_KEYS = ("code","command")`, rules.py:286-300), and Denylist, Shellcheck, Scope, StaticAnalysis, Package, Grant, Immunity and Budget key on args, never on the label. So a `run_shell` relabelled read_only still gets the protected-path scan, denylist, shellcheck and scope checks; the relabel only buys (a) skipping the irreversible->human escalation and (b) passing in plan mode/locked posture. And (a) is already moot in the running system: kernel/service.py:188-200 sets `irreversible_requires_human=False` as sim.sh's baseline and ~/.simorgh/simorgh.toml has no [guardian] override (`grep -n "guardian\|irreversible" ~/.simorgh/simorgh.toml` returns nothing). The design already anticipates untrusted labels -- the substantive rules were deliberately written to not need them.

The self-patch path is also less open than claimed: the unit gate (which worktree landing runs over the whole suite, execution/worktree.py:24,96-102, and simloader re-runs) pins `_TOOL_POLICY[tool.name][0] == tool.reversibility` against Execution's own declarations for four tool families (tests/simorgh/orchestration/test_tools_router.py:544, 616, 688, 729). The residual gap is that the static builtin rows (`run_shell` at tools.py:83, replace_in_file, git_commit ...) are not pinned by such a test.

On the trust-boundary argument: Guardian already takes `tool` and `args` from the same unprotected proposer (service.py:504); the label is one more field from the same source, and the pipeline's answer is to judge the args. Adding orchestration/ and profiles.py to the protected list would freeze the very layer the corrigibility design says must remain evolvable (guardian/config.py:17-20), which is disproportionate for one laptop and one developer. Subscribing Guardian to tool.registered is cheap but introduces a registration-ordering/replay dependency for something two rules use; a ~10-line test pinning every builtin row to the execution registry, plus a Guardian-side `classify_call` for `home_call`, closes the real gaps with less machinery.

### evidence

- simorgh/guardian/service.py:97-110 -- consumes tuple has no TOOL_REGISTERED; `grep -rn TOOL_REGISTERED simorgh` shows only execution (producer), worldmodel:47,113 and orchestration/service.py:36,104 as consumers
- simorgh/guardian/service.py:504,522-526 -- Proposal built from p["tool"], p["args"], p["reversibility"]; ToolInfo(read_only=proposal.reversibility == "read_only")
- simorgh/orchestration/tools.py:83 `"run_shell": ("irreversible", True)`; :693 `_TOOL_POLICY.get(tool, ("irreversible", False))`; :696-697 comment claims Guardian recomputes home_call -- `grep -rn classify_call simorgh/guardian` returns nothing
- simorgh/guardian/config.py:21-41 DEFAULT_PROTECTED_SUBJECTS lists guardian/, execution/, contracts/, kernel/, simloader.py, sim.sh; not orchestration/
- simorgh/guardian/rules.py:257 and :298 are the only reads of ctx.tool; rules.py:116 `_CODE_ARG_KEYS = ("code", "command")` and :286-300 ProtectedRule never exempts code/command payloads on read_only
- simorgh/guardian/rules.py:720-740 ReversibilityRule: read_only->allow, reversible->allow (deny if locked), irreversible->escalate only if irreversible_requires_human
- simorgh/kernel/service.py:188-200 -- sim.sh baseline sets irreversible_requires_human=False (auto-approve default); `grep -n "guardian\|irreversible" ~/.simorgh/simorgh.toml` -> no [guardian] section
- tests/simorgh/orchestration/test_tools_router.py:544,616,688,729 -- assertEqual(_TOOL_POLICY[tool.name][0], tool.reversibility) for knowledge/pim/security/other families; no equivalent assertion for the static builtin rows (run_shell, replace_in_file, git_commit)
- simorgh/execution/worktree.py:24,96-102 -- landing runs `gate` (the whole suite) in a copy before fast-forwarding
- simorgh/orchestration/tools.py:632-635 register_tool_policy only fills _TOOL_POLICY when the name is absent, so Execution's registered label never overrides a static row

**severity adjustment:** lower

**corrected claim:** Guardian does take the reversibility label from the proposal (service.py:522-526) and never recomputes `home_call`'s class with `classify_call`, contrary to the comment at orchestration/tools.py:696-697 and the intent in contracts/home/policy.py:5-8 -- that is a real unconnected wire. But the label only feeds ModeRule (plan mode / locked posture) and ReversibilityRule (irreversible escalation); ProtectedRule deliberately ignores read_only for code/command payloads and every other rule keys on args, so a relabelled `run_shell` is still scanned for protected paths, denylist patterns and shellcheck findings. In the live sim.sh configuration irreversible actions are auto-approved anyway, so the escalation the label could bypass is already off. The gate pins policy labels to Execution's declarations for four tool families but not the static builtin rows. Fix: a Guardian-side `classify_call` for home_call and one test pinning the builtin rows of `_TOOL_POLICY` to the Execution registry; protecting orchestration/ or adding a tool.registered subscription is disproportionate for this scale and would freeze the layer meant to evolve.

