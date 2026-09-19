# refute:proportionality:Three deployment modes and a multi-proce

*Workflow: review · Phase: Refute · Agent id: `a19868da05f60c3cc` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read api.py mode defaults, bus config default, and toml runtime section | """Internal interfaces of the Kernel (docs/blueprint/subsystems/03-kernel.md section 3.4/5). The Kernel is the composition root -- the one package `02-system-ar |
| 2 | Bash | Read cited service.py and selfcheck.py passages, count lines, find selfcheck callers |  self.progress = make_boot_progress(interactive) async def boot(self) -> None: from .supervisor import BootFailed, BootTimeout, Supervisor _require_cross_proces |
| 3 | Bash | Find selfcheck callers, tests, identity module, enforcement docstring, toml sections, relaunch tool, CLI wiring, blueprint text | == selfcheck callers simorgh/interface/service.py:156: # every headless boot (tests, `--self-check`, `status`, `trace`) simorgh/interface/service.py:677: topics |
| 4 | Bash | Check relaunch tool implementation, worker CLI subcommand, loader self-check use, WorkerKernel size, enforcement identity code, local-multi  | == relaunch tool impl simorgh/execution/tools.py:1087: empty environment (no PATH for execvp to search).""" simorgh/learning/pipeline.py:188: activation_tool =  |
| 5 | Bash | Check relaunch tool existence, aws backend size, worker usage in loader, EVOLUTION local-multi context, selfcheck steps | == relaunch anywhere (eval):1: no matches found: --include=*.py == aws backends simorgh/bus/backends: __init__.py __pycache__ aws.py memory.py sqlite.py simorgh |
| 6 | Bash | Locate relaunch tool registration and measure aws/worker code sizes | == relaunch anywhere simorgh/execution/config.py:3:relaunch, hot_swap, and isolated_test_suite (and their config keys) are simorgh/execution/tools.py:8:procedur |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out against the code as of today, and two things I verified make the finding slightly stronger rather than weaker. (1) The IdentityRegistry protects nothing in ANY mode: in `single` it is None (service.py:173), and in `local-multi` WorkerKernel builds its own registry from `security.new_run_secret()` (service.py:626) and self-authenticates, so the token a worker presents is verified only by the worker's own in-process policy; the main process never sees or verifies it. The identity layer is therefore a no-op both in the mode in use and in the one it was built for -- the docstring says as much. (2) The self-check is a genuine unconnected wire: selfcheck.py:7-8 says learning's `relaunch` tool calls `simorgh --self-check` before execv, but no `relaunch` tool is registered anywhere (grep finds only docstring mentions in execution/config.py:3, execution/tools.py:8, learning/pipeline.py:188 names it as a string), and neither sim.sh nor simloader.py invokes `--self-check`; the only caller is kernel/cli.py:376 behind a manual flag. The blueprint (03-kernel.md:295-297) promises it boots the full registry; the code boots `_StubGuardian`/`_StubExecution` (selfcheck.py:59,111,188-189). The `_hmac_secret` lives on the Kernel instance (service.py:134) and is handed to ContextFactory (service.py:222); in a single process this is code discipline, not a boundary, as claimed.

Skeptic lens (is this disproportionate at one-laptop scale?): the footprint is small -- WorkerKernel ~111 lines, IdentityRegistry ~15 lines, aws bus backend 269 + dynamodb ledger 282 lines, selfcheck 256 lines, roughly 1% of 87k -- so the cost is not code volume but two boot paths and two enforcement regimes, one of which (per-process client-side identity) the code itself documents as not actually enforcing anything. That is a fair "over-engineering" call at medium severity, not higher. One nuance that softens the wording but not the verdict: "a topology that has never run here" overstates it slightly -- tests/simorgh/integration/test_local_multi_worker_crash_resume.py does spawn real `simorgh worker` OS processes on the sqlite bus, so local-multi runs under the suite; it has never run as the deployed configuration (~/.simorgh/simorgh.toml has no [runtime] section, sim.sh/simloader never invoke `worker`). The recommendation (keep the approval token and ReservedTopologyPolicy; shelve WorkerKernel/aws/IdentityRegistry until a second process exists; make --self-check real or delete it) is cheap and proportionate; the aws/dynamodb backends alone are ~550 lines with no config referencing them.

### evidence

- ~/.simorgh/simorgh.toml sections: [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama] -- no [runtime]; simorgh/kernel/api.py:34 `mode: str = "single"`; simorgh/bus/config.py:31 `backend: str = "memory"`
- simorgh/kernel/service.py:173 `identities = IdentityRegistry(self._hmac_secret, self.run_id) if self.runtime.mode != "single" else None`; :134 `self._hmac_secret = security.new_run_secret()`; :222 passed to ContextFactory
- simorgh/kernel/service.py:353-354 '`aws` mode is untouched here -- its process topology is a different track's concern'
- simorgh/kernel/service.py:588-597 WorkerKernel docstring: 'That secret is generated fresh in this process and is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process'; :626 `identities = IdentityRegistry(security.new_run_secret(), self.run_id)`
- simorgh/bus/enforcement.py:61-68 `authenticate()` verifies against the registry built in the same process; :33-50 IdentityRegistry is ~15 lines
- simorgh/kernel/selfcheck.py:7-8 claims learning's `relaunch` tool calls `simorgh --self-check` before execv; :10-14 'The Guardian/Execution used here are minimal stubs'; :59 `class _StubGuardian`, :111 `class _StubExecution`, :188-189 instantiated in `run()`; file is 256 lines
- grep -rn 'relaunch' simorgh | grep '\.py:' -> only docstring mentions (execution/config.py:3, execution/tools.py:8, kernel/cli.py:91,199) and learning/pipeline.py:188 `activation_tool = ... else "relaunch"`; no tool named relaunch is registered
- grep -n 'self-check\|self_check' sim.sh simloader.py -> no output; only caller is simorgh/kernel/cli.py:376-377 `if args.self_check: return asyncio.run(_cmd_self_check())`
- docs/blueprint/subsystems/03-kernel.md:295-297 'Boots the full registry on the `memory` bus and `memory` ledger in a temp data dir with providers disabled'
- Sizes: WorkerKernel service.py:570-680 (~111 lines); simorgh/bus/backends/aws.py 269 lines; simorgh/ledger/backends/dynamodb.py 282 lines; grep -rn 'simorgh worker' sim.sh simloader.py tools/*.py -> no output
- Nuance: tests/simorgh/integration/test_local_multi_worker_crash_resume.py:1-20 spawns real `simorgh.kernel.cli.main(["worker", ...])` OS processes on the sqlite bus, so local-multi has run under the test suite, though never as the deployed config; docs/EVOLUTION.md:3146-3148 records that `local-multi`/`aws` boot 'had never actually worked, not once' before that fix

**severity adjustment:** keep

