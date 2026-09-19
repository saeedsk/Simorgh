# refute:correctness:Three deployment modes and seven backend

*Workflow: review · Phase: Refute · Agent id: `aa7cf157162bb5d06` · Tool calls: 5*

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
| 1 | Bash | List backends, config defaults, and sim.sh exec line | simorgh/bus/backends: __init__.py __pycache__ aws.py memory.py sqlite.py simorgh/ledger/backends: __init__.py __pycache__ dynamodb.py jsonl.py memory.py sqlite. |
| 2 | Bash | Check compat/schemagen headers, blueprint non-goal, tests, and who uses worker/compat/schema | """Schema-version translators (docs/blueprint/03 section 8). Adding an optional field is a minor change and needs nothing here. Removing, renaming, or retyping  |
| 3 | Bash | Check who uses WorkerKernel, compat, schema json, local-multi, aws mode, boto3 | - **Not a distributed system on day one.** Multi-process and multi-host are supported by the Bus/Ledger abstractions and are a *configuration* choice, but the r |
| 4 | Bash | Check compat usage, line counts, prior reviews coverage, tests | --- translate/compat in bus --- compat imported anywhere --- messages lines __init__.py __pycache__ action.py 1163 total --- DSL sum 810 total --- worker tests  |
| 5 | Bash | Check prior HTML review, runtime schema loading, EVOLUTION mentions, factory wiring | --- html mentions aws --- schema json loaded at runtime? simorgh/contracts/checkout.py:39:MANIFEST_NAME = ".simorgh-checkout.json" simorgh/contracts/checkout.py |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact checks out against the code today, and the finding is not in the known list (docs/architecture-audit-2026.md and docs/architecture-review-2026-09-18.html contain no mention of dynamodb, WorkerKernel, local-multi, compat.py or schemagen; docs/architecture-third-opinion-2026-09-18.md:79 actually praises the "four backend tiers (memory -> jsonl -> sqlite -> dynamodb)" as a clean upgrade path, i.e. the opposite reading). The live config (~/.simorgh/simorgh.toml) has only [voice], [interface], [execution], [cognition] sections, so bus=memory, ledger=jsonl, runtime.mode=single are the defaults in force; sim.sh exports only SIMORGH_EXECUTION_REPO_ROOT and never starts a worker process. The aws bus backend and dynamodb ledger backend are reachable only via factory branches (bus/factory.py:68, ledger/factory.py:34) that nothing in the live path selects. One materially NEW point strengthens the claim beyond what the reader wrote: contracts/compat.py's docstring says "The Bus routes an older message through translate() before delivery", but `grep -rn "translate\|compat" simorgh/bus` returns nothing and no module anywhere imports contracts.compat -- it is a registry with no translators AND no caller (the project's "unconnected wire" shape applied to its own versioning story). The schema/*.json files are likewise never json.load'ed at runtime; they are referenced only in comments (verification/service.py:48, verification/verdict.py:26, execution/pathsafety.py:21). The blueprint's own non-goal (01-vision-and-principles.md:82-85) says "reference deployment is one host, one process (or a few), no cloud dependency". Classification: (a) over-built for real scale. Severity medium is right: the weight is real (2,503 lines of backends, 810 lines DSL, 1,163 lines declarations, 7 test files for local-multi alone that the loader gate must run) but nothing here is broken in the live path. Recommendation is sound; I would add that if compat.py is kept, it must be wired into the Bus or its docstring corrected.

### evidence

- `ls simorgh/bus/backends` -> aws.py memory.py sqlite.py; `ls simorgh/ledger/backends` -> dynamodb.py jsonl.py memory.py sqlite.py; `wc -l` -> aws.py 269, dynamodb.py 282 (2,503 lines across all backends)
- `cat ~/.simorgh/simorgh.toml` -> sections present: [voice] [interface] [execution] [cognition] [cognition.providers.ollama] only; no [bus], [ledger], [runtime]
- simorgh/bus/config.py:30 `backend: str = "memory"  # memory | sqlite | aws`; simorgh/ledger/config.py:18 `backend: str = "jsonl"`; simorgh/kernel/api.py:34 `mode: str = "single"  # single | local-multi | aws`; simorgh/kernel/config.py:84 `_VALID_MODES = ("single", "local-multi", "aws")`
- sim.sh:22 is the only `export SIMORGH_*` line (SIMORGH_EXECUTION_REPO_ROOT); no worker process is spawned; simorgh/kernel/cli.py:32 registers the `worker` subcommand, cli.py:206 `worker = WorkerKernel(config, worker_id=worker_id)`; simorgh/kernel/service.py:570 `class WorkerKernel:`
- simorgh/bus/factory.py:68 `if config.backend == "aws": from .backends.aws import AwsBackend`; simorgh/ledger/factory.py:34-38 lazy `from .backends.dynamodb import DynamoBackend, _boto3_adapters` -- only reachable by explicit config that is not set
- simorgh/contracts/compat.py:10-13 "The catalog is at v1 for every type, so this module is currently a registry with no translators"; compat.py:7-9 claims "The Bus routes an older message through `translate()` before delivery" but `grep -rn "translate\|compat" simorgh/bus --include='*.py'` -> no output, and `grep -rn "from .compat\|contracts.compat" simorgh` -> no importer anywhere (NEW: no translators and no caller)
- simorgh/contracts/schemagen.py:6-10 "what other tooling -- or a non-Python subsystem one day -- can consume"; `ls simorgh/contracts/schema | wc -l` -> 174; `wc -l fields,registry,validation,schemagen,envelope,compat` -> 810 total; `wc -l simorgh/contracts/messages/*.py` -> 1163 total; `grep -rn "json.load" simorgh/contracts/*.py` shows no runtime load of schema/*.json -- referenced only in comments (verification/service.py:48, verification/verdict.py:26, execution/pathsafety.py:21)
- docs/blueprint/01-vision-and-principles.md:82-85 "Not a distributed system on day one. Multi-process and multi-host are supported by the Bus/Ledger abstractions and are a *configuration* choice, but the reference deployment is one host, one process (or a few), no cloud dependency."
- tests: tests/simorgh/bus/test_aws_fake.py; tests/simorgh/ledger/test_backends.py:3 "(two adapter protocols, no credentials/network) `dynamodb`", :409 imports DynamoBackend; local-multi/WorkerKernel referenced by 7 test files incl. tests/simorgh/integration/test_local_multi_worker_crash_resume.py -- all run by the loader gate
- docs/EVOLUTION.md:3147 "`local-multi`/`aws` boot had never actually worked, not once" (history; confirms these modes were never a running deployment)
- Prior reviews: `grep -i "dynamodb|aws|WorkerKernel|local-multi|compat.py|schemagen" docs/architecture-audit-2026.md` -> no hits; same on docs/architecture-review-2026-09-18.html -> no hits; docs/architecture-third-opinion-2026-09-18.md:79 praises the "four backend tiers (memory -> jsonl -> sqlite -> dynamodb)" -- so this finding is new, not a repeat

**severity adjustment:** keep

