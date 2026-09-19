# refute:correctness:Guardian enforces the reversibility labe

*Workflow: review · Phase: Refute · Agent id: `a5c49a8b26f9ae6e9` · Tool calls: 8*

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
| 1 | Bash | Read Guardian consumes list and ToolInfo construction |  parts = [_preview_arg(str(name), value) for name, value in (args or {}).items()] detail = ", ".join(parts) why = "; ".join(reasons or ()) question = f"Approve  |
| 2 | Bash | Verify guardian greps, dispatch label, tool comments, cameras class, httpapi | == grep classify_call/contracts.home/TOOL_REGISTERED in guardian == simorgh/guardian/rules.py:122: future tool's -- is declared `["array", "string"]` and the to |
| 3 | Bash | Check rules, execution re-check, topic, and prior reviews | == rules.py reversibility uses == 132: reached `needs_human` (reversibility only) with no denylist reason 168:# in free-form code denies the call: without this, |
| 4 | Bash | Read reversibility rule, token check, name rules, home policy | == ReversibilityRule == if status.fraction_used >= 1.0: return Decision("deny", self.layer, (f"{status.provider} budget exhausted for this window",)) return Dec |
| 5 | Bash | Check token verifier, execution verify path, ledger evidence, tests | == tokens.py verify fields == 18: def issue(self, action_id: str, tool: str, args: dict, *, ttl_s: float \| None = None) -> tuple[str, float, str]: 22: token = s |
| 6 | Bash | Confirm ledger evidence and absence of Execution re-check | == action streams with cam_siren == 0 file: == all interface-proposed cam_siren labels == == execution post-verify reversibility check == (none) == lock/unlock  |
| 7 | Bash | Find action stream naming and cam_siren records | 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian action%3A00058d0478bb.jsonl action%3A00069b23741 |
| 8 | Bash | Print proposer and label for cam_siren and home_call proposals | action%3A7422804c0982.jsonl \| proposed_by= interface:71b8cc9e-4ff2-4a88-9876-f072e1bcc4c4 \| reversibility= reversible \| args= {'camera': 'Office', 'seconds': 1} |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every load-bearing citation is true of the code today. Guardian builds ToolInfo solely from the proposal's own `reversibility` string (simorgh/guardian/service.py:522-526), and the final ReversibilityRule (simorgh/guardian/rules.py:721-740) branches on `proposal.reversibility` directly; ModeRule's `read_only` (rules.py:257) comes from the same proposer-supplied field. Guardian's `consumes` tuple (service.py:97-109) has no TOOL_REGISTERED, and no file in simorgh/guardian/ references classify_call, contracts.home, or a declared-class table. Execution's `_on_approved` (simorgh/execution/service.py:751-790+) verifies only the HMAC over (action_id, tool, args_sha256, expiry) via tokens.py:18-22 and never compares the approved label against `tool.reversibility` from its own registry, so nothing downstream repairs the label either. interface/dispatch.py:1333-1336 hard-codes `"reversibility": "reversible"` with a comment asserting Guardian recomputes it, and httpapi.py:392-402 routes dashboard calls through the same `_run_tool`. The only proposer that does compute an honest class is Orchestration (orchestration/tools.py:693-716 uses `_TOOL_POLICY`, fed by `register_tool_policy` from tool.registered, and classify_call for home_call), but its comment at 698-699 ("Guardian recomputes the same answer") is also false. The ledger confirms the effect: three action streams show `cam_siren` proposed by `interface:71b8cc9e-...` with `reversibility=reversible`, while simorgh/execution/home/cameras.py:684-686 declares `cam_siren` `reversibility = "irreversible"`. This is not in the known-findings list; prior reviews discuss the binary `irreversible_requires_human` flag, not that the class Guardian gates on is chosen by the proposer. Minor evidence discrepancies (I found 3 action streams, not 5; 13 `irreversible` declarations under simorgh/execution, not 10) do not affect the claim. One mitigating note for severity: with sim.sh's auto-approve default (`irreversible_requires_human=false`) an irreversible label would also be allowed in guarded posture, so today's practical exposure is the loss of the human prompt whenever prompts are re-enabled, plus `mode=locked` still denies 'reversible' correctly. The design intent (Guardian recomputes; proposer label is a floor) is right, the implementation and two docstrings contradict it, so 'right-design-undermined' is the correct kind.

### evidence

- simorgh/guardian/service.py:522-526: `tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)` -- built from the proposal payload `p["reversibility"]` (line 504), no registry lookup
- simorgh/guardian/service.py:97-109: consumes = (ACTION_PROPOSED, GUARDIAN_REVIEW, SYSTEM_STATE_CHANGED, TASK_CREATED, TASK_COMPLETED, TASK_FAILED, REFLECT_DRIFT_DETECTED, REFLECT_HEALTH_FINDING, COGNITION_PROVIDER_STATUS, SYSTEM_RESUME, GUARDIAN_POSTURE_REQUEST, UI_PROMPT_ANSWERED) -- no TOOL_REGISTERED, though topics.py:122 defines it and execution/service.py:168,448,593,656 publish it
- `grep -rn "classify_call\|contracts.home\|TOOL_REGISTERED\|tool.registered" simorgh/guardian/*.py` -> no matches (only unrelated uses of the word 'declared' in comments)
- simorgh/guardian/rules.py:724-740 ReversibilityRule: `r = proposal.reversibility` ... `if r == "reversible": ... return Decision("allow")` in every mode but locked; the escalate-to-human branch is reached only when r is irreversible
- simorgh/guardian/rules.py:257: `read_only = bool(ctx.tool and ctx.tool.read_only)` -- ModeRule also reads the proposer-derived ToolInfo
- simorgh/interface/dispatch.py:1333-1336: comment 'Guardian recomputes the real class itself and never trusts a proposer's label' followed by `"reversibility": "reversible"`, `"proposed_by": f"interface:{session_id}"`
- simorgh/interface/httpapi.py:392-402: `_run_for_page` imports `_run_tool` from dispatch and calls it with session_id="dash" -- same hard-coded label
- simorgh/orchestration/tools.py:693-716: Orchestration's proposer does use `_TOOL_POLICY.get(tool, ("irreversible", False))` and `classify_call`/`reversibility_of` for home_call, but the comment at 698-699 'Guardian recomputes the same answer from the same pure function rather than trusting this' is false
- simorgh/execution/service.py:751-790: `_on_approved` calls `self._verifier.verify(approved, args, now=now)` (HMAC over action_id/tool/args hash/expiry per guardian/tokens.py:18-22) then fetches `tool = self._registry.get(approved["tool"])`; `grep` of lines 790-860 for reversib/read_only -> none, so the declared class is never compared to the approved label
- simorgh/execution/home/cameras.py:684-686: `name = "cam_siren"` ... `reversibility = "irreversible"`; `grep -rn 'reversibility = "irreversible"' simorgh/execution | wc -l` -> 13
- Ledger ~/.simorgh/ledger/streams: action%3A7422804c0982.jsonl, action%3A57079a1997fa.jsonl, action%3A944033b339ef.jsonl each record tool=cam_siren proposed_by=interface:71b8cc9e-4ff2-4a88-9876-f072e1bcc4c4 reversibility=reversible (args e.g. {'camera': 'Office', 'seconds': 1})
- Known-findings check: docs/architecture-audit-2026.md:61, docs/architecture-third-opinion-2026-09-18.md:73,175 and docs/architecture-review-2026-09-18.html:155-160 discuss only the binary irreversible_requires_human flag, not a proposer-chosen class; `grep -rn "reversible.*interface\|interface.*reversib" tests/simorgh/` -> no test covers this path

**severity adjustment:** keep

**corrected claim:** Minor corrections only: three (not five) action streams in the live ledger carry an interface-proposed cam_siren labelled 'reversible', and 13 (not 10) tools under simorgh/execution declare 'irreversible'. Also worth stating: with sim.sh's current auto-approve default the practical difference today is nil (irreversible is allowed anyway in guarded mode), and 'locked' posture still denies 'reversible', so the hole is the lost human prompt whenever irreversible_requires_human is re-enabled, on every interface/dashboard-proposed call.

