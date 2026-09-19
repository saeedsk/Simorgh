# refute:proportionality:Guardian enforces the reversibility labe

*Workflow: review · Phase: Refute · Agent id: `a5443e7a7b73afa19` · Tool calls: 9*

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
    "title": "Guardian enforces the reversibility label the proposer chose, and the interface labels everything 'reversible'",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "The tool layer's only safety export, the per-tool reversibility class, never reaches Guardian: Guardian builds ToolInfo from the proposal's own `reversibility` field, does not subscribe to tool.registered, and does not call contracts/home/policy.py, while interface/dispatch.py stamps every human- or dashboard-proposed call as 'reversible'.",
    "evidence": [
      "simorgh/guardian/service.py:522-526: `tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == \"read_only\", reversibility=proposal.reversibility)` - the declared class on the Tool object is never consulted",
      "simorgh/guardian/service.py:97-100: consumes = (ACTION_PROPOSED, GUARDIAN_REVIEW, SYSTEM_STATE_CHANGED, ...) - no TOOL_REGISTERED; `grep -rn \"classify_call\\|contracts.home\" simorgh/guardian/*.py` -> no output",
      "simorgh/interface/dispatch.py:1336: `\"reversibility\": \"reversible\"` with the comment 'Guardian recomputes the real class itself and never trusts a proposer's label' - which is not what guardian/service.py does",
      "simorgh/orchestration/tools.py (home_call comment): 'Guardian recomputes the same answer from the same pure function rather than trusting this' - also untrue",
      "Ledger, 5 action streams: `cam_siren interface:71b8cc9e-... reversibility= reversible args= {'camera': 'Pool', 'seconds': 1}` etc., while simorgh/execution/home/cameras.py declares cam_siren `reversibility = \"irreversible\"` (measured: 10 tools declare irreversible)",
      "simorgh/interface/httpapi.py:389-402: the dashboard's `_run_for_page` goes through the same `_run_tool` and therefore the same hard-coded label"
    ],
    "why_it_matters": "The three-tier taxonomy is maintained in three places across 98 tools, yet the component that acts on it sees a value the least trusted party supplies. A `tool home_call lock.unlock` typed at the CLI, or any tool the dashboard is later wired to, arrives as 'reversible' and is auto-allowed in guarded posture; the `human` class for locks and alarms in contracts/home/policy.py holds only when Orchestration is the proposer. Two docstrings assert the opposite of the code, so the next person will trust the label too.",
    "recommendation": "Have Execution hand Guardian the declared table once (Guardian subscribes to tool.registered, or Kernel passes the registry's {name: reversibility} at boot) and compute `effective = strongest(declared[tool], proposal.reversibility, classify_call(...) for home_call)` in guardian/service.py before building ToolInfo. Then delete the label from interface/dispatch.py and make `_TOOL_POLICY`'s reversibility column a test that asserts equality with the declared value rather than a second source. Half a day; one new test that proposes cam_siren from 'interface:x' with 'reversible' and expects the irreversible path.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read Guardian consumes list and ToolInfo construction |  question = question[:_QUESTION_MAX_CHARS - 1] + "…" return question class Service: name = "guardian" version = "0.1.0" consumes = ( topics.ACTION_PROPOSED, top |
| 2 | Bash | Grep Guardian for tool registry use; read dispatch label site and orchestration home_call comment | exit=1 ---- dispatch import asyncio args = cli_tool_args(tool, raw) if "__error__" in args: return Outcome(f"error: {args['__error__']}") # No secret rides in a |
| 3 | Bash | Inspect how Guardian rules and Execution use the reversibility field, and count declared irreversible tools | ---- rules using reversibility simorgh/guardian/api.py:25: reversibility: str simorgh/guardian/api.py:40: reversibility: str simorgh/guardian/config.py:103: irr |
| 4 | Bash | Read ReversibilityRule, ProtectedRule, execution token verification, cam_siren declaration, dashboard path, and ledger layout |  if status.fraction_used >= 1.0: return Decision("deny", self.layer, (f"{status.provider} budget exhausted for this window",)) return Decision("abstain", self.l |
| 5 | Bash | Check ledger for interface-proposed irreversible tools labelled reversible, Execution approval path, dispatch confirmation, and config mode | ---- ledger action streams cam_siren ---- ledger irreversible-declared tools proposed by interface with reversible label declared irreversible: ['cam_siren', 'o |
| 6 | Bash | Check auto-approve default, the dispatch approval-prompt comment, human class mapping, and who else consumes tool registration | ---- sim.sh ---- dispatch 1150-1175 return Outcome(f"ring: unknown verb {verb!r} -- {usage}") async def _tool_command(args: str, *, bus: BusClient, ledger: Ledg |
| 7 | Bash | Locate auto-approve env wiring, TOOL_REGISTERED consumers, classify_call callers, and related tests | ---- sim.sh auto approve simorgh/guardian/config.py:138: """`[guardian]` table -> Config, with a `SIMORGH_GUARDIAN_AUTO_APPROVE` simorgh/guardian/config.py:155: |
| 8 | Bash | Read home_call tool's own runtime classification and confirm sim.sh auto-approve default | ---- home tools 195-215 description = ( "Do something in the house: turn a light on, set the thermostat, pause the TV. Takes a " "Home Assistant service (light. |
| 9 | Bash | Confirm where auto-approve is set and whether home_call refuses on the human class |  # `sim.sh`'s own default, deliberately looser than `GuardianConfig`'s # own dataclass default (`irreversible_requires_human=True`, kept # safe for anyone const |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out against the code as it is today. Guardian's `consumes` tuple (simorgh/guardian/service.py:97-110) has no TOOL_REGISTERED; `grep -rn "classify_call\|contracts.home\|TOOL_REGISTERED" simorgh/guardian/*.py` exits 1 with no output; ToolInfo is built purely from `proposal.reversibility` (service.py:522-526) and ReversibilityRule decides on `proposal.reversibility` alone (rules.py:720-741). interface/dispatch.py:1333-1336 hard-codes `"reversibility": "reversible"` under a comment claiming Guardian recomputes it, and the `_tool_command` docstring at dispatch.py:1162 promises "an irreversible call still stops at the approval prompt", which is false for this path. The dashboard's `_run_for_page` (httpapi.py:392-402) funnels through the same `_run_tool` with session "dash". A ledger scan found 5 action streams where `cam_siren` (declared `reversibility = "irreversible"` at execution/home/cameras.py:686) was proposed by `interface:*` with label `reversible`. Execution does not backstop it either: `_on_approved` only verifies the HMAC token (execution/service.py:751-768), and `home_call` computes the `worst` class at run time but only stores it in result metadata rather than refusing (execution/home/tools.py:255-275). So the finding is a genuine right-design-undermined case, and the 'unconnected wire' shape the project already knows.

Skeptic lens on scale and proportion: the exposure is smaller than 'high' suggests. (1) Under the creator's actual running default, kernel/service.py:188-200 sets `irreversible_requires_human=False` (sim.sh auto-approve), so ReversibilityRule returns 'allow' for both labels; the label mismatch changes no decision today, and in 'locked' posture both labels are denied, so it only bites when the creator turns auto-approve off in guarded/normal mode. (2) For the CLI, the proposer IS the human; escalating a cam_siren the creator just typed back to the same terminal is a redundant prompt, so labelling terminal-typed calls as pre-approved is a defensible policy, if it were stated. The party actually widened is the dashboard HTTP endpoint, which is a different trust boundary. (3) Materially new: the `human` tier never reaches Guardian from any proposer, because `reversibility_of` collapses it to `irreversible` (contracts/home/policy.py:112-115), and Guardian has no notion of 'human' at all (grep "human" in guardian/ finds only `origin`). policy.py's docstring says `human` is "meant to survive" auto-approve; nothing implements that. So the three-tier taxonomy is already two-tier before this bug matters. The recommendation itself is proportionate: TOOL_REGISTERED already exists (contracts/topics.py:122) and worldmodel/service.py:113 and orchestration/service.py:104 already subscribe to it, so Guardian doing the same and taking strongest(declared, proposed) is a same-shape change of well under a day, and it removes two false docstrings.

### evidence

- simorgh/guardian/service.py:97-110 consumes = (ACTION_PROPOSED, GUARDIAN_REVIEW, SYSTEM_STATE_CHANGED, TASK_*, ..., UI_PROMPT_ANSWERED) -- no TOOL_REGISTERED
- simorgh/guardian/service.py:522-526 tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)
- grep -rn "classify_call\|contracts.home\|TOOL_REGISTERED\|tool.registered" simorgh/guardian/*.py -> no output, exit=1
- simorgh/guardian/rules.py:720-741 ReversibilityRule.evaluate reads r = proposal.reversibility only; irreversible -> escalate only if ctx.config.irreversible_requires_human
- simorgh/kernel/service.py:188-200 comment: sim.sh's running default is auto-approve (irreversible_requires_human=False), so today both labels yield 'allow'
- simorgh/interface/dispatch.py:1333-1336 '# The floor. Guardian recomputes the real class itself and never trusts a proposer's label' ... "reversibility": "reversible"
- simorgh/interface/dispatch.py:1162 docstring: 'an irreversible call still stops at the approval prompt' -- false for this path
- simorgh/orchestration/tools.py:698-702 comment 'Guardian recomputes the same answer from the same pure function' then reversibility_of(classify_call(...))
- simorgh/interface/httpapi.py:392-402 _run_for_page -> _run_tool(session_id="dash") -- same hard-coded label for the dashboard
- Ledger scan (python over ~/.simorgh/ledger/streams/action%3A*.jsonl): interface-proposed, declared-irreversible, labelled-reversible = {'cam_siren': 5}; simorgh/execution/home/cameras.py:686 reversibility = "irreversible"
- simorgh/execution/service.py:751-768 _on_approved verifies the token only; no declared-class check
- simorgh/execution/home/tools.py:255-263,275 home_call computes worst class per call but only emits it as metadata 'safety'; never refuses
- simorgh/contracts/home/policy.py:112-115 reversibility_of: 'human' maps to 'irreversible' -- Guardian has no distinct human tier; grep '"human"' simorgh/guardian/*.py hits only `origin` defaults
- simorgh/contracts/topics.py:122 TOOL_REGISTERED exists; simorgh/worldmodel/service.py:113 and simorgh/orchestration/service.py:104 already subscribe -- the recommended Guardian subscription is a same-shape change

**severity adjustment:** lower

**corrected claim:** Guardian trusts the proposer's reversibility label and never sees the tool's declared class; interface/dispatch.py (CLI and dashboard) labels everything 'reversible' under a docstring that claims the opposite. Under the shipped sim.sh auto-approve default this changes no decision today (irreversible is auto-allowed anyway, and 'locked' denies both), and for the CLI the proposer is the human, so the real widened boundary is the dashboard HTTP endpoint and any future non-auto-approve run. The deeper gap is that the `human` tier is collapsed to `irreversible` before Guardian ever sees it and Execution's own per-call classification is metadata-only, so no proposer gets the 'a person decides every time' behaviour policy.py promises.

