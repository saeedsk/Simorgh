# refute:proportionality:Multi-process and cloud substrate (sqlit

*Workflow: review · Phase: Refute · Agent id: `a5e82689d3118243d` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "bus-ledger-substrate". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Multi-process and cloud substrate (sqlite bus, SNS/SQS, DynamoDB, WorkerKernel, identity tokens, tail polling) is never used and its security premise is documented as unfinished",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "About 2,000 lines of backends plus 740 test lines, WorkerKernel, IdentityRegistry, the durable flag, cross_process polling and Ledger.tail exist for local-multi/aws modes that nothing selects, while their abstractions leak into the single-process path (an extra stat per append because jsonl declares cross_process=True; tail's poll loop; durable accepted and ignored).",
    "evidence": [
      "~/.simorgh/simorgh.toml has no [bus] or [ledger] section -> defaults `backend: str = \"memory\"` (bus/config.py:30) and `backend: str = \"jsonl\"` (ledger/config.py:18); kernel/api.py:34 `mode: str = \"single\"`",
      "grep for sqlite/aws/dynamodb backend selection outside tests and the backends themselves: only docstrings (kernel/service.py:70, :546, :574)",
      "wc -l: bus/backends/sqlite.py 422, bus/backends/aws.py 269, ledger/backends/sqlite.py 275, ledger/backends/dynamodb.py 282, tests 740; WorkerKernel = 135 lines from kernel/service.py:570",
      "kernel/service.py:593-595 -- 'is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process ... unfinished'",
      "bus/backends/sqlite.py:18-21 -- 'DB calls are synchronous on the event loop' (its own docstring), contradicting the ledger sqlite backend's to_thread design",
      "jsonl.py:71 `cross_process = True` -> `_refresh_if_grown` stat on every append (jsonl.py:402) and every find_by_idempotency (jsonl.py:452); `Ledger.tail` (contracts/protocols.py:58, ledger/client.py:199-224) has zero callers"
    ],
    "why_it_matters": "For one laptop and one family this is maintenance surface without a user: every ledger change must keep four backends in parity, and the interfaces carry flags that lie (durable). The one piece that would actually help today -- the sqlite ledger backend, for the tiny-file problem -- is the part not being used.",
    "recommendation": "Delete the aws bus backend, dynamodb backend, WorkerKernel and identity-token paths (git keeps them); drop tail/durable/cross_process from the protocols. Keep exactly two ledger backends, memory for tests and sqlite for the laptop, and promote sqlite to the default once traces move there.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check backend sizes, defaults and config |  422 simorgh/bus/backends/sqlite.py 269 simorgh/bus/backends/aws.py 275 simorgh/ledger/backends/sqlite.py 282 simorgh/ledger/backends/dynamodb.py 815 simorgh/le |
| 2 | Bash | Check backend selection sites and WorkerKernel | === backend selection outside tests/backends === (eval):1: no matches found: --include=*.py === kernel/service.py lines 60-80, 540-600 === class KernelBootError |
| 3 | Bash | Locate backend selectors, worker entrypoint, jsonl cross_process | === who selects sqlite/aws/dynamodb (non-test, non-backend) === simorgh/ledger/config.py:13:BACKENDS = ("memory", "jsonl", "sqlite", "dynamodb") simorgh/ledger/ |
| 4 | Bash | Check refresh/lock, tail callers, durable flag, sqlite docstrings | === _refresh_if_grown + _file_lock === if meta is None: path = self._stream_path(stream) if path.exists(): # appended by another process since start self._scan_ |
| 5 | Bash | Check durable flag, tail callers, test sizes, other ledger readers |  |

## Structured reply

_No result recorded (agent still running, skipped, or failed)._

## Final text

I'll verify the cited evidence directly.