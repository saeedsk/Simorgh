# refute:proportionality:Adaptive immunity never learns from shel

*Workflow: review · Phase: Refute · Agent id: `a96dec87a5a18e203` · Tool calls: 11*

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
    "title": "Adaptive immunity never learns from shell or command rejections",
    "kind": "bug",
    "severity": "low",
    "claim": "`_remember_rejection` reads only `args[\"code\"]`, so a denied `run_shell`/`run_container`/`run_remote` proposal (which carry `command`) is never added to the rejected index, and ImmunityRule can never match a re-worded shell attempt; the `guardian.review` path also runs only the denylist.",
    "evidence": [
      "simorgh/guardian/service.py:644-648 `code = proposal.args.get(\"code\")`; `if not isinstance(code, str) or not code: return`",
      "simorgh/guardian/rules.py:352-368 `_code_text` was fixed to join `code` and `command` for the rules, but the remember side was not",
      "simorgh/guardian/service.py:208-237 `_on_review` -> `layers_run: [\"denylist\"]`"
    ],
    "why_it_matters": "Same 'one side implemented' shape the project already names as its dominant bug; the immunity feature is half-wired for the most dangerous tool.",
    "recommendation": "Use `rule_defs._code_text(proposal)` in `_remember_rejection` and run the full pipeline's static rules (protected, denylist, bandit) in `_on_review`.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/service.py (from line 195) | 195 self._lock_expiry = None 196 197 async def health(self) -> Health: 198 if self._degraded_detail: 199 return Health.degraded(self._degraded_detail) 200 retur |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/service.py (from line 600) | 600 source="guardian", 601 )) 602 self._decided[action_id] = (fingerprint, True) 603 return 604 605 if verdict.kind == "needs_human": 606 question = approval_qu |
| 3 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/rules.py (from line 330) | 330 return Decision( 331 "deny", self.layer, 332 (f"{path!r} is protected ({protected!r}); only the creator may edit it directly",), 333 ) 334 return Decision(" |
| 4 | Bash | Locate immunity rule, remember call sites, and review consumers | 116:_CODE_ARG_KEYS = ("code", "command") 117- 118- 119:def _code_arg_text(value: object) -> str \| None: 120- """A `code`/`command` argument as a single program  |
| 5 | Bash | Read ImmunityRule, deny path, review consumers, similarity function | class ImmunityRule: name = "immunity" layer = "immunity" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: code = _code_text(propo |
| 6 | Bash | Confirm shell arg name, review consumer kind, and reproduce the asymmetry | (eval):1: no matches found: simorgh/execution/tools/*.py --- ) # request_or_error: a timeout (Cognition not built yet, or genuinely # down) comes back as the se |
| 7 | Bash | Read the immunity test, check rejected-stream tests and live ledger contents |  decision = await _evaluate(ImmunityRule(), _proposal(args={"code": "anything"}), ctx) self.assertEqual(decision.kind, "abstain") async def test_abstains_when_n |
| 8 | Bash | Inspect live guardian rejected stream and denial counts by layer | guardian%3Arejected.jsonl guardian%3Atrust.jsonl file=/Users/saeed/.simorgh/ledger/streams/guardian%3Arejected.jsonl 16 /Users/saeed/.simorgh/ledger/streams/gua |
| 9 | Bash | Count live denials by tool, layer and which code arg key they carried | 4:approval, and records the full decision on `action:<action_id>` plus 340: await self._tighten("guarded", f"{p['provider']} budget at {fraction:.0%} of window  |
| 10 | Bash | Recount live denials with the correct proposal event type |  action_id = p.get("prompt_id", "") if not action_id: return stream = f"action:{action_id}" events = await self._ctx.ledger.read(stream) received = next((e for  |
| 11 | Bash | Show a received event's shape and recount denials by tool and arg key | {"causation_id": null, "idempotency_key": null, "payload": {"proposal": {"action_id": "68905643c244", "args": {"code": "import subprocess, shutil, tempfile, wav |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core claim is CONFIRMED against code and against the live ledger. `_remember_rejection` (simorgh/guardian/service.py:644-648) reads only `proposal.args.get("code")` and returns early otherwise, while the rules side (`_code_text`, rules.py:352-368, `_CODE_ARG_KEYS = ("code", "command")` at rules.py:116) was widened to `command` on 2026-09-08/09 and has a unit test for immunity matching a `run_shell` command (tests/simorgh/guardian/test_rules.py:612-620). That test passes only because it injects the rejected excerpt directly via `rejected_similarity=lambda c: similarity(c, [command], 0.85)`; nothing tests that the service ever writes such an excerpt. The live ledger proves the gap: across 26,738 `action:*` streams, 26 denials came from the two layers that call `_remember_rejection` (protected/denylist), 16 carried `code` and 10 carried `command` (8 run_shell/protected, 1 run_shell/denylist, 1 run_container/denylist). The `guardian:rejected` stream holds exactly 16 events, all with `code_excerpt` — the 10 shell denials were dropped. So this is a genuine (c) bug of the project's named "one side implemented" shape, and the one-line fix (`code = rule_defs._code_text(proposal)`) is proportionate.

The second half is overstated. `_on_review` running only the denylist is documented as deliberate (service.py:211-215: "Deliberately narrow: this answers 'does this code do something we forbid outright'"), and its only caller is Verification's pre-check on self_patch/skill bodies (verification/service.py:46-50, 296-299), i.e. Python source blobs, not shell commands — so it has no bearing on the shell-immunity gap. The eventual `apply_source_patch` action still goes through the full pipeline (protected, denylist, immunity, static analysis). Adding bandit/protected to review would be a second copy of the gate at a pre-check point; at one-laptop scale that is extra work for little gain and belongs, at most, as a design note, not a bug. Severity stays low: the shell denials that were missed are already denied every time by the static rules; immunity only adds fuzzy re-wording protection.

### evidence

- simorgh/guardian/service.py:644-648 — `code = proposal.args.get("code")`; `if not isinstance(code, str) or not code: return` (only `code`, never `command`)
- simorgh/guardian/service.py:586-587 — `_remember_rejection` is called for verdict.layer in ("protected", "denylist", "immunity") regardless of tool
- simorgh/guardian/rules.py:116 `_CODE_ARG_KEYS = ("code", "command")`; rules.py:352-368 `_code_text` joins both keys; rules.py:666-681 `ImmunityRule` uses `_code_text`
- tests/simorgh/guardian/test_rules.py:612-620 — immunity-vs-run_shell test passes only by injecting the excerpt through a lambda; no test covers the service-side remember
- Live ledger scan (python over ~/.simorgh/ledger/streams/action*.jsonl): denied by (tool, layer, code-key): run_script/denylist/code 10; run_shell/protected/command 8; run_shell/denylist/command 1; run_container/denylist/command 1; replace_in_file, apply_source_patch, run_python_sandboxed, run_script/protected with `code` 6 -> 16 `code` denials, 10 `command` denials
- ~/.simorgh/ledger/streams/guardian%3Arejected.jsonl: `wc -l` = 16; Counter({('rejected','denylist','action'): 13, ('rejected','protected','action'): 3}) — exactly the 16 code-carrying denials, none of the 10 command-carrying ones
- simorgh/guardian/service.py:208-237 `_on_review` docstring: 'The same denylist that guards a live apply_source_patch, run over the candidate ahead of time. Deliberately narrow'; `layers_run: ["denylist"]`
- simorgh/verification/service.py:46-50 `_guardian_kind` maps every kind to self_patch|skill; :296-299 the sole GUARDIAN_REVIEW sender, sending a `text/x-python` blob — review never sees shell commands

**severity adjustment:** keep

**corrected claim:** `_remember_rejection` (guardian/service.py:644-648) reads only `args["code"]`, so denied `run_shell`/`run_container` proposals (which carry `command`) are never written to the `guardian:rejected` stream; the live ledger shows 10 such denials dropped versus 16 code-carrying ones remembered, so `ImmunityRule` can never match a re-worded shell attempt despite the rules side having been widened to `command`. This is a genuine one-line bug (use `rule_defs._code_text(proposal)`), low severity because the static rules still deny each attempt. The separate observation that `guardian.review` runs only the denylist is documented as deliberate, applies only to Verification's Python self-patch/skill pre-check (never shell), and the real apply action still passes the full pipeline — widening it is a design preference, not a defect.

