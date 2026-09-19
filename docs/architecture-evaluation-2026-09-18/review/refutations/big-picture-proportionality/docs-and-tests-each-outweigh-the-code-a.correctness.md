# refute:correctness:Docs and tests each outweigh the code, a

*Workflow: review · Phase: Refute · Agent id: `a9245511eca56d661` · Tool calls: 4*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Docs and tests each outweigh the code, and both certify shape rather than the loop",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "26,150 lines of Markdown, 9,095 of them blueprint specs written before the subsystems ran, plus a test suite larger than the code (90k vs 87k lines, 447 files, 33 kernel-booting integration tests) and 28.5% prose inside the source, coexist with the two critical wires above being unasserted -- the volume is a symptom of specifying and narrating instead of driving the one flow that matters.",
    "evidence": [
      "find docs -name '*.md' | xargs cat | wc -l -> 26150; EVOLUTION.md 5254; blueprint 9095 across 8 top docs + 17 subsystem specs; docs/plans 5923; READMEs inside simorgh/ 1357",
      "tests: 90,203 lines / 447 test files; integration: 44 files, 33 construct a Kernel",
      "in-code prose: \"code=54320 docstring=11751 comment=9906 ... prose share=28.5%\"",
      "git rev-list --count HEAD -> 856 commits between 2026-09-03 and 2026-09-18 (16 days)",
      "docs/blueprint/07-post-cutover-review.md:310-330 diagnosed exactly this on 2026-09-06 (\"No seam tests ... 'built on both sides, connected on neither' is invisible\"); finding 1 shows the same shape survived 12 more days and ~600 commits",
      "tests/simorgh/learning/test_service.py:5-51 -- a test that pins the broken wiring as expected behaviour"
    ],
    "why_it_matters": "For a one-person project the docs:code:tests ratio is a maintenance liability on its own (every self-patch has to keep 26k lines of prose true), but the deeper cost is that certainty is being manufactured in the wrong place: the system reads as thoroughly verified while its purpose is unverified.",
    "recommendation": "Freeze EVOLUTION.md (docs/findings/ already exists for dated results) and collapse each subsystem spec to a one-page contract of topics in / topics out / streams owned. Write three end-to-end assertions that drive real subsystems with only the provider faked: (1) a landed patch appears in SELF.md change history, (2) a chat turn adds no `unknown` competence row, (3) a dashboard steady state creates no action streams. Let those three replace a proportional amount of shape-level unit tests.",
    "confidence": 0.75
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count docs, code, test lines and commits | --- docs md lines 26249 --- EVOLUTION 5254 docs/EVOLUTION.md --- blueprint 9095 25 --- plans 5923 --- READMEs inside simorgh/ 1357 --- simorgh py 86996 --- test |
| 2 | Bash | Measure prose share and read cited doc and test lines | --- prose share code=54327 docstring=12891 comment=9899 prose share=29.6% --- 07-post-cutover 305-335 truthfully from a line that could never change (`06-worldm |
| 3 | Bash | Check blueprint dating and whether recommended end-to-end assertions exist | --- first commit touching blueprint / subsystems docs/blueprint: 2026-09-06 4be0852 simorgh/kernel: 2026-09-06 c5ceea7 simorgh/learning: 2026-09-06 f865464 simo |
| 4 | Bash | Check early git history and what seam-level integration tests assert | --- commits 09-03..09-05 2026-09-06 Free MCP servers, real simorgh.toml wiring, and a debug-notice leak fix 2026-09-06 Add MCP client support, with one server w |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

You've hit your session limit · resets 11:10pm (America/Los_Angeles)