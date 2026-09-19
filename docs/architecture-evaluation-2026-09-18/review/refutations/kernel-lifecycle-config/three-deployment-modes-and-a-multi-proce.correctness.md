# refute:correctness:Three deployment modes and a multi-proce

*Workflow: review · Phase: Refute · Agent id: `abde4e478b455684c` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "Three deployment modes and a multi-process trust model carried by a single-process system, plus a self-check that proves stubs and is never called",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "WorkerKernel, IdentityRegistry, per-process identity tokens, `aws` mode and the `--self-check` proof exist for a topology that has never run here; in the only mode in use (`single`, one Python process) the HMAC approval token and reserved-topic policy are discipline rather than a boundary, and selfcheck.py exercises stub Guardian/Execution rather than the registry the blueprint says it boots.",
    "evidence": [
      "~/.simorgh/simorgh.toml has no [runtime] section (mode defaults to 'single', api.py:34); bus/config.py:30 backend default 'memory'.",
      "simorgh/kernel/service.py:353-354 '`aws` mode is untouched here -- its process topology is a different track's concern'; :588-597 WorkerKernel docstring: the worker's identity secret 'is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process ... unfinished hardening'.",
      "simorgh/kernel/selfcheck.py:10-14 'The Guardian/Execution used here are minimal stubs, not the real subsystems'; :7-8 claims `learning`'s relaunch tool calls this before execv -- grep for 'self-check|run_selfcheck|selfcheck' outside kernel/ finds no caller; docs/blueprint/subsystems/03-kernel.md:292-294 promises the self-check 'Boots the full registry on the memory bus and memory ledger'.",
      "service.py:167-172 acknowledges the token secret doubles as the identity secret; in single mode `identities` is None (line 173) and the Kernel object holding `_hmac_secret` is reachable from any code in the process."
    ],
    "why_it_matters": "For one laptop and one family the safety property that matters is 'Execution runs only what Guardian approved', which in-process is a code-review property; the token machinery documents it nicely but the extra modes double the surface (two kernels, two boot paths, a policy with two enforcement regimes) and produce docstrings that explain why they do not quite work. The self-check is 256 lines that assert something no boot depends on.",
    "recommendation": "Keep the approval token (cheap, self-documenting) and the ReservedTopologyPolicy; delete WorkerKernel, `simorgh worker`, `aws`/`local-multi` and IdentityRegistry until a second process actually exists (git keeps them). Either make `--self-check` the real thing (boot the actual registry on memory backends in a temp data dir and run one guarded no-op) and call it from the loader watchdog path, or delete it.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check runtime mode config and defaults | 27:model = "qwen3:4b-instruct" 32:vision_model = "qwen2.5vl:3b" ---api.py--- """A subsystem asked for a secret it was not scoped to, or that was never configure |
| 2 | Bash | Read cited service.py and selfcheck.py lines, find selfcheck callers | ---service.py 160-180--- _require_cross_process_backends(self.config, self.runtime) self.runtime.data_dir.mkdir(parents=True, exist_ok=True) self.progress.stage |
| 3 | Bash | Find selfcheck callers, relaunch tool, worker command wiring | ---py callers of selfcheck outside kernel/selfcheck.py--- simorgh/interface/service.py:156: # every headless boot (tests, `--self-check`, `status`, `trace`) sim |
| 4 | Bash | Trace relaunch tool, execv paths, loader, aws backends, cross-process guard | ---relaunch tool defs--- simorgh/kernel/selfcheck.py:7:a *behavioral* proof; `learning`'s `relaunch` tool calls this (via `simorgh simorgh/kernel/selfcheck.py:8 |
| 5 | Bash | Check toml backends, relaunch tool, aws backend size, real-registry test, selfcheck body | ---toml sections--- 1:[voice] 15:[interface] 18:[execution] 22:[cognition] 24:[cognition.providers] 26:[cognition.providers.ollama] ---v2 relaunch tool registra |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every file:line the finding cites is accurate as of today's code, and the finding is not in the known list (the closest known item, "self_patch.draft not registered", is a different wire). Verified: ~/.simorgh/simorgh.toml has only [voice]/[interface]/[execution]/[cognition*] sections, so RuntimeConfig.mode defaults to "single" (api.py:34) and bus backend to "memory" (bus/config.py:30); service.py:173 builds IdentityRegistry only when mode != "single", so in the live deployment the ReservedTopologyPolicy has no identity check and the approval HMAC secret lives on the Kernel object in-process; service.py:353-354 and :588-597 contain the quoted docstrings, including the admission that a worker's identity secret "is *not*, and today cannot be" the main process's secret and that policy is "enforced client-side, per process"; WorkerKernel.__init__ (service.py:605-609) refuses to start unless mode == "local-multi", so `simorgh worker` (cli.py:32, :206) is unreachable under the current config; aws bus and dynamodb ledger backends exist as further unused surface (269 + 282 lines). selfcheck.py:174-190 constructs _StubGuardian/_StubExecution on InMemoryLedgerBackend and a default BusConfig, not the registry, while docs/blueprint/subsystems/03-kernel.md:292-294 promises "Boots the full registry". The docstring at selfcheck.py:7-8 claims learning's relaunch tool calls it before execv, but no tool named "relaunch" is registered anywhere in simorgh/ (only named as a string at learning/pipeline.py:188 and in docstrings at execution/tools.py:8, execution/config.py:3); the only execv in the tree is simloader.py:1101, and simloader.py contains no reference to self-check (it gates with the unit suite). The restart path (kernel/cli.py:199, RESTART_EXIT_CODE) also does not run it. Two corrections lower the precision of the claim, not its substance: (1) "--self-check ... is never called" is overstated -- it is exercised by tests (tests/simorgh/kernel/test_cli.py:161, tests/simorgh/kernel/test_selfcheck.py:3, tests/test_e2e_cli.py:85); what is true is that no boot, relaunch, restart or loader path calls it, and the docstring's named caller does not exist. (2) The stub-vs-registry gap is a documented, deliberate choice: tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py:12-17 states that --self-check "deliberately uses two small inline stub subsystems" and that this integration test is where the real registry is booted. So the real-registry proof exists, as a test rather than as the CLI flag the blueprint describes. The classification (over-engineering for one-laptop scale, plus blueprint/code drift on the self-check) stands; severity medium is appropriate.

### evidence

- ~/.simorgh/simorgh.toml sections: [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama] -- no [runtime], [bus], or [ledger]; grep 'backend' returns nothing
- simorgh/kernel/api.py:34 `mode: str = "single"  # single | local-multi | aws`; simorgh/bus/config.py:30 `backend: str = "memory"  # memory | sqlite | aws`
- simorgh/kernel/service.py:173 `identities = IdentityRegistry(self._hmac_secret, self.run_id) if self.runtime.mode != "single" else None`; :174 `policy = ReservedTopologyPolicy(identities)`; :167-172 comment on reusing the approval secret as the identity secret
- simorgh/kernel/service.py:353-354 `aws` mode is untouched here -- its process topology is a different track's concern
- simorgh/kernel/service.py:588-597 WorkerKernel docstring: secret 'is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process (... unfinished hardening ...)'; :605-609 raises KernelBootError unless mode == "local-multi"
- simorgh/bus/enforcement.py:14-22 docstring: identity verified only on sqlite/aws backends; 'In `single` mode identity is the in-process client object'
- simorgh/bus/backends/aws.py 269 lines; simorgh/ledger/backends/dynamodb.py 282 lines -- present, unreachable under current config
- simorgh/kernel/selfcheck.py:7-8 claims `learning`'s `relaunch` tool calls this via `simorgh --self-check` before execv; :10-14 'The Guardian/Execution used here are minimal stubs'; :174-190 run() builds InMemoryLedgerBackend, BusConfig(), ReservedTopologyPolicy(), _StubGuardian, _StubExecution -- no registry; wc -l = 256
- grep -rn 'relaunch' simorgh/ : only docstrings (execution/tools.py:8, execution/config.py:3, pipeline.py:3) and learning/pipeline.py:188 `activation_tool = "hot_swap" if ... else "relaunch"` -- no tool named relaunch is registered
- grep -rn 'execv|os.exec' simorgh/ simloader.py : only simloader.py:1101; grep 'self-check|selfcheck|self_check' simloader.py sim.sh : no matches
- Callers of run_selfcheck: simorgh/kernel/cli.py:20,72,376-377 only; test callers tests/simorgh/kernel/test_cli.py:161, tests/simorgh/kernel/test_selfcheck.py:3, tests/test_e2e_cli.py:85 (tests/test_self_patch.py is v1 `src.` code)
- docs/blueprint/subsystems/03-kernel.md:292-294 '### 5.4 Self-check (`--self-check`) Boots the full registry on the `memory` bus and `memory` ledger in a temp data dir'
- tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py:12-17: 'Unlike the CLI's own `--self-check` (which deliberately uses two small inline stub subsystems ...), this test is the one place the REAL seventeen are all constructed together'

**severity adjustment:** keep

**corrected claim:** WorkerKernel, IdentityRegistry, per-process identity tokens, the aws bus/dynamodb ledger backends and `local-multi`/`aws` modes exist for a topology the live config never selects (no [runtime]/[bus] in ~/.simorgh/simorgh.toml; WorkerKernel refuses to boot outside local-multi). In the only mode in use (`single`), service.py:173 builds no IdentityRegistry, so the reserved-topic policy and the HMAC approval token are in-process discipline, not a boundary. `--self-check` (selfcheck.py, 256 lines) drives stub Guardian/Execution rather than the registry the blueprint (03-kernel.md:292-294) describes; its docstring names a `relaunch` tool caller that is not registered anywhere in simorgh/, and no boot, restart, relaunch or simloader path invokes it -- it is exercised only by unit/e2e tests. The real-registry boot proof does exist, but as tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py, not as the CLI flag the blueprint promises.

