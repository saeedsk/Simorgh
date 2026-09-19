# refute:correctness:The 2026-style loop features are built a

*Workflow: review · Phase: Refute · Agent id: `aacfd9bd350c9ee7a` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "The 2026-style loop features are built and all switched off by default",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "Re-grounding via progress note, parallel read-only tool batches, clean revisions, in-process delegation and strong-tier escalation are implemented in session.py but every one defaults off in config.py and the live simorgh.toml sets none of them, so production runs one tool per step with an unbounded transcript until Cognition raises context_too_large and a forced reground rescues it.",
    "evidence": [
      "simorgh/orchestration/config.py:60 `reground_every_steps: int = 0`, :64 `clean_revisions: bool = False`, :67 `delegation: bool = False`, :74 `parallel_read_tools: int = 1`, :77 `escalate_from_attempt: int = 0`, each annotated 'Off until its benchmark arm wins'",
      "simorgh/orchestration/session.py:898-907 the only reground in production is the forced one after a context_too_large error",
      "simorgh/orchestration/session.py:1425-1480 _delegate and :1385-1420 _read_batch/_run_batch exist and are tested (tests/simorgh/orchestration/test_delegate.py, test_parallel_reads.py, test_reground.py)",
      "~/.simorgh/simorgh.toml: no [orchestration] section"
    ],
    "why_it_matters": "State-of-the-art harnesses in 2026 are exactly these three things: compaction on a schedule, parallel independent tool calls, and bounded sub-agents with fresh context. Simorgh has them and runs without them, so its measured behaviour (steps burned, context blowups, cost) is that of a 2024 loop.",
    "recommendation": "Default reground_every_steps=8 and parallel_read_tools=4 for task profiles now (they are cheap and low-risk); enable delegation for research/patch; run the benchmark arm to tune, not to gate.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read orchestration config defaults |  session. """ from __future__ import annotations from dataclasses import dataclass @dataclass(frozen=True) class Config: workers: int = 1 # Whether Verification |
| 2 | Bash | Locate loop-feature references in session.py | 8:artifact assembly, no delegation (fresh/fork), no steer injection, no 9:reground-every-N-steps restatement. See the package README. 608: worktrees: bool = Fal |
| 3 | Bash | Check live toml and every other writer of these config keys | /Users/saeed/.simorgh/simorgh.toml exit=1 (eval):1: no matches found: --include=*.py |
| 4 | Bash | Find other writers of the keys, list toml sections, read the loop around reground | simorgh/cognition/parser.py:380: # parallel_read_tools`) needs their arguments. Which of them run is simorgh/contracts/messages/cognition.py:34: # parallel_read |
| 5 | Bash | Confirm tests exist, check prior reviews, see how orchestration config is built | test_delegate.py test_parallel_reads.py test_reground.py ---known findings mention?--- ---how config is loaded--- |
| 6 | Bash | Check env overrides, config loader and bench tools for these keys | ---sim.sh env--- 8:# fails, up to a cap. `SIMORGH_NO_LOADER=1` runs the package directly, 15:PYTHON_BIN="${SIMORGH_PYTHON:-python3}" 22:export SIMORGH_EXECUTION |
| 7 | Bash | Check for any other transcript bounding and the due() rule | ---transcript bounding in session.py--- 139:def _trim_evidence(text: str, limit: int) -> str: 144: truncated tail as the actual fact, rejecting an answer whose  |
| 8 | Bash | Check toml-to-Config mapping and per-result compaction that bounds the transcript | ---config loader--- (eval):1: no matches found: simorgh/config*.py ---session 1588-1605--- # the repo root came back so clipped that it concluded it was # worki |
| 9 | Bash | Check profile step caps, bench arm switch plumbing and any recorded benchmark results | ---profile step budgets--- 77: read_only=False, max_steps=20, max_revisions=0, scaffold="chat", verify=False, 129: read_only=False, max_steps=20, max_revisions= |
| 10 | Bash | Read what the recorded benchmark arm said about these features | 54-\| Change \| Switch \| Commit \| Status \| 55-\|---\|---\|---\|---\| 56:\| A. Progress note, re-grounding every N steps \| `reground_every_steps`, `keep_recent_steps` \|  |
| 11 | Bash | Check Cognition's own compaction layers that run before context_too_large |  # key "strong" is used when a request asks for `tier: "strong"` # (escalation). Empty = every purpose uses `provider_order`, as before. routes: Mapping[str, tu |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual core holds: all five switches default off in simorgh/orchestration/config.py, the live ~/.simorgh/simorgh.toml has no [orchestration] section (sections present: voice, interface, execution, cognition, cognition.providers, cognition.providers.ollama), the code paths exist in session.py (_read_batch :1404, _run_batch :1429, _delegate :1445, _reground :1520, scheduled call :891-892, forced call on context_too_large :912-917), and tests exist (test_delegate.py, test_parallel_reads.py, test_reground.py). The finding is not in the known list and prior review docs never mention reground/parallel_read/delegation. Two parts of the claim are wrong, though. (1) 'unbounded transcript until Cognition raises context_too_large' is false: Cognition runs a five-layer compaction pipeline before that error (cognition/compaction.py: L1 per-result cap at tool_result_max_tokens=2000, L2 snip at 90%, L3 microcompact at 95%, L4 collapse at 45%, L5 model summarization), session.py bounds every tool result to 8000 chars (_MODEL_RESULT_CHARS), and every task profile has a max_steps cap (20/14/8/20 in profiles.py). context_too_large is raised only when protected blocks alone exceed budget or all layers fail (cognition/service.py:299, :368). (2) 'switched off' is framed as an oversight, but the defaults are the outcome of a measured benchmark wave recorded in docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md: reground-every-6 (arm 22) and reground+clean (arm 23) scored within noise of baseline and roughly doubled 'step budget exhausted'; parallel reads (arm 25) halved L3 budget exhaustion but scored within noise; conclusion 'Keep A and B off'. The recommendation to set reground_every_steps=8 'now' contradicts the creator's own measurement (the doc suggests every 10, keep 4, if retried). What remains materially true and new: delegation is 'built; not yet in an arm' and escalation is 'partial', so two of the five features have never been measured at all; and the doc itself admits the arms were underpowered (identical-settings L3 runs swung 3/21 vs 9/25), so 'off until its arm wins' rests on a measurement that cannot rank the switches. That is a real critique, but it is a measurement-power problem, not a 2024-loop-by-neglect problem.

### evidence

- simorgh/orchestration/config.py:60 `reground_every_steps: int = 0`, :64 `clean_revisions: bool = False`, :67 `delegation: bool = False`, :71 `escalate_from_attempt: int = 0`, :74 `parallel_read_tools: int = 1` (read via sed -n 40,110p)
- `grep -n '^\[' ~/.simorgh/simorgh.toml` -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]; no [orchestration]
- simorgh/orchestration/session.py:891-892 scheduled reground gated by progress_note.due(...self._reground_every); :912-917 forced reground on last_think_error == 'context_too_large'; :1404 _read_batch, :1429 _run_batch, :1445 _delegate, :1520 _reground
- simorgh/orchestration/service.py:85-91 passes every switch from self.config into the worker; tools/bench_instance.py:129-134 and :255 orchestration_overrides() sets them only for benchmark arms (`--orch reground_every_steps=6`)
- tests/simorgh/orchestration/: test_delegate.py test_parallel_reads.py test_reground.py exist
- simorgh/cognition/config.py:114-118 tool_result_max_tokens=2000, snip_trigger_fraction=0.90, microcompact_trigger_fraction=0.95, collapse_trigger_fraction=0.45; simorgh/cognition/compaction.py:122-151 layers 1-5 applied before context_too_large; simorgh/cognition/service.py:299,:368 the only raise sites
- simorgh/orchestration/session.py:1597 `_MODEL_RESULT_CHARS = 8000` bounds every tool result before compaction; simorgh/orchestration/profiles.py:77,129,153,169,179 max_steps=20/20/14/8/20
- docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md:56-63 status table: A 'built; no gain measured', B 'built; no gain measured', C 'built; not yet in an arm', E 'partial', H 'built; arm 25 within noise, off'; :75-77 'Keep A and B off', 'step budget exhausted was roughly twice as frequent in arm 22', 'slices of 13-26 cases cannot rank these switches'
- grep -i 'reground|parallel_read|delegation' over docs/architecture-review-2026-09-18.html, docs/architecture-audit-2026.md, docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)

**severity adjustment:** lower

**corrected claim:** Scheduled re-grounding, clean revisions, in-process delegation, strong-tier escalation and parallel read-only batches are implemented and unit-tested in orchestration/session.py but all default off in orchestration/config.py and the live simorgh.toml sets none of them; production therefore runs one tool per step, relying on Cognition's five-layer compaction (per-result 2k-token cap, snip, microcompact, collapse, summarize) and profile max_steps to bound context, with a forced reground only after context_too_large. The off-defaults are a deliberate, documented decision from the 2026-09-15 benchmark wave (re-grounding every 6 steps doubled 'step budget exhausted' with no score gain; parallel reads within noise), not an oversight. The genuine gaps are that delegation and escalation were never put in any arm, and the arms that were run were too small to rank any switch (identical-settings runs swung 3/21 vs 9/25), so 'off until its benchmark arm wins' is gated on a measurement that cannot produce a winner.

