# refute:proportionality:Execution is a 21.6k-line God package ho

*Workflow: review · Phase: Refute · Agent id: `a06246d7d9cce2229` · Tool calls: 2*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Execution is a 21.6k-line God package holding five product domains, next to a retired 16k-line v1 tree and 11 GB of workspace in the repo",
    "kind": "over-engineering",
    "severity": "low",
    "claim": "Home, media, PIM, knowledge, security and energy (10.5k lines) live inside simorgh/execution rather than as domain packages behind the `extra_tools` seam the service already has, so the subsystem that must stay smallest and most trusted (it holds the HMAC verifier) is 25% of the code and 27% of the tests; src/ (v1) is still in the tree and imported by nothing.",
    "evidence": [
      "lines per package: execution 21,590 of 86,996 (24.8%); tests/simorgh/execution 15,098 of 90,203",
      "execution subdirs: home 2379, media 2252, pim 2087, knowledge 1995, security 1085, energy 686",
      "simorgh/execution/service.py:118-119 `extra_tools`/`connectors` injection seam already exists; :4-7 \"Registry and dispatch are kept in this one module for this build (the spec's registry.py/runner.py split is a natural follow-up once the tool count grows past what fits in one screenful)\" -- the count is now 104 classes",
      "du -sh src -> 2.4M, 16,441 Python lines; grep -rn 'from src\\|import src' simorgh tools simloader.py -> none",
      "du -sh workspace papers -> 11G, 109M inside the repository root"
    ],
    "why_it_matters": "Guardian's ProtectedRule keeps execution/ off-limits to self-patching, which means every house/media/PIM improvement Sim might make to itself is blocked because it shares a package with the token verifier. Splitting domains out makes them patchable and keeps the trusted core small.",
    "recommendation": "Move the six domain subpackages to simorgh/domains/<name> registered through `extra_tools` (or a `domains` layer in kernel/registry.py LAYERS), keeping only registry, verifier, sandboxes and worktree in execution; protect only that. Delete src/ (git history keeps it) and move workspace/ and papers/ out of the checkout the loader gates.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines per package and execution subdirs | simorgh/execution/ 21590 simorgh/voice/ 11233 simorgh/interface/ 10747 simorgh/contracts/ 6443 simorgh/orchestration/ 5600 simorgh/kernel/ 4045 simorgh/verifica |
| 2 | Bash | Inspect service.py seam, src imports, workspace sizes, gitignore | """Execution's Service (08-execution.md section 5): the only subsystem the Kernel/Bus enforcement lets subscribe to `action.approved`. Verifies every approval i |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

You've hit your session limit · resets 11:10pm (America/Los_Angeles)