# refute:correctness:Live default auto-approves every irrever

*Workflow: review · Phase: Refute · Agent id: `a60fe7a67a49483c4` · Tool calls: 6*

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
    "title": "Live default auto-approves every irreversible action, so the door lock, sirens and shell run with no human in the loop",
    "kind": "wrong-design",
    "severity": "critical",
    "claim": "With the live config (no `[guardian]` section in ~/.simorgh/simorgh.toml) the Kernel sets `irreversible_requires_human=False` (kernel/service.py:203), Guardian has no house-specific rule and does not recompute `classify_call`, and `HomeCallTool` computes the `human` class but never refuses on it, so `home_call lock.unlock`, `cam_siren`, `ring_siren`, `run_shell`, `run_script` and `install_package` are all approved with nobody asked.",
    "evidence": [
      "simorgh/kernel/service.py:203 `guardian_section.setdefault(\"irreversible_requires_human\", False)`",
      "~/.simorgh/simorgh.toml has sections [voice] [interface] [execution] [cognition] and no [guardian]; `env | grep SIMORGH` prints nothing",
      "`grep -rn classify_call simorgh/` -> only contracts/home/policy.py, execution/home/tools.py, orchestration/tools.py; nothing in simorgh/guardian/",
      "simorgh/contracts/home/policy.py:22-24 promises \"`sim.sh` auto-approves irreversible actions by default. For the house that default is wrong, and `human` here is meant to survive it\" -- no code implements the survival",
      "simorgh/execution/home/tools.py:255-266 computes `worst` then calls `client.call(...)` unconditionally; `worst` only lands in metadata",
      "Offline pipeline run with Config(irreversible_requires_human=False): `approved  home_call: {'service': 'lock.unlock', ...}`, `approved  cam_siren: {...}`, `approved  run_shell: {'command': 'cat ~/.simorgh/secrets.toml'}`"
    ],
    "why_it_matters": "One boolean, defaulted off by the launcher, is the only thing standing between the model and unlocking the front door or exfiltrating the vault. The design intent (physical-world 'human' class survives auto-approve) is written in a docstring and nowhere else.",
    "recommendation": "Make `human`-class house calls a Guardian rule that ignores `irreversible_requires_human`: add a `HomeSafetyRule` that calls `classify_call` on `home_call` args (the pure function already exists for exactly this reason) and returns `escalate` regardless of the switch; have `HomeCallTool` refuse `worst == \"human\"` unless the approval carried a `human_approved` constraint. Separately, split the one boolean into two: `code_irreversible_requires_human` and `world_irreversible_requires_human`, default the second to True in the Kernel.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read kernel default, live config sections, env, classify_call uses |  self.bus = make_bus_client(self._bus_backend, source="kernel", ledger=self.ledger, clock=self._clock.now, policy=policy) # `sim.sh`'s own default, deliberately |
| 2 | Bash | Read home policy, HomeCallTool execute path, orchestration reversibility hook | ---POLICY--- """How dangerous is this service call? A pure function, in contracts, so Guardian and the tool that proposes the call compute the same answer from  |
| 3 | Bash | Check Guardian rules for home handling, tool policy labels, sim.sh switch, and prior reviews | ---GUARDIAN-GREP--- (eval):1: no matches found: --include=*.py ---REVRULE--- 720:class ReversibilityRule: 721- name = "reversibility" 722- layer = "reversibilit |
| 4 | Bash | Check when the kernel default landed, env override path, Guardian files, prior review text, and effective live value | ---BLAME--- 8b0197f Wire simorgh.toml's [guardian] section, default sim.sh to auto-approve 8b0197f 2026-09-07 Wire simorgh.toml's [guardian] section, default si |
| 5 | Bash | Confirm no house rule in Guardian and that the computed safety class is consumed nowhere | simorgh/guardian/api.py:58: classify: Callable[[Proposal], Awaitable[str \| None]] \| None = None # None \| "ALLOW"/"DENY"/"ASK" simorgh/guardian/pipeline.py:40: i |
| 6 | Bash | Check whether the Guardian classifier hook is on by default | 5:finding`/`task.*` and feeds `Posture.tighten`); `classifier_enabled` 103: irreversible_requires_human: bool = True 105: classifier_enabled: bool = False # cog |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact holds against the code today. (1) simorgh/kernel/service.py:202-203 does `guardian_section.setdefault("irreversible_requires_human", False)` on the section read from simorgh.toml, and the comment (lines 188-201) says this is deliberate: sim.sh's real default is auto-approve, overridable only by `[guardian]` in the toml or `SIMORGH_GUARDIAN_AUTO_APPROVE=0`. The live toml has sections [voice] [interface] [execution] [cognition] and no [guardian]; `env | grep SIMORGH` shows nothing. Reproducing the Kernel's exact steps offline gives `live effective: False | dataclass default: True`. (2) Guardian has no house rule: DEFAULT_PIPELINE (guardian/rules.py:743-756) ends in ReversibilityRule, which reads `proposal.reversibility` as supplied (rules.py:725) and, for "irreversible" with the flag False, returns allow (rules.py:738-740). `grep classify_call simorgh/` hits only contracts/home, execution/home/tools.py and orchestration/tools.py; nothing under simorgh/guardian/. The orchestration comment at orchestration/tools.py:697-698 ("Guardian recomputes the same answer") is therefore false today. The only other escalation path, the LLM classifier hook (pipeline.py:40), is `classifier_enabled: bool = False` by default (guardian/config.py:105) and only runs when an escalation already exists. (3) HomeCallTool computes `worst` (execution/home/tools.py:255-263) and then calls `client.call(...)` unconditionally (265-266); `worst` lands only in `metadata["safety"]`, and grep shows no consumer of that key and no `human_approved` constraint anywhere. (4) _TOOL_POLICY labels cam_siren, ring_siren, run_shell, run_script, install_package "irreversible" (orchestration/tools.py:83-86,191,206), so with the flag False they pass ReversibilityRule as allow. Denylist/protected/scope rules still run first, but none of them target a lock.unlock service call or a siren. The design intent in contracts/home/policy.py:22-24 is a docstring with no implementation behind it. This is NOT merely the known "sim.sh auto-approve flips one boolean": the prior fact-check (docs/architecture-review-2026-09-18.html:152-155, and the third-opinion doc line 50) concluded the live default is human-required and called it a documentation bug; that conclusion is wrong because it missed the Kernel's setdefault (commit 8b0197f, 2026-09-07). The audit's line 61 recommends per-class gates but does not establish the factual gap. Classification: (b) right design (pure classify_call in contracts so Guardian can recompute), undermined by implementation (nobody wires it), plus (a) one boolean covering both code and physical-world effects.

### evidence

- simorgh/kernel/service.py:202-203: `guardian_section = self.config.section("guardian")` / `guardian_section.setdefault("irreversible_requires_human", False)`; comment at 188-201 states this is sim.sh's intended default, overridable only by toml or SIMORGH_GUARDIAN_AUTO_APPROVE=0
- git log -S'setdefault("irreversible_requires_human"' -> 8b0197f 2026-09-07 "Wire simorgh.toml's [guardian] section, default sim.sh to auto-approve"
- ~/.simorgh/simorgh.toml section headers: [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama] -- no [guardian]; `env | grep -i SIMORGH` prints only PWD/OLDPWD
- python3 replaying the Kernel's steps: `live effective: False | dataclass default: True` (guardian/config.py:103 `irreversible_requires_human: bool = True`)
- simorgh/guardian/rules.py:725 `r = proposal.reversibility`; 738-740 `if ctx.config.irreversible_requires_human: return Decision("escalate", ...)` / `return Decision("allow", self.layer)`; DEFAULT_PIPELINE 743-756 contains no home/house rule
- `grep -rn classify_call simorgh/` -> contracts/home/__init__.py, contracts/home/policy.py, execution/home/tools.py:30,255, orchestration/tools.py:700,702 -- zero hits in simorgh/guardian/; `grep -i 'home|classify' simorgh/guardian/api.py simorgh/guardian/pipeline.py` hits only the generic LLM `classify` hook
- simorgh/guardian/config.py:105 `classifier_enabled: bool = False`; pipeline.py:38-47 the classifier only runs when an escalation already exists
- simorgh/orchestration/tools.py:697-698 comment "Guardian recomputes the same answer from the same pure function rather than trusting this" -- no such recomputation exists
- simorgh/contracts/home/policy.py:22-24: "`sim.sh` auto-approves irreversible actions by default. For the house that default is wrong, and `human` here is meant to survive it."
- simorgh/execution/home/tools.py:255-266: `classes = {classify_call(...)}`, `worst = ...`, then `result = await client.call(service, entity_ids=..., data=data, ...)` with no check on `worst`; `worst` appears only in `metadata={... "safety": worst ...}` at 276 and 297
- `grep -rn 'human_approved|home_always_human' simorgh/` -> only execution/config.py:420 (the always_human tuple config) and tools.py:260 (feeds classify_call); no consumer of metadata["safety"] in execution/service.py, guardian/, or orchestration/
- simorgh/orchestration/tools.py _TOOL_POLICY: run_shell:83, install_package:85, run_script:86 = ("irreversible", True); home_call:131 = ("reversible", True); cam_siren:191, ring_siren:206 = ("irreversible", True)
- docs/architecture-review-2026-09-18.html:152-155 claims "there is no [guardian] section in the live config. The shipped default is irreversible_requires_human: bool = True" and docs/architecture-third-opinion-2026-09-18.md:50 calls it "a documentation bug, not a safety bug" -- both miss kernel/service.py:203, so this finding is a material correction, not a repeat

**severity adjustment:** keep

