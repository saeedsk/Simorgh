# refute:correctness:Adaptive immunity never learns from shel

*Workflow: review · Phase: Refute · Agent id: `ae8ed91cd08312532` · Tool calls: 6*

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
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/service.py (from line 600) | 600 source="guardian", 601 )) 602 self._decided[action_id] = (fingerprint, True) 603 return 604 605 if verdict.kind == "needs_human": 606 question = approval_qu |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/rules.py (from line 330) | 330 return Decision( 331 "deny", self.layer, 332 (f"{path!r} is protected ({protected!r}); only the creator may edit it directly",), 333 ) 334 return Decision(" |
| 3 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/service.py (from line 195) | 195 self._lock_expiry = None 196 197 async def health(self) -> Health: 198 if self._degraded_detail: 199 return Health.degraded(self._degraded_detail) 200 retur |
| 4 | Bash | Verify remember_rejection callers, ImmunityRule, known findings, review callers | simorgh/guardian/service.py:510: rejected_similarity=self._rejected_similarity, simorgh/guardian/service.py:564: # append inside `_remember_rejection`, `approva |
| 5 | Bash | Check remember_rejection call site, review callers, and tests |  decided = {"kind": verdict.kind, "layer": verdict.layer} if verdict.notes: # What a rule noticed and chose not to act on -- shellcheck's # non-dangerous findin |
| 6 | Bash | Check review.py existence, immunity test, and live source of _remember_rejection | __init__.py __pycache__ api.py charter.py config.py pipeline.py posture.py README.md rules.py service.py tokens.py simorgh/guardian/service.py:641: def _rejecte |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** The core claim is true of the code today. `Service._remember_rejection` (simorgh/guardian/service.py:644-648) reads `proposal.args.get("code")` and returns early when absent, so a `run_shell`/`run_container`/`run_remote` proposal denied by protected/denylist/immunity (the only call site, service.py:586-587) never lands in `guardian:rejected` or `self._rejected_excerpts`. Meanwhile `ImmunityRule.evaluate` (rules.py:666-674) and `DenylistRule` (rules.py:376) both read `_code_text(proposal)`, which joins `_CODE_ARG_KEYS = ("code", "command")` (rules.py:116, 352-368). So the read side was widened to `command` on 2026-09-08 but the write side was not: a shell command can be matched by immunity only if something else already put its text in the index, which nothing does. The existing unit test `test_denies_a_rejected_commands_re_submission_via_run_shell` (tests/simorgh/guardian/test_rules.py:612-620) pre-seeds the excerpt list via a lambda, so it asserts the rule's shape and never exercises the service's remember path — exactly the "tests assert code shape" pattern the project already documents. This is not in the known-findings list (the audit/review docs mention "immunity" only as a layer name). The secondary claim about `_on_review` running only the denylist (service.py:226-236, `layers_run: ["denylist"]`) is factually correct, but the docstring (service.py:209-216) states it is "Deliberately narrow" and the only caller is Verification reviewing self-patch candidate bodies (simorgh/verification/service.py:298-299), not shell commands; so that half is a documented design choice, not an unconnected wire, and the recommendation to run protected/bandit there is a suggestion rather than a bug fix. One extra stale detail: `similarity`'s docstring says it is "Shared by ImmunityRule and review.py" but no review.py exists in simorgh/guardian/ (ls output: api, charter, config, pipeline, posture, rules, service, tokens). Severity stays low: the denylist still denies an identical re-submission on its own; immunity only adds fuzzy matching against re-worded attempts.

### evidence

- simorgh/guardian/service.py:644-648: `code = proposal.args.get("code")` / `if not isinstance(code, str) or not code: return` -- `command` is never consulted
- simorgh/guardian/service.py:586-587: `_remember_rejection` is the sole caller path, invoked only for layers protected/denylist/immunity
- simorgh/guardian/rules.py:116 `_CODE_ARG_KEYS = ("code", "command")`; rules.py:352-368 `_code_text` joins both; rules.py:671 `ImmunityRule.evaluate` uses `_code_text`
- grep `_code_text(` in service.py: zero hits (only rules.py:376 and :671) -- the remember side never adopted the shared helper
- tests/simorgh/guardian/test_rules.py:612-620: immunity/run_shell test seeds `rejected_similarity=lambda c: similarity(c, [command], 0.85)`, so the service's index population is untested
- simorgh/guardian/service.py:209-216 docstring: "Deliberately narrow: this answers 'does this code do something we forbid outright'"; :227 and :236 `layers_run: ["denylist"]`
- simorgh/verification/service.py:298-299: the only GUARDIAN_REVIEW publisher, sending a `code_ref` blob of candidate patch code
- docs/architecture-audit-2026.md / docs/architecture-review-2026-09-18.html: grep for immunity|remember_rejection|_on_review finds only the layer name in a list -- not previously reported

**severity adjustment:** keep

**corrected claim:** `_remember_rejection` (service.py:644-648) reads only `args["code"]`, so a denied `run_shell`/`run_container`/`run_remote` proposal (which carries `command`) is never written to the `guardian:rejected` stream or the in-memory excerpt list; `ImmunityRule` was widened to read `command` via `_code_text` (rules.py:352-368, 671) but the write side was not, so immunity cannot learn from shell denials and the unit test only proves the rule shape with a pre-seeded list. Separately, `_on_review` runs only the denylist (service.py:226-236), but this is documented as deliberate and serves Verification's self-patch review, not shell commands -- a design choice to reconsider rather than a bug.

