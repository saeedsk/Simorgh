# refute:proportionality:Live default auto-approves every irrever

*Workflow: review · Phase: Refute · Agent id: `ae19d95b58b1d816f` · Tool calls: 12*

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
| 1 | Bash | Read kernel guardian defaults, live toml sections, env, classify_call users |  self.bus = make_bus_client(self._bus_backend, source="kernel", ledger=self.ledger, clock=self._clock.now, policy=policy) # `sim.sh`'s own default, deliberately |
| 2 | Bash | Read home policy and HomeCallTool execution path | ---policy--- """How dangerous is this service call? A pure function, in contracts, so Guardian and the tool that proposes the call compute the same answer from  |
| 3 | Bash | Read proposal reversibility wiring, Guardian rules, sim.sh switch, live execution config | ---orch 685-725--- rest = _strip_code_fence(rest) args = {first: head.strip(), second: rest} if tool in _MARKER_JSON_REST: args = {first: head.strip(), **_json_ |
| 4 | Bash | Check auto-approve switch, ReversibilityRule body, denylist, tool policy, HA configuration, ledger | ---AUTO_APPROVE--- (eval):1: no matches found: --include=*.py ---ReversibilityRule--- class ReversibilityRule: name = "reversibility" layer = "reversibility" as |
| 5 | Bash | Locate auto-approve env handling, live HA/camera secrets keys, ledger evidence of house calls, Guardian escalate path | ---AUTO_APPROVE--- simorgh/execution/security/tools.py:192: raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip() simorgh/execution/security/ |
| 6 | Bash | Check ledger outcomes for siren and home calls, siren tool gates, Guardian trust of proposer label, prompt wiring | ---ledger cam_siren outcomes--- /Users/saeed/.simorgh/ledger/streams/execution%3Ainflight.jsonl /Users/saeed/.simorgh/ledger/streams/action%3A7422804c0982.jsonl |
| 7 | Bash | Read siren action decision record, Guardian proposal reconstruction, locate siren tool and tests | ---cam_siren decided--- "type":"decided"} "type":"verified"} ---guardian 495-535--- # unbounded map is a leak in a process meant to run for months # (`security. |
| 8 | Bash | Parse the recorded siren decision, list siren tool gates, find Guardian decide API for offline reproduction | ---cam_siren decided payload--- received {"camera": "Office", "seconds": 1} reversible decided {"kind": "approved", "layer": ""} verified {"outcome": true, "rea |
| 9 | Bash | Read siren tool class, list every recorded house proposal with its label, get Guardian API shapes for an offline run | ---cam_siren class--- side_effects=(f"cam_ir:{cam.channel}",)) class CamSirenTool(_CameraTool): name = "cam_siren" description = "Sound a camera's siren for a f |
| 10 | Bash | Find every proposal builder, date the siren policy, run Guardian pipeline offline on house and shell proposals | ---proposal builders--- simorgh/interface/dispatch.py:1336: "reversibility": "reversible", simorgh/learning/service.py:199: "reversibility": reversibility, "rat |
| 11 | Bash | Read the chat-side proposal builder that hardcodes reversible; check whether prior reviews already covered this | Exit code 1 ---dispatch 1300-1345--- import asyncio args = cli_tool_args(tool, raw) if "__error__" in args: return Outcome(f"error: {args['__error__']}") # No s |
| 12 | Bash | Check prior reviews for overlap, identify the CLI tool-proposal path and whether Guardian overrides proposer labels from the tool registry | ---already known--- docs/architecture-audit-2026.md:61: - **Action:** Evolve the Guardian rule engine beyond a binary `irreversible_requires_human` flag. Suppor |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is accurate today. simorgh/kernel/service.py:203 does `guardian_section.setdefault("irreversible_requires_human", False)`; ~/.simorgh/simorgh.toml has only [voice] [interface] [execution] [cognition*] sections and `env | grep SIMORGH` prints nothing, so the live default is auto-approve (this also corrects docs/architecture-third-opinion-2026-09-18.md:50/213, which says the runtime default requires a human -- it does not, because the Kernel fills the gap with False before GuardianConfig.from_mapping runs). `grep -rn classify_call simorgh/` hits only contracts/home/policy.py, execution/home/tools.py and orchestration/tools.py -- nothing in simorgh/guardian/. Guardian's `_on_proposed` (guardian/service.py:502-526) copies `p["reversibility"]` straight into both Proposal and ToolInfo, and ReversibilityRule (guardian/rules.py:724-740) reads only that label; with the switch off, an irreversible proposal returns `allow`. HomeCallTool (execution/home/tools.py:255-266) computes `worst` and calls `client.call(...)` unconditionally; `worst` lands only in metadata. An offline run of DEFAULT_PIPELINE with Config(irreversible_requires_human=False) approved home_call lock.unlock, cam_siren and run_shell exactly as the finding says.

Materially new, and worse than the finding states: the proposer's label is trusted, not recomputed, on EVERY path. interface/dispatch.py:1331-1336 (`_run_tool`, the path `cam siren`/`ring siren` typed at the terminal takes, lines 1016-1028/1122-1131) hardcodes `"reversibility": "reversible"` with a comment claiming "Guardian recomputes the real class itself and never trusts a proposer's label" -- it does not. The ledger confirms it: all five recorded cam_siren proposals (2026-09-15, action:7422804c0982 etc.) carry `reversibility: reversible`, were `decided: approved, layer ""` and `verified: outcome true`, so they would be auto-approved even with the switch ON. The same false promise appears at orchestration/tools.py:698 and contracts/home/policy.py:2-6. So the real design property ("Guardian computes the class from args; the proposer cannot understate it") is asserted in three docstrings and implemented in none -- a textbook instance of this project's unconnected-wire bug shape, category (b): right design, implementation undermines it.

Skeptic lens / scale: the door-lock headline is hypothetical TODAY -- ~/.simorgh/secrets.toml contains REOLINK_HOST and RING_TOKEN but no HOME_ASSISTANT_URL/HOME_ASSISTANT_TOKEN, so `home_call lock.unlock` is refused at `client.configured` (contracts/home/client.py:50, 180) before classification is even reached. Sirens, however, are live and have been fired. The recommendation is proportionate: a ~20-line Guardian rule calling the pure function that already exists plus a two-line refusal in HomeCallTool; it creates no ongoing work and the creator's deliberate auto-approve for code work is untouched. The "split the boolean" half of the recommendation is already-known (docs/architecture-audit-2026.md:61, architecture-review-2026-09-18.html:245, third-opinion:175). Severity: lower from critical to high, because the front door is not reachable in the live config and the creator explicitly chose auto-approve for code; keep it high because the physical-world gate is documented as surviving the switch and does not, and because the CLI path bypasses the switch entirely.

### evidence

- simorgh/kernel/service.py:202-203 `guardian_section = self.config.section("guardian"); guardian_section.setdefault("irreversible_requires_human", False)`; comment at :188-201 says this is sim.sh's deliberate default
- `grep -n '^\[' ~/.simorgh/simorgh.toml` -> [voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]; no [guardian]. `env | grep -i SIMORGH` -> nothing
- `grep -rn classify_call simorgh/` -> contracts/home/__init__.py, contracts/home/policy.py, execution/home/tools.py:30,255, orchestration/tools.py:700,702; zero hits under simorgh/guardian/
- simorgh/guardian/service.py:502-505 `proposal = Proposal(... reversibility=p["reversibility"] ...)` and :521-526 `tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)` -- the proposer's label is used verbatim
- simorgh/guardian/rules.py:724-740 ReversibilityRule: `if ctx.config.irreversible_requires_human: return Decision("escalate", ...)` else `Decision("allow", ...)`; :743-756 it is the last rule in DEFAULT_PIPELINE and no home/siren rule exists
- simorgh/execution/home/tools.py:255-266 computes `classes`/`worst` then `result = await client.call(service, entity_ids=..., data=data, ...)` with no check on `worst`; `worst` only appears in metadata at :279 and :300
- simorgh/interface/dispatch.py:1331-1336 `_run_tool` publishes ACTION_PROPOSED with hardcoded `"reversibility": "reversible"` and the comment "Guardian recomputes the real class itself and never trusts a proposer's label"; :1016-1028 and :1122-1131 route `cam siren` / `ring siren` through it
- Ledger: python parse of ~/.simorgh/ledger/streams/action:*.jsonl -> five cam_siren proposals (ts 1789428514..1789428575, cameras Office/Parking/Pool) all with reversibility="reversible"; action:7422804c0982 events: received -> decided {kind: approved, layer: ""} -> verified {outcome: true}
- simorgh/orchestration/tools.py:191 `"cam_siren": ("irreversible", True)`, :206 `"ring_siren": ("irreversible", True)`, :83/85/86 run_shell/install_package/run_script irreversible; :693-703 home_call label computed by orchestration via classify_call/reversibility_of (honest on the model path, but still proposer-supplied)
- Offline pipeline run (python, no boot, no model): requires_human=False -> home_call lock.unlock approved, cam_siren approved, run_shell approved; requires_human=True -> those escalate to needs_human EXCEPT cam_siren labelled reversible, which is still approved
- `grep -o 'HOME_ASSISTANT_[A-Z]*|REOLINK_HOST|RING_TOKEN' ~/.simorgh/secrets.toml | sort -u` -> REOLINK_HOST, RING_TOKEN only; simorgh/contracts/home/client.py:46,50,180 refuses home_call when HOME_ASSISTANT_URL/TOKEN are missing, so lock.unlock is unreachable in the live config
- Prior coverage: docs/architecture-audit-2026.md:61 and docs/architecture-review-2026-09-18.html:245 already recommend per-class gates ('sirens and locks always human'); docs/architecture-third-opinion-2026-09-18.md:50,213 wrongly states the runtime default requires a human

**severity adjustment:** lower

**corrected claim:** With the live config the Kernel defaults irreversible_requires_human to False, and Guardian never recomputes classify_call -- it copies whatever reversibility label the proposer sent (guardian/service.py:504,525). So on the model path (orchestration labels lock.unlock/sirens 'irreversible') sirens, run_shell etc. are approved with nobody asked; and on the terminal path (interface/dispatch.py:1336 hardcodes 'reversible' for every typed tool, including cam/ring siren) they would be approved even with the switch ON -- the ledger shows five sirens fired that way on 2026-09-15. HomeCallTool computes the 'human' class but never refuses on it. The door lock specifically is not reachable today because Home Assistant is not configured (no HOME_ASSISTANT_URL/TOKEN in secrets.toml); Reolink and Ring sirens are. The fix is small and proportionate (a Guardian rule over the existing pure function + a refusal in HomeCallTool); splitting the boolean into code/world gates was already recommended by earlier reviews.

