# refute:correctness:The reversibility taxonomy has had no ru

*Workflow: review · Phase: Refute · Agent id: `aff0c6592871700fe` · Tool calls: 18*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "The reversibility taxonomy has had no runtime effect: 0 escalations in 26,737 decisions",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "Across every recorded action the decision kinds are approved 26,703 and denied 34 with no escalation, so the three-tier label the tool layer maintains in three places has changed nothing for nine days; its one consumer (ReversibilityRule) is switched off by the deployment's auto-approve default and `[execution] shell = True` is the code default.",
    "evidence": [
      "Ledger measured: `decisions: Counter({'approved': 26703, 'denied': 34})`; irreversible tools approved: run_shell 561, run_script 45, install_package 17, sim_command 11, cam_siren 5",
      "simorgh/guardian/rules.py:720-739 ReversibilityRule: escalates only when `ctx.config.irreversible_requires_human`; simorgh/guardian/config.py:157 flips it from SIMORGH_GUARDIAN_AUTO_APPROVE",
      "simorgh/execution/config.py:193 `shell: bool = True` ('the creator: give sim file system write access and shell access'); run_shell is the most-used effecting tool (570 calls) and is declared irreversible",
      "contracts/home/policy.py docstring: 'sim.sh auto-approves irreversible actions by default. For the house that default is wrong, and `human` here is meant to survive it' - but home_call has been proposed once, and Guardian never applies the policy (see finding 1)"
    ],
    "why_it_matters": "This is the creator's chosen posture, so the gate itself is not the bug; the waste is that the label is treated as the tool layer's main safety contract while its only effect is nil. Meanwhile the things the label could drive for free - recording a `before` state so reversible tools are actually undoable, verification rigor (verification/rigor.py already reads it), a spoken confirmation for `human`-class house calls even under auto-approve - are not wired to it.",
    "recommendation": "Keep auto-approve, but give the label consumers that run in that posture: (a) ReversibilityRule escalates `human`-class house calls and `notify` regardless of the boolean (a tiny always-human set, already sketched in guardian config's `always_human`); (b) for reversible tools, Execution captures `before` in metadata automatically (home_undo already expects it) so undo is uniform; (c) drop the pretence elsewhere: if `shell = True` is the default, say so in the tool's description hint. One afternoon.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the cited guardian rule, config, and execution config lines |  # Tools whose args plausibly cause a model call (drafting); anything # else never checks the budget table at all -- a read_file proposal # is not slowed down b |
| 2 | Bash | Check deployment config, sim.sh env, guardian mode fields, rigor consumer, home policy docstring, and ledger layout | 12:expressive_lane = "auto" 13:stt = "auto" 27:model = "qwen3:4b-instruct" 32:vision_model = "qwen2.5vl:3b" ---sim.sh--- ---mode--- 84: mode: str = "guarded" #  |
| 3 | Bash | Find where auto-approve is set, whether always_human exists, and list ledger streams | tests/simorgh/execution/security/test_security.py:202: env_override="SIMORGH_GUARDIAN_AUTO_APPROVE") tests/simorgh/execution/security/test_security.py:203: self |
| 4 | Bash | Check whether sim.sh or simloader sets auto-approve and how guardian records decisions | 22:export SIMORGH_EXECUTION_REPO_ROOT="${SIMORGH_EXECUTION_REPO_ROOT:-$REPO_ROOT}" 26:export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="${PROTOCOL_BUFFERS_PYTHON_I |
| 5 | Bash | Read the deployment toml, find who sets auto-approve, and read how Guardian emits decisions | [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2.8 min_confidence =  |
| 6 | Bash | Find who sets auto-approve outside guardian config and how escalate maps to needs_human | ---env-setters--- simorgh/execution/remote.py:29: what it did. With `irreversible_requires_human` set, every call waits. simorgh/execution/shell.py:16: `Reversi |
| 7 | Bash | Read where the kernel flips auto-approve on and how the pipeline turns escalate into needs_human |  # The Kernel's own client is built directly (not through # `ContextFactory.build`, which self-authenticates every other # subsystem) -- it needs the same treat |
| 8 | Bash | Inspect one action stream's event shape and count action streams | {"causation_id":null,"idempotency_key":null,"payload":{"proposal":{"action_id":"00058d0478bb","args":{"action":"offer","camera":"Garden","sdp":"blob:731ac8ac382 |
| 9 | Bash | Count Guardian decision kinds, layers, reversibility class, and irreversible-approved tools across all action streams | decided kinds Counter({'approved': 26703, 'denied': 34}) by (kind,layer) [(('approved', ''), 26703), (('denied', 'denylist'), 15), (('denied', 'protected'), 12) |
| 10 | Bash | Count home/siren/shell proposals with their labels, find rigor consumers, where the label is declared, and home_undo's before-state | Counter({('run_shell', 'irreversible'): 570, ('cam_siren', 'reversible'): 5, ('home_call', 'reversible'): 1}) ---rigor consumer--- simorgh/verification/service. |
| 11 | Bash | Check whether verification rigor differs by reversibility and where the label is declared | 42- default_factory=lambda: {k: _rigor(v) for k, v in _DEFAULT_RIGOR_BY_KIND.items()} 43- ) 44: rigor_by_reversibility: dict[str, Rigor] = field( 45- default_fa |
| 12 | Bash | Check rigor defaults per reversibility, how verification learns a subject's reversibility, and which non-action streams exist | 14:_DEFAULT_RIGOR_BY_KIND = { 15- "chat": "NONE", 16- "research": "LIGHT", 17- "project_child_readonly": "LIGHT", 18- "skill": "FULL", 19- "patch": "FULL", 20-  |
| 13 | Bash | Check what reversibility verification actually sees at runtime, who builds verify subjects, and whether Execution itself acts on the label | ---verify streams--- ---subject_ref publishers--- simorgh/learning/service.py:203: subject_ref: str, checklist_hint: str) -> None: simorgh/learning/service.py:2 |
| 14 | Bash | Check whether the verify subject blob carries reversibility and whether rigor is recorded anywhere | Exit code 1 29: { ---verify stream sample--- -rw-r--r-- 1 saeed staff 3149 Sep 11 21:40 /Users/saeed/.simorgh/ledger/streams/verify%3A00a322a83957.jsonl {"causa |
| 15 | Bash | Read the verify-subject builder, check whether rigor is recorded, and whether learning's subject carries a reversibility label |  """`verify.requested.subject_ref` is a blob ref, not raw text -- Verification's `_resolve_subject` reads it with `ledger.get_blob` and expects a JSON object wi |
| 16 | Bash | Check whether verify subjects ever carry a reversibility key, whether Execution snapshots before-state, and whether prior reviews already co | 10: payload = json.dumps({ 11: "description": session.user_text, "result": text[:2000], "kind": session.kind, "steps": steps, 18: return await self._ledger.put_ |
| 17 | Bash | Confirm the verify subject payload keys and read the prior review's context on reversibility and auto-approve |  payload = json.dumps({ "description": session.user_text, "result": text[:2000], "kind": session.kind, "steps": steps, "complete_log": complete_log, "subject":  |
| 18 | Bash | Confirm the kernel's auto-approve baseline reaches Guardian config at runtime, and what rigor Verification actually gets when reversibility  | 141: def section(self, name: str) -> dict[str, Any]: 142- value = self.raw.get(name, {}) 143- return dict(value) if isinstance(value, Mapping) else {} 144- 145- |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core claim survives verification: I re-counted every action stream in ~/.simorgh/ledger/streams (26,737 `action:*` streams, 2026-09-09 21:27 to 2026-09-17 21:20, i.e. 8.0 days) and the `decided` events are exactly approved 26,703 / denied 34 / needs_human 0; 670 of the approvals were for proposals labelled `irreversible` (run_shell 561, run_script 45, worktree_land 35, install_package 17, sim_command 11, run_container 1). The denials came only from denylist (15), protected (12) and paused (7); ReversibilityRule never produced a verdict. The reason is real and current: guardian/rules.py:738 escalates only when `ctx.config.irreversible_requires_human`, and although the dataclass default is True (guardian/config.py:103) the running Kernel overrides it — kernel/service.py:202-203 does `guardian_section.setdefault("irreversible_requires_human", False)` before building GuardianConfig at :218, and the live ~/.simorgh/simorgh.toml has no `[guardian]` table and sim.sh sets no SIMORGH_GUARDIAN_AUTO_APPROVE. So the deployed system is auto-approve by code default, not by env var. Note the prior review (docs/architecture-review-2026-09-18.html) stated the opposite ("shipped default is True... not in the live environment"), so the measured nil effect is materially new rather than a repeat. `shell: bool = True` at execution/config.py:193 is confirmed, and run_shell is labelled irreversible at execution/shell.py:187.

Where the finding is wrong or imprecise: (1) it cites guardian/config.py:157 as the flip, but that line only handles the env var, which is unset; the live switch is kernel/service.py:203. (2) `cam_siren` is labelled `reversible`, not irreversible (5 proposals, all reversible), so it does not belong in the irreversible-approved list; ironically that strengthens the thesis, since even with auto-approve off the siren would never prompt. (3) "its one consumer" is wrong: verification/rigor.py:24 and verification/service.py:162-164 are a second consumer, but a dead one — the verify subject blob built at orchestration/session.py:1884-1891 carries no `reversibility` key, so `subject.get("reversibility", "reversible")` always yields "reversible" and rigor is effectively by kind only (a `python -c` run shows research → standard, not light, because max(LIGHT, STANDARD)). That is a small genuine bug the finding did not name. (4) "nine days" is eight. (5) home_call proposed once and labelled reversible: confirmed; home tools already record `before` (execution/home/tools.py:290-299), Execution generically does not (no snapshot/before handling in execution/service.py).

Overlap with known findings: "sim.sh auto-approve flips one boolean" and the prior review's "tiered safety: sirens and locks always human" cover recommendation (a) in spirit, but the measured zero-effect across the whole ledger and the dead verification consumer are new. Classification as right-design-undermined is fair; severity medium is appropriate.

**corrected claim:** Across all 26,737 recorded action decisions (2026-09-09 to 2026-09-17, 8 days) Guardian recorded approved 26,703 / denied 34 / needs_human 0; the reversibility label never changed a verdict. Its Guardian consumer (ReversibilityRule, guardian/rules.py:738) is switched off not by SIMORGH_GUARDIAN_AUTO_APPROVE (unset; sim.sh does not export it) but by the Kernel's code baseline kernel/service.py:203 `setdefault("irreversible_requires_human", False)`, with no `[guardian]` table in the live simorgh.toml. Its second consumer, Verification's select_rigor (verification/rigor.py:24), is also inert because the verify subject blob (orchestration/session.py:1884-1891) never carries a `reversibility` key, so rigor is decided by kind alone. 670 irreversible-labelled proposals were auto-approved (run_shell 561, run_script 45, worktree_land 35, install_package 17, sim_command 11, run_container 1); cam_siren and home_call are labelled `reversible`, so they would not prompt even with auto-approve off. `[execution] shell = True` is the code default (execution/config.py:193).

### evidence

- Ledger scan of ~/.simorgh/ledger/streams/action%3A* (26,737 files): decided kinds Counter({'approved': 26703, 'denied': 34}); by (reversibility, kind): reversible/approved 24402, read_only/approved 1631, irreversible/approved 670, irreversible/denied 21, reversible/denied 12, read_only/denied 1; denial layers: denylist 15, protected 12, paused 7; span 2026-09-09 21:27 to 2026-09-17 21:20 (7.995 days); zero needs_human
- Irreversible-labelled proposals approved, by tool: run_shell 561, run_script 45, worktree_land 35, install_package 17, sim_command 11, run_container 1. cam_siren: 5 proposals all labelled 'reversible'; home_call: 1 proposal labelled 'reversible'
- simorgh/guardian/rules.py:724-739 ReversibilityRule: irreversible -> 'escalate' only if ctx.config.irreversible_requires_human, else 'allow'; simorgh/guardian/pipeline.py:41-47 turns escalate into Verdict('needs_human') unless the classifier says ALLOW
- simorgh/kernel/service.py:202-203: guardian_section = self.config.section('guardian'); guardian_section.setdefault('irreversible_requires_human', False); :218 GuardianConfig.from_mapping(guardian_section). `python3 -c` with env unset: Config().irreversible_requires_human == True, Config.from_mapping({'irreversible_requires_human': False}) == False, mode default 'guarded'
- `grep -n -i -E 'guardian|approve|export' sim.sh` -> only SIMORGH_EXECUTION_REPO_ROOT and PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION; ~/.simorgh/simorgh.toml has no [guardian] table (sections: voice, interface, execution, cognition)
- simorgh/execution/config.py:193 `shell: bool = True` with the 2026-09-07 creator quote; simorgh/execution/shell.py:187 `reversibility = "irreversible"`
- simorgh/verification/rigor.py:24 by_reversibility = config.rigor_by_reversibility.get(req.reversibility, Rigor.STANDARD); simorgh/verification/service.py:162 reversibility=subject.get('reversibility', 'reversible'); simorgh/orchestration/session.py:1884-1891 subject blob keys are description/result/kind/steps/complete_log/subject/written_paths/base_ref/repo_root (no reversibility); python -c select_rigor with the defaulted 'reversible': task standard, research standard, chat standard, self_patch full
- simorgh/contracts/home/policy.py:22-23 docstring: 'sim.sh auto-approves irreversible actions by default. For the house that default is wrong, and `human` here is meant to survive it.'; simorgh/execution/home/tools.py:290-299 home_call records `before` in metadata; :311-317 home_undo reads it; `grep -rn 'snapshot|"before"' simorgh/execution/service.py` -> no matches (no generic before-capture)
- docs/architecture-review-2026-09-18.html states 'The shipped default is irreversible_requires_human: bool = True ... not in the live environment' — contradicted by kernel/service.py:203, so the measured auto-approve posture is new relative to the prior review; its item 6 ('sirens and locks always human') overlaps recommendation (a)

**severity adjustment:** keep

