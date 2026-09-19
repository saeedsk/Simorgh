# refute:correctness:Multi-process and cloud substrate (sqlit

*Workflow: review · Phase: Refute · Agent id: `a7b7e8b14bb1aa9b1` · Tool calls: 8*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "bus-ledger-substrate". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Check config defaults and toml sections | --- toml sections --- 1:[voice] 15:[interface] 18:[execution] 22:[cognition] 24:[cognition.providers] 26:[cognition.providers.ollama] --- bus/config.py --- @dat |
| 2 | Bash | Line counts and backend selection grep | --- wc --- 422 simorgh/bus/backends/sqlite.py 269 simorgh/bus/backends/aws.py 275 simorgh/ledger/backends/sqlite.py 282 simorgh/ledger/backends/dynamodb.py 704  |
| 3 | Bash | Backend selection sites, WorkerKernel and docstrings | --- backend selection outside backends dirs --- simorgh/ledger/config.py:13:BACKENDS = ("memory", "jsonl", "sqlite", "dynamodb") simorgh/ledger/config.py:45: dy |
| 4 | Bash | Check cross_process flag and refresh-on-append in jsonl backend | Exit code 1 --- jsonl.py 65-75 --- def as_dict(self) -> dict: return {"head": self.head, "bytes": self.bytes, "last_ts": self.last_ts} class JsonlBackend: cross |
| 5 | Bash | Verify tail, durable, file lock, sqlite docstrings | --- _refresh_if_grown body --- def _refresh_if_grown(self, stream: str) -> None: """Another process may have appended: if the file is longer than we last saw, r |
| 6 | Bash | Check durable flag, identity registry, test line counts, ledger dir | --- durable in bus --- simorgh/bus/client.py:207: self, pattern: str, handler: Handler, *, group: str \| None = None, durable: bool = False, simorgh/bus/client.p |
| 7 | Bash | Confirm enforcement docstring and factory selection | --- ledger sqlite backend ever selected by toml/env/sim.sh? --- tools/bench_recall.py:79: ledger = make_ledger(LedgerConfig(backend="jsonl", data_dir=tmp, fsync |
| 8 | Bash | Read enforcement module docstring for the security caveat | 1:"""Reserved-topology enforcement (docs/blueprint/03 section 3 and section 15:Identity is the hard part in multi-process modes: a process could claim 19:`sourc |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core of the claim holds against the code today. ~/.simorgh/simorgh.toml has sections [voice] [interface] [execution] [cognition] only -- no [bus], [ledger] or [runtime] -- so the process runs with bus backend="memory" (simorgh/bus/config.py:30), ledger backend="jsonl" (simorgh/ledger/config.py:18) and mode="single" (simorgh/kernel/api.py:34). Line counts match exactly (422/269/275/282, service.py is 704 lines so WorkerKernel at :570 is 135 lines). Backend selection sites outside tests are only the two factories (bus/factory.py:63,68; ledger/factory.py:29,33) driven by config that nothing sets; sim.sh/simloader.py/tools set no backend. In single mode `identities` is None (kernel/service.py:173), so IdentityRegistry exists only for the unselected modes. The WorkerKernel docstring at service.py:588-596 does say the worker secret 'is *not*, and today cannot be, the same secret ... policy is enforced client-side, per process ... unfinished hardening', and bus/enforcement.py:15-20 confirms 'Identity is the hard part in multi-process modes'. bus/backends/sqlite.py:17-21 says 'DB calls are synchronous on the event loop' while ledger/backends/sqlite.py:8 uses asyncio.to_thread -- the design inconsistency is real. jsonl.py:71 `cross_process = True`; append (jsonl.py:397-402) takes the fcntl _file_lock and calls _refresh_if_grown which does path.stat() (jsonl.py:393) on every append, and find_by_idempotency (jsonl.py:451-452) does the same -- that per-append cost exists only to serve other processes that never exist in single mode. `.tail(` has zero callers outside simorgh/ledger (grep over simorgh/ returned nothing); bus `durable` (client.py:207, api.py:64 'ignored by memory', memory.py:11) is accepted and ignored on the running backend. Three corrections: (1) 'nothing selects' is slightly overstated for WorkerKernel -- it is reachable via the `simorgh worker` CLI subcommand (kernel/cli.py:32,206), though it refuses unless mode=local-multi (service.py:606-608), which is never configured; (2) 'tail's poll loop' leaking into the single-process path is dead code, not a runtime cost -- with zero tail() callers the poll task is never created, so the only measurable single-process overhead is the stat+file-lock per append; (3) test line count is understated: the finding says 740, but the directly related files (test_aws_fake 166, test_sqlite_multiprocess 104, test_backends 470, test_backends_parity 257, test_local_multi_worker_crash_resume 273) total 1,270. None of this appears in the known-findings list (the known ledger finding is about JSONL size/tiny files, not about the unused multi-process substrate). Classification as 'design over-built for scale, with leakage into the live path' is fair; the enforcement caveat is a documented-unfinished design, not a bug in the running configuration.

### evidence

- grep -n '^\[' ~/.simorgh/simorgh.toml -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]; no [bus]/[ledger]/[runtime]
- simorgh/bus/config.py:30 `backend: str = "memory"  # memory | sqlite | aws`; simorgh/ledger/config.py:18 `backend: str = "jsonl"`; simorgh/kernel/api.py:34 `mode: str = "single"  # single | local-multi | aws`
- wc -l: bus/backends/sqlite.py 422, bus/backends/aws.py 269, ledger/backends/sqlite.py 275, ledger/backends/dynamodb.py 282, kernel/service.py 704 (WorkerKernel class at :570 -> 135 lines)
- grep '"sqlite"|"aws"|"dynamodb"|local-multi|WorkerKernel' simorgh --include=*.py excluding backends dirs: selection only in bus/factory.py:63,68 and ledger/factory.py:29,33 (config-driven); WorkerKernel constructed only at kernel/cli.py:206 (`simorgh worker` subcommand, kernel/cli.py:32); no sim.sh/simloader.py/tools override of backend
- simorgh/kernel/service.py:173 `identities = IdentityRegistry(self._hmac_secret, self.run_id) if self.runtime.mode != "single" else None` -- identity tokens unused in the running mode
- simorgh/kernel/service.py:592-596 docstring: 'is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process ... unfinished hardening'; bus/enforcement.py:15 'Identity is the hard part in multi-process modes'
- simorgh/bus/backends/sqlite.py:17-19 'DB calls are synchronous on the event loop ... the cost of threading a connection through to_thread is not worth it' vs simorgh/ledger/backends/sqlite.py:8 'All SQLite calls run in a worker thread (asyncio.to_thread)'
- simorgh/ledger/backends/jsonl.py:71 `cross_process = True`; :397-402 append() -> `with self._file_lock(): self._refresh_if_grown(event.stream)`; :387-395 _refresh_if_grown does `path.stat().st_size` on every call; :451-452 find_by_idempotency also calls it
- grep -rn '\.tail(' simorgh --include=*.py excluding ledger/ -> no output (zero callers); simorgh/ledger/client.py:206 creates the poll task only inside tail(), so the poll loop is dead code in practice
- simorgh/bus/client.py:207 subscribe(..., durable: bool = False); simorgh/bus/api.py:64 `durable: bool  # persisted in sqlite/aws; ignored by memory`; simorgh/bus/backends/memory.py:11 'durable=True is accepted and ignored'
- Test lines directly tied to these backends/modes: test_aws_fake.py 166 + test_sqlite_multiprocess.py 104 + test_backends.py 470 + test_backends_parity.py 257 + test_local_multi_worker_crash_resume.py 273 = 1,270 (finding said 740)
- ls ~/.simorgh/ledger -> blobs heads idem index.json LOCK snapshots streams (jsonl layout); du -sh -> 1.4G, confirming jsonl is the live backend and sqlite ledger is not

**severity adjustment:** keep

**corrected claim:** Roughly 1,250 lines of bus/ledger backends (sqlite bus, SNS/SQS, sqlite ledger, DynamoDB) plus ~135 lines of WorkerKernel and the IdentityRegistry/subsystem-token path, backed by ~1,270 test lines, exist for `local-multi`/`aws` modes that no configuration selects: simorgh.toml has no [bus]/[ledger]/[runtime] section, so the process runs memory bus + jsonl ledger in `single` mode, and `identities` is None. WorkerKernel is reachable only through the `simorgh worker` CLI, which refuses unless mode=local-multi. The multi-process abstractions leak into the single-process path in two concrete ways: the jsonl backend declares `cross_process = True`, so every append and every idempotency lookup pays a file lock plus a stat to detect writers that never exist; and the bus `durable` subscribe flag is accepted and silently ignored by the memory backend. `Ledger.tail` and its cross-process poll loop have zero callers, so they are dead interface surface rather than a runtime cost. The two sqlite backends disagree on threading design (bus sqlite is synchronous on the loop; ledger sqlite uses to_thread), and the WorkerKernel docstring itself records that cross-process identity is enforced client-side and is 'unfinished hardening'.

