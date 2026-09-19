# refute:correctness:The HMAC token is real between processes

*Workflow: review · Phase: Refute · Agent id: `ad9e0c427aab99880` · Tool calls: 4*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "safety-guardian-execution". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "The HMAC token is real between processes and ceremony within one; the actual attack surface is upstream of it",
    "kind": "over-engineering",
    "severity": "low",
    "claim": "Inside one Python process every subsystem shares an interpreter, so the token defends against bugs and accidental publishes (which it has genuinely caught -- the redelivery/replay case) rather than against a compromised peer; meanwhile the decisions it seals are made on unverified inputs (finding above) and the effects it gates run unconfined (findings above).",
    "evidence": [
      "simorgh/contracts/security.py:37-58 HMAC over action_id|tool|args_sha|expiry; verifier.py:43-57",
      "simorgh/kernel/registry.py:50 `NEEDS_HMAC_SECRET = {\"guardian\",\"execution\"}` -- the secret is scoped, which is the right shape, but a Worker (kernel/service.py:604-641) is a separate process only in the multi-process configuration",
      "simorgh/guardian/service.py:139-157 the dedupe map exists because a redelivered proposal minted a second token that then tripped the replay guard -- the mechanism catches ordinary faults"
    ],
    "why_it_matters": "Not wrong, and cheap; but the creator should not read 'HMAC re-verified by Execution' as the safety story. It proves the executed action is the approved action; it says nothing about whether the approval was sound or the effect bounded.",
    "recommendation": "Keep it, document its actual threat model in one sentence ('proves what ran is what was approved; not a defence against in-process code'), and spend the next effort on process confinement, which is where the missing boundary is.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read HMAC token and verifier code | """Approval tokens and subsystem tokens (docs/blueprint/03 section 10; 02 section 3). An approval token binds a Guardian decision to the *exact* action it appro |
| 2 | Bash | Read verifier, registry, worker and guardian dedupe code | class ApprovalVerifier: def __init__(self, secret: bytes, *, replay_guard: security.ReplayGuard \| None = None) -> None: self._secret = secret self._replay = rep |
| 3 | Bash | Check secret scoping, runtime mode, and known findings | simorgh/kernel/context.py:68: hmac_secret: bytes, simorgh/kernel/context.py:69: needs_hmac_secret: frozenset[str], simorgh/kernel/context.py:103: self._hmac_sec |
| 4 | Bash | Check which subsystems each process hosts and the live runtime mode | class KernelBootError(RuntimeError): pass def _bus_config_for(config: LoadedConfig, runtime: RuntimeConfig): """Shared by `Kernel` and `WorkerKernel` so both pr |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact checks out against the code as it is today, and the claim is not in the known-findings list (the existing reviews praise the HMAC as "a stellar security pattern" / "architecturally sound" without stating its threat model). The token is exactly HMAC-SHA256 over action_id|tool|args_sha256|expiry (contracts/security.py:38-40) verified constant-time plus expiry (43-58) and replay-guarded (execution/verifier.py:35-55). The secret is scoped to guardian+execution via NEEDS_HMAC_SECRET (kernel/registry.py:50) and ContextFactory (kernel/context.py:119-121), but that scoping is a lookup discipline, not a process boundary: both services store the raw bytes on `self._secret` (guardian/service.py:165, execution/service.py:142) inside the same interpreter as every other subsystem. The live deployment is single-process: ~/.simorgh/simorgh.toml has no [runtime] section, so mode defaults to "single" (kernel/api.py:34). The claim is actually slightly stronger than stated: even in local-multi, WorkerKernel hosts only Orchestration with hmac_secret=b"" (kernel/service.py:606-641), so Guardian and Execution co-reside in the kernel process in every mode and the approval token never crosses a process boundary; only the subsystem-identity tokens (IdentityRegistry, service.py:173) do. The dedupe map's own comment (guardian/service.py:139-157) confirms the mechanism's real catch was an at-least-once redelivery minting a second token that tripped the replay guard, i.e. an ordinary fault, not an adversary. Minor citation drift: the verifier logic is at verifier.py:35-55, not 43-57. The parts of the claim that lean on other findings (unverified inputs upstream, unconfined effects downstream) are cross-references I did not independently re-verify, but the core assertion about what the HMAC does and does not prove stands. Classification as (a) a correct-but-over-read mechanism at low severity is fair; the recommendation (keep it, state its threat model, work on confinement) follows.

### evidence

- simorgh/contracts/security.py:38-40 `approval_token` = HMAC-SHA256 over "action_id|tool|args_sha256|expiry"; :43-58 `verify_approval_token` constant-time compare + expiry; :61-70 `ReplayGuard`
- simorgh/execution/verifier.py:35-55 `ApprovalVerifier.verify` recomputes args sha, checks expiry, signature, then replay (line range in the finding was 43-57; substance identical)
- simorgh/kernel/registry.py:50 `NEEDS_HMAC_SECRET: frozenset[str] = frozenset({"guardian", "execution"})`
- simorgh/kernel/context.py:119-121 scoping is a name-allowlist on the Context's secret store (`allowed.add("__hmac__")`, `HmacSecretStore`), not a process boundary
- simorgh/guardian/service.py:165 and simorgh/execution/service.py:142 both hold the raw secret as `self._secret` in the same interpreter
- simorgh/kernel/service.py:606-611 `WorkerKernel.__init__` raises unless `config.runtime.mode == "local-multi"`; :630-636 worker builds Context with `hmac_secret=b"", needs_hmac_secret=frozenset()` and only for "orchestration" -- Guardian and Execution are never split into separate processes in any mode
- simorgh/kernel/api.py:34 `mode: str = "single"`; `grep -n '^\[runtime\]' ~/.simorgh/simorgh.toml` returns nothing, so the live system runs single-process
- simorgh/guardian/service.py:139-157 comment: duplicate `action.proposed` "was decided twice and minted a second token. The second token then failed Execution's replay guard ... a tamper alarm that fires on ordinary redelivery is worse than no alarm"
- docs/architecture-audit-2026.md:8 and docs/architecture-third-opinion-2026-09-18.md:18,70-71 describe the HMAC only as a strength; no prior review states its threat model, so this is not a repeat

**severity adjustment:** keep

**corrected claim:** The approval token is HMAC-SHA256 over action_id|tool|args_sha256|expiry, minted by Guardian and re-verified (with a replay guard) by Execution, and the secret is allow-listed to those two subsystems. But Guardian and Execution live in the same Python process in every runtime mode -- the live config runs "single", and even "local-multi" only moves Orchestration into workers (kernel/service.py:630-636), keeping Guardian and Execution together with the raw secret on each service's `self._secret`. So the token proves that what Execution ran is the exact action Guardian approved and defends against bugs and redelivery (the one case it has demonstrably caught, guardian/service.py:139-157), not against in-process code; it says nothing about whether the approval was sound or the effect bounded.

