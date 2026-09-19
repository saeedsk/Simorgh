# refute:proportionality:Three deployment modes and seven backend

*Workflow: review · Phase: Refute · Agent id: `abb74e1e85b4669ce` · Tool calls: 7*

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
    "title": "Three deployment modes and seven backends for a system whose only deployment is one process on one laptop",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "aws/dynamodb backends, the WorkerKernel/local-multi mode, a schema-version translator registry with no translators, and a JSON-schema projection of 174 message types are all built, tested and documented, and none is in force or on the roadmap the creator is actually executing.",
    "evidence": [
      "ls simorgh/bus/backends -> aws.py (269 lines), memory.py, sqlite.py; ls simorgh/ledger/backends -> dynamodb.py (282), jsonl.py, memory.py, sqlite.py",
      "cat ~/.simorgh/simorgh.toml -> no [bus], [ledger] or [runtime] section; bus/config.py:30 `backend: str = \"memory\"`; kernel/api.py:34 `mode: str = \"single\"`; sim.sh:57 `exec python3 simloader.py run` (no worker processes)",
      "simorgh/contracts/compat.py:10-12 \"The catalog is at v1 for every type, so this module is currently a registry with no translators\"",
      "simorgh/contracts/schemagen.py:6-10 \"what other tooling -- or a non-Python subsystem one day -- can consume\"; ls simorgh/contracts/schema | wc -l -> 174; contracts DSL (fields/registry/validation/schemagen/envelope/compat) -> 810 lines + 1,163 lines of message declarations",
      "docs/blueprint/01-vision-and-principles.md:75-79 \"Not a distributed system on day one ... reference deployment is one host, one process\" -- the blueprint's own non-goal",
      "tests referencing aws/dynamodb: tests/simorgh/bus/test_aws_fake.py, tests/simorgh/ledger/test_backends.py -- tested against fakes, never run for real"
    ],
    "why_it_matters": "Every one of these is a surface a self-patching agent can wander into, a test the loader gate has to run, and a doc that has to stay true. The cloud modes are the clearest case of a creator constraint ('host anywhere') that costs real weight for zero present value.",
    "recommendation": "Freeze, then delete: bus/backends/aws.py, ledger/backends/dynamodb.py, WorkerKernel and the `worker` CLI subcommand, contracts/compat.py, and the schema/*.json projection (keep the in-process validation the DSL gives you; it is cheap and catches real payload mistakes). If 'host anywhere' ever returns, the boundary discipline means the backends can be re-added behind the same Protocols without touching subsystems -- that is the abstraction actually worth keeping.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Inspect backends, config, and launch script | simorgh/bus/backends: __init__.py __pycache__ aws.py memory.py sqlite.py simorgh/ledger/backends: __init__.py __pycache__ dynamodb.py jsonl.py memory.py sqlite. |
| 2 | Bash | Check compat and schemagen usage | --- compat """Schema-version translators (docs/blueprint/03 section 8). Adding an optional field is a minor change and needs nothing here. Removing, renaming, o |
| 3 | Bash | Verify importers of cloud backends, worker mode, tests, blueprint lines | --- compat importers --- schemagen users in simorgh/tools simorgh/contracts/README.md simorgh/contracts/fields.py simorgh/contracts/registry.py simorgh/contract |
| 4 | Bash | Check runtime wiring of compat, schema consumers, worker CLI, test share, history | --- translate wired into bus? --- schema json consumers simorgh/verification/planreview.py:35: # (contracts/schema/plan.reviewed.v1.json). simorgh/verification/ |
| 5 | Bash | Check compat wiring, history dates, blueprint plans for multi-mode | --- compat tests tests/simorgh/contracts/test_compat.py tests/simorgh/orchestration/test_tools_router.py tests/simorgh/orchestration/test_context.py tests/simor |
| 6 | Bash | Read EVOLUTION entry on local-multi and roadmap references | 119. **`local-multi` mode lands, closing roadmap Phase 5 item 1 -- and turns up a real bug that was never local-multi-specific at all.** Same read-first pattern |
| 7 | Bash | Read Phase 5 roadmap and check bus version handling | ### Phase 5 — Scale-out, adapters, cutover (M) - `local-multi` mode: Worker processes on the SQLite bus; crash/resume drills. - Optional `aws` backends (SNS/SQS |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The facts check out: the cloud backends, WorkerKernel/worker subcommand, empty compat registry and 174-file schema projection all exist, and none is in force (~/.simorgh/simorgh.toml has no [bus]/[ledger]/[runtime] section; defaults are bus=memory, ledger=jsonl, mode=single; sim.sh:57 runs a single process). But two parts of the claim are overstated and the recommendation is disproportionate at this scale. (1) "not on the roadmap the creator is actually executing" is wrong for local-multi: docs/blueprint/04-build-plan-and-roadmap.md:162-166 lists local-multi and optional aws backends as Phase 5 items, and EVOLUTION #119 records local-multi landing as "closing roadmap Phase 5 item 1". The blueprint line the finding quotes as a "non-goal" continues "Multi-process and multi-host are supported by the Bus/Ledger abstractions and are a *configuration* choice" (01-vision-and-principles.md:79-82), so it was a stated design goal, not a contradiction. (2) The cost is far smaller than "real weight": aws.py+dynamodb.py are 551 lines, lazily imported only when configured (bus/factory.py:69, ledger/factory.py:33-39), tested by 6 fake-driven tests plus a share of 25 backend-parity tests; nothing at runtime touches them. Deleting them saves almost nothing and WorkerKernel (110 lines) is the one scale-out mode that actually fits one laptop (crash isolation of task workers). What IS a real, materially new issue: simorgh/contracts/compat.py:7-9 claims "The Bus routes an older message through translate() before delivery and dead-letters anything it cannot translate", yet grep finds zero references to translate/compat in simorgh/bus or simorgh/kernel; the module is imported only by its own test. That is the project's dominant "unconnected wire" shape (a doc-asserted mechanism with no caller), a genuine bug in the docstring/design rather than over-engineering. And the schema projection has a concrete recurring tax: tests/simorgh/contracts/test_schemagen.py:10 test_checked_in_schemas_are_in_sync forces regeneration of the 174 JSON files on every message change, while no runtime code consumes them (only code comments in verification/ and execution/pathsafety.py cite them). So: the actionable, proportionate fix is narrow (fix or wire compat; make the JSON projection on-demand rather than checked-in-and-gated), not the wholesale deletion the finding recommends.

### evidence

- ~/.simorgh/simorgh.toml: sections present are [voice], [interface], [execution], [cognition]; no [bus], [ledger], [runtime] -- confirmed
- simorgh/bus/config.py:30 `backend: str = "memory"`; simorgh/ledger/config.py:18 `backend: str = "jsonl"`; simorgh/kernel/api.py:34 `mode: str = "single"`; sim.sh:57 `exec "$PYTHON_BIN" simloader.py run "$@"` -- confirmed single process
- wc -l: simorgh/bus/backends/aws.py 269, simorgh/ledger/backends/dynamodb.py 282; both lazy-imported only when configured: simorgh/bus/factory.py:69 `from .backends.aws import AwsBackend  # lazy`, simorgh/ledger/factory.py:33-39
- simorgh/contracts/compat.py:7-9 docstring: 'The Bus routes an older message through `translate()` before delivery and dead-letters anything it cannot translate'; `grep -rn 'translate\|can_translate' simorgh/bus simorgh/kernel` -> no output; only importer in the tree is tests/simorgh/contracts/test_compat.py:3 -- the mechanism is documented but never wired (materially new)
- ls simorgh/contracts/schema | wc -l -> 174; tests/simorgh/contracts/test_schemagen.py:10 `test_checked_in_schemas_are_in_sync` gates every message change on regeneration; no runtime consumer: grep for 'contracts/schema' outside simorgh/contracts hits only comments (verification/planreview.py:35, verification/service.py:48, verification/api.py:41, verification/verdict.py:26,33, execution/pathsafety.py:21)
- simorgh/kernel/service.py:570 `class WorkerKernel` (110 lines); simorgh/kernel/cli.py:31-34 `worker` subparser; kernel/service.py:90-103 refuses local-multi without a cross-process backend
- docs/blueprint/01-vision-and-principles.md:79-82: 'Not a distributed system on day one. Multi-process and multi-host are supported by the Bus/Ledger abstractions and are a *configuration* choice, but the reference deployment is one host, one process (or a few)' -- the finding's quote omits the second clause
- docs/blueprint/04-build-plan-and-roadmap.md:162-166 Phase 5 lists '`local-multi` mode: Worker processes on the SQLite bus' and 'Optional `aws` backends (SNS/SQS/DynamoDB/S3)'; docs/EVOLUTION.md:3133 '`local-multi` mode lands, closing roadmap Phase 5 item 1' -- local-multi was on the executed roadmap
- Test weight is small: tests/simorgh/bus/test_aws_fake.py 6 tests (166 lines), tests/simorgh/ledger/test_backends.py 25 tests of which 6 lines mention dynamo; all against fakes, no boto3 required (test_aws_fake.py:27 tests the missing-boto3 path)
- git log -1 dates: aws.py last touched 2026-09-08, dynamodb.py 2026-09-10, compat.py and schemagen.py untouched since 2026-09-06 creation -- the cloud backends receive no ongoing work beyond cross-cutting fixes

**severity adjustment:** lower

**corrected claim:** The aws/dynamodb backends and the local-multi WorkerKernel exist and are not in force (config defaults to memory bus, jsonl ledger, single mode; sim.sh runs one process), but they were planned roadmap items (Phase 5) explicitly framed by the blueprint as a configuration choice, are lazily imported, and cost ~550 lines plus a handful of fake-driven tests -- negligible weight that does not justify deletion. Two narrower issues are real: (a) simorgh/contracts/compat.py documents a Bus translation step that no Bus or Kernel code calls (an unconnected wire, the project's dominant bug shape) -- either wire it or delete the module and its docstring claim; (b) the 174 checked-in JSON schema files are enforced in sync by a unit test on every message change yet have no runtime consumer, so they should be generated on demand (or the sync test dropped) rather than kept as a gated artifact.

