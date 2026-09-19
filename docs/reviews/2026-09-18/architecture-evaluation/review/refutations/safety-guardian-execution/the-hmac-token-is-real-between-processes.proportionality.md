# refute:proportionality:The HMAC token is real between processes

*Workflow: review · Phase: Refute · Agent id: `a55a90c0dae70b344` · Tool calls: 7*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "safety-guardian-execution". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 2 | Bash | Read verifier, registry secret scoping, worker spawn, guardian dedupe | """Execution's own, independent verification of an `action.approved` message (08-execution.md section 5.1): token verification at the executor, not only at the  |
| 3 | Bash | Check runtime mode, secret scoping, and how tools execute | --- toml runtime --- 27:model = "qwen3:4b-instruct" 32:vision_model = "qwen2.5vl:3b" --- default mode --- 79: "mode": str, "data_dir": str, "deployment": str, " |
| 4 | Bash | Check default runtime mode, sim.sh, subprocess usage, container, secret scoping | --- default mode value --- 84:_VALID_MODES = ("single", "local-multi", "aws") --- toml runtime section? --- 1:[voice] 15:[interface] 18:[execution] 22:[cognitio |
| 5 | Bash | Confirm default single mode and run_shell access | --- toml has [runtime]? --- 0 --- shell tool: run_shell full access --- """Real shell access, through Guardian rather than around it. The creator, 2026-09-07: " |
| 6 | Bash | Confirm default mode and whether threat model is already stated | default mode: single --- who else could read the secret in-process --- (eval):4: no matches found: --include=*.py --- is the threat model already documented? -- |
| 7 | Bash | Read blueprint statement on single-mode identity and bus enforcement caveat | ## 10. Security - The Kernel generates a per-run secret; `approval_token`s are HMAC-SHA256 over the canonical action; Execution verifies before running; tokens  |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out and the live configuration confirms the premise. The HMAC covers action_id|tool|args_sha|expiry (simorgh/contracts/security.py:37-39) and Execution recomputes it plus the args hash against the ledger's own `received` event (simorgh/execution/verifier.py:36-57). The secret is scoped to guardian+execution via NEEDS_HMAC_SECRET (simorgh/kernel/registry.py:50) and served only from memory by HmacSecretStore (simorgh/kernel/context.py:146-158). But `RuntimeConfig.mode` defaults to "single" (python -c prints `default mode: single`), ~/.simorgh/simorgh.toml has no [runtime] section (grep -c returns 0), so in the creator's actual deployment Guardian, Execution, Cognition and every other subsystem share one interpreter; `ReservedTopologyPolicy` identities are even set to None in single mode (simorgh/kernel/service.py:173). The Worker process only exists under local-multi (kernel/service.py:604-608), and there it gets hmac_secret=b"" (line 640) — so cross-process the token is meaningful, in-process it is a guard against bugs and forged/replayed publishes, exactly as the finding says. The guardian dedupe comment (simorgh/guardian/service.py:131-150) confirms the mechanism's real-world catches have been redelivery faults, not adversaries. The effects it gates are unconfined by the creator's explicit request: shell.py:3-4 quotes "give sim file system write access and shell access" and shell.py:23-28 states plainly the refusal list is "not an attempt at a security boundary". Severity is correctly low and the kind (over-engineering / overclaimed) is fair: security.py:8-10 calls the token "the structural half of 'nothing executes because a model decided it should'", which overstates what an in-process HMAC buys. On the skeptic lens: the recommendation to keep it and add one sentence is proportionate. The pointer to "spend the next effort on process confinement" is the only disproportionate part at one-laptop/one-family scale: `run_container` already provides a confined lane (execution/container.py:1-25), and run_shell is unconfined by design the creator asked for, so a general confinement effort would be more work than it saves; that nuance does not refute the claim, it narrows the recommendation.

**corrected claim:** The HMAC token is a real boundary only across processes (local-multi/aws), and the creator runs `single` mode by default with no [runtime] override; in-process it catches bugs, forged publishes and redelivery replays rather than a compromised peer, and it says nothing about whether Guardian's inputs were sound or the effect (run_shell, by the creator's own request unconfined) was bounded. Keep it, correct the docstring's overclaim in security.py:8-10 with one sentence; a confined lane (run_container) already exists, so a broader process-confinement effort is optional at this scale.

### evidence

- simorgh/contracts/security.py:37-39 — approval_token = HMAC-SHA256 over action_id|tool|args_sha256|expiry
- simorgh/contracts/security.py:8-10 — docstring claims token is 'the structural half of nothing executes because a model decided it should' (overclaim in-process)
- simorgh/execution/verifier.py:36-57 — ApprovalVerifier recomputes args hash, expiry, HMAC, then ReplayGuard.consume
- simorgh/kernel/registry.py:50 — NEEDS_HMAC_SECRET = {guardian, execution}
- simorgh/kernel/context.py:146-158 — HmacSecretStore serves __hmac__ from memory only
- simorgh/kernel/service.py:173 — `identities = IdentityRegistry(...) if self.runtime.mode != "single" else None`: no bus identity enforcement in single mode
- simorgh/kernel/service.py:604-608, 640-641 — Worker process only under local-multi; its ContextFactory gets hmac_secret=b"", needs_hmac_secret=frozenset()
- simorgh/kernel/config.py:84 — _VALID_MODES = (single, local-multi, aws); `python3 -c 'from simorgh.kernel.config import RuntimeConfig; print(RuntimeConfig.mode)'` -> `single`
- `grep -c '^\[runtime\]' ~/.simorgh/simorgh.toml` -> 0 (live config runs default single mode)
- simorgh/guardian/service.py:131-150 — _decided dedupe added because a redelivered proposal minted a second token that tripped Execution's replay guard (observer 2026-09-10)
- simorgh/execution/shell.py:3-4, 23-28 — creator requested shell access; refusal list 'Not an attempt at a security boundary'
- simorgh/execution/container.py:1-25 — run_container already provides a confined execution lane (no repo bind mount, read-only, pids/mem caps)

**severity adjustment:** keep

