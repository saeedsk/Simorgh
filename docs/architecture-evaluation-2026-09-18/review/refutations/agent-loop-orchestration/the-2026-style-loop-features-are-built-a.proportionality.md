# refute:proportionality:The 2026-style loop features are built a

*Workflow: review · Phase: Refute · Agent id: `a65934f7a74cc710a` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "agent-loop-orchestration". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 2 | Bash | Locate feature flag uses in session.py | 8:artifact assembly, no delegation (fresh/fork), no steer injection, no 9:reground-every-N-steps restatement. See the package README. 608: worktrees: bool = Fal |
| 3 | Bash | Inspect live simorgh.toml sections | 1:[voice] 15:[interface] 18:[execution] 22:[cognition] 24:[cognition.providers] 26:[cognition.providers.ollama] ---orchestration section--- ---grep keys--- |
| 4 | Bash | Read reground/batch code and list tests |  while True: if self._paused(): return await self._pause(session) # Cooperative, and checked between steps rather than during # one: a cancel must not tear down |
| 5 | Bash | Check config wiring and whether benchmark arms were ever run | (eval):1: no matches found: --include=*.py --- findings/plans mentioning arms --- docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md docs/plans/long |
| 6 | Bash | Read benchmark arm results for the loop features | ## 2. What the 2026-09-14 wave showed - **The answer reviewer was not a net gain on benchmarks.** It rejected 111 correct and 111 wrong answers, and for researc |
| 7 | Bash | Check how toml reaches Config and find the baseline arm numbers | simorgh/cognition/parser.py:380: # parallel_read_tools`) needs their arguments. Which of them run is simorgh/contracts/messages/cognition.py:34: # parallel_read |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every factual line in the finding checks out: the five switches default off in simorgh/orchestration/config.py (reground_every_steps=0 :60, clean_revisions=False :64, delegation=False :67, escalate_from_attempt=0 :71, parallel_read_tools=1 :74), they are wired through service.py:85-91 -> worker.py:138-180 -> session.py:608-643 so a [orchestration] toml section would activate them, ~/.simorgh/simorgh.toml has no such section (sections present: voice, interface, execution, cognition, cognition.providers, cognition.providers.ollama), the scheduled reground at session.py:890-892 is dead when _reground_every is 0 so the only reground that fires in production is the forced one after context_too_large at :912-917, and _parallel_offer/_read_batch/_run_batch (:1399-1430) plus five test files (test_reground, test_parallel_reads, test_delegate, test_escalation, test_clean_retries) exist.

What the finding gets wrong is the interpretation, and that is the whole architectural point. The switches are not "built and forgotten"; they were benchmarked. docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md section 3 records wave w20260915-arms: baseline 7/26 GAIA-L3, 11/24 L2, 2/15 SWE-bench; reground-every-6 (arm 22) 7/26, 13/23, 2/12 with "step budget exhausted" roughly TWICE as frequent because writing a note every six steps spends steps; reground+clean (arm 23) 8/26, 9/20, 4/13; parallel reads=4 (arm 25) 9/25, 13/24, 3/13, with two identical-setting L3 runs giving 3/21 and 9/25, a swing bigger than any inter-arm gap. The creator's conclusion, "slices of 13-26 cases cannot rank these switches", is sound statistics, and "off until its arm wins" (config.py comment, findings doc: "Every change ships behind a switch, off until its arm wins") is a deliberate, evidence-driven policy, not an undermined design. The recommendation "default reground_every_steps=8 ... they are cheap and low-risk" is directly contradicted by the measured cost of re-grounding (doubled budget exhaustion, no accuracy gain). The parallel-reads half of the recommendation has some support (arm 25 halved L3 budget exhaustion 4->2) but the creator already noted that and chose to wait for repeated runs; on a one-developer, cost-frugal system with a keyless search engine that spaces batched searches 2 s apart anyway (findings doc section 4), the saving is model calls, not wall time, and flipping it on with the current noise would be guessing. The "context blowups" consequence is asserted, not shown: the arms record no context_too_large in 22/23 and the forced reground path exists precisely so a blowup is recovered rather than fatal. Net: this is not a "right design undermined by implementation" finding; it is a disagreement with a measurement-gated rollout policy that is, at this scale, the correct discipline. It should at most be a low note: the benchmark noise sizing (repeat baseline 3x) named as "next" in the findings doc has not been done yet, so the switches sit in limbo.

### evidence

- simorgh/orchestration/config.py:56-74: reground_every_steps=0, keep_recent_steps=2, clean_revisions=False, delegation=False, delegate_max_steps=12, escalate_from_attempt=0, parallel_read_tools=1; comments say '0 is off, the default until its benchmark arm wins (docs/plans/long-run-context-design.md)'
- simorgh/orchestration/service.py:85-91 passes config.reground_every_steps / escalate_from_attempt / parallel_read_tools into the worker; simorgh/orchestration/worker.py:138-180 forwards them; simorgh/orchestration/session.py:608-643 stores them (_parallel_reads, _escalate_from_attempt, _delegation, _clean_revisions, _reground_every) -- the toml wire exists, it is just unset
- grep -n '^\[' ~/.simorgh/simorgh.toml -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]; grep for reground|parallel_read|delegation|clean_revisions|escalate_from in the toml -> no matches
- simorgh/orchestration/session.py:890-892 scheduled reground guarded by progress_note.due(..., self._reground_every) -> never due at 0; :912-917 forced reground only on last_think_error == 'context_too_large'; :922 second failure returns Outcome('blocked', 'context too large for the model, even after re-grounding')
- simorgh/orchestration/session.py:1399-1430 _parallel_offer returns {} when _parallel_reads < 2; _read_batch returns [tool_calls[0]] alone in that case; _dropped_rule -> 'one tool call per message.'
- ls tests/simorgh/orchestration/ -> test_clean_retries.py test_delegate.py test_escalation.py test_parallel_reads.py test_reground.py
- docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md:52-78: arms table -- A reground 'built; no gain measured', B clean 'built; no gain measured', C delegate 'built; not yet in an arm', H parallel reads 'built; arm 25 within noise, off'; baseline 7/26, 11/24, 2/15 vs arm 22 7/26, 13/23, 2/12 vs arm 25 9/25, 13/24, 3/13; 'step budget exhausted was roughly twice as frequent in arm 22'; 'Its two L3 runs with identical settings gave 3/21 and 9/25 ... slices of 13-26 cases cannot rank these switches'
- docs/findings/2026-09-15-benchmarks-long-runs-models-skills.md:208: next step 'Size the benchmark's run-to-run noise (repeat the baseline 3 times on the same slices) before judging any switch' -- not yet done as of 2026-09-18 (no later findings doc mentions these switches)

**corrected claim:** Re-grounding, clean revisions, delegation, strong-tier escalation and parallel read-only tool batches are implemented in session.py, wired through service.py/worker.py, unit-tested, and all default off in config.py; the live ~/.simorgh/simorgh.toml has no [orchestration] section, so production runs one tool per step and only re-grounds after a context_too_large error. This is a deliberate measurement-gated policy, not an oversight: a benchmark wave on 2026-09-15 found re-grounding every 6 steps gave no accuracy gain and roughly doubled 'step budget exhausted', clean revisions gave no gain, parallel reads landed within run-to-run noise (though it halved budget exhaustion on GAIA L3), and delegation has not been in an arm at all. The real open item is that the noise-sizing runs the creator named as prerequisite (baseline repeated 3x) have not been done, so the switches are stuck in limbo rather than wrongly off.

**severity adjustment:** lower

