# refute:correctness:Physical-world tools are gated identical

*Workflow: review · Phase: Refute · Agent id: `ac28d1b4908bfb4ed` · Tool calls: 9*

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
    "title": "Physical-world tools are gated identically to code: one label, one boolean, no channel-level distinction",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "The 21 house/camera/Ring tools and 17 TV/media tools use the same `reversibility` constant and the same ReversibilityRule as file edits; `cam_setup`, `cam_stream`, `cam_ptz`, `cam_light`, `ring_setup`, `cast_*`, `tv_key` are all `reversible` and therefore never escalate in any mode; the only per-call classification is `home_call`, computed at proposal time without device_class or alarm state and then discarded by the tool.",
    "evidence": [
      "Tool enumeration: 98 tools, Counter({'reversible': 51, 'read_only': 37, 'irreversible': 10}); e.g. `cam_ptz ro=False rev=reversible`, `tv_key rev=reversible`, `cast_play rev=reversible`",
      "simorgh/orchestration/tools.py:698-704 classifies `home_call` with `args.get(\"target\")` and `data` only; execution/home/tools.py:255-262 classifies again with device_class and alarm_state, stores `worst` in metadata",
      "simorgh/guardian/rules.py:720-740 ReversibilityRule is the only place physical vs code is decided, via the same `r` string"
    ],
    "why_it_matters": "For one family on one laptop the right question is not 'can this be undone' but 'does this act on the world'. A PTZ camera pointed at a neighbour or a TV turned to full volume at 2am is reversible and still not something a chat turn should do unattended.",
    "recommendation": "Add a second axis to the tool protocol, `domain: code | world | self`, set once in each tool class, and give Guardian a `WorldRule` that escalates `world` actions from autonomous origins (curiosity/reflection/project) and lets human-originated chat ones through -- a small rule, and it reuses the `origin` field Guardian already tracks (service.py:242-244).",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read ReversibilityRule in guardian rules |  ) return Decision("abstain", self.layer) def similarity(code: str, excerpts: list[str], threshold: float) -> tuple[float, str] \| None: """Shared by `ImmunityRu |
| 2 | Bash | Read home_call classification at proposal and tool sites |  raw = _strip_code_fence(str(raw)) if tool in _MARKER_SPLIT_FIRST_LINE: first, second = _MARKER_SPLIT_FIRST_LINE[tool] head, _, rest = str(raw).partition("\n")  |
| 3 | Bash | Read origin handling in guardian service |  if not code: await self._ctx.bus.reply(message, type=topics.GUARDIAN_REVIEW_REPLY, payload={ "approved": False, "reasons": ["no code to review"], "layers_run": |
| 4 | Bash | Check what the home tool does with its per-call classification |  worst = "human" if "human" in classes else ( "reversible" if "reversible" in classes else "unattended") try: result = await client.call(service, entity_ids=tup |
| 5 | Bash | Locate the tool policy table entries for the named tools | 29:_TOOL_POLICY: dict[str, tuple[str, bool]] = { 346: # into `_TOOL_POLICY` by mistake instead of here -- a duplicate 580: return _TOOL_POLICY.get(tool, ("irrev |
| 6 | Bash | Check whether guardian rules already consider origin or a world/physical axis | simorgh/guardian/rules.py:252: # origins only -- a human-originated proposal still gets the simorgh/guardian/rules.py:254: if ctx.posture.level == "locked" and  |
| 7 | Bash | Check ModeRule origin handling, guardian recompute of home_call, and consumers of the safety metadata | class PausedRule: name = "paused" layer = "paused" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: if ctx.system_state in ("paus |
| 8 | Bash | Enumerate tool policy table counts and the named tools' labels | 105 Counter({'reversible': 54, 'read_only': 39, 'irreversible': 12}) cam_setup ('reversible', True) cam_stream ('reversible', True) cam_ptz ('reversible', True) |
| 9 | Bash | Check safety metadata consumers, the classify_call policy, irreversible tools, and always-human config wiring | ---policy--- #: Words in an entity id that mean "this is part of the security #: system", whatever its domain says. _SECURITY_WORDS = ("alarm", "siren", "securi |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core claim holds against the code today: Guardian has exactly one axis for effects, the `reversibility` string, and the ReversibilityRule (simorgh/guardian/rules.py:720-740) allows any `reversible` proposal in every mode except locked, with no notion of "acts on the world". `cam_setup`, `cam_stream`, `cam_ptz`, `cam_light`, `ring_setup`, `tv_key`, `cast_play`, `home_call`, `home_undo` are all `("reversible", True)` in `_TOOL_POLICY` (orchestration/tools.py:131-201), so a curiosity- or reflection-originated task can pan a camera or play to the TV without escalation. The only origin-aware rule is ModeRule (rules.py:246-269), which uses `proposal.origin` solely to narrow the effective mode when posture is already `locked`; grep finds no "world"/"physical"/domain axis anywhere in simorgh/guardian/. The `home_call` per-call classification at proposal time (orchestration/tools.py:694-702) passes only service, target (a friendly name, not an entity id) and data -- no device_class, no alarm_state, and not the configured `home_always_human_services` -- so a lock's device_class or an armed alarm never reaches Guardian; the code comment "Guardian recomputes the same answer" is false today (no `classify_call` import under simorgh/guardian/). The richer classification in execution/home/tools.py:255-263 is computed after approval and the tool proceeds to `client.call` at line 265 regardless of `worst`. Corrections: (1) `worst` is not literally discarded -- it is written to `ToolResult.metadata["safety"]` (lines 277-278, 297-298) -- but no other code reads that key and it never blocks or escalates, so the functional point stands; (2) the counts are off: `_TOOL_POLICY` has 105 entries, Counter reversible=54, read_only=39, irreversible=12 (the reader likely counted one profile's registered tools); (3) `cam_siren` and `ring_siren` are `irreversible`, so not every camera/Ring tool escapes escalation. This is not in the known-findings list; "sim.sh auto-approve flips one boolean" concerns the approval prompt, not the tool taxonomy. Design classification (a): a single-axis label that is right for code edits but wrong for physical devices in a one-family deployment; the recommendation (a `domain` axis plus a small origin-aware rule) is proportionate.

### evidence

- simorgh/guardian/rules.py:720-740 ReversibilityRule: `r = proposal.reversibility`; `if r == "reversible": ... return Decision("allow", ...)` unless mode == locked; no other input
- simorgh/guardian/rules.py:246-269 ModeRule is the only origin-aware rule and only narrows mode when `ctx.posture.level == "locked"`; `grep -rn 'physical\|world' simorgh/guardian/*.py` -> no hits
- simorgh/orchestration/tools.py:131-201: `"home_call": ("reversible", True)`, `"cast_play"`, `"tv_key"`, `"cam_setup"`, `"cam_stream"`, `"cam_light"`, `"cam_ptz"`, `"ring_setup"` all `("reversible", True)`
- python3 -c 'from simorgh.orchestration.tools import _TOOL_POLICY ...' -> `105 Counter({'reversible': 54, 'read_only': 39, 'irreversible': 12})`; irreversible world tools are only `cam_siren`, `ring_siren`
- simorgh/orchestration/tools.py:694-702: `classify_call(str(args.get("service")), str(args.get("target")), data=args.get("data") or {})` -- no device_class, alarm_state or always_human; comment claims 'Guardian recomputes' but `grep -rn classify_call simorgh/guardian/` -> no hits
- simorgh/execution/home/tools.py:255-265: `classes = {classify_call(..., device_class=..., alarm_state=alarm, always_human=...)}`; `worst = ...`; then `result = await client.call(...)` unconditionally
- simorgh/execution/home/tools.py:277-278, 297-298: `metadata={..., "safety": worst, ...}`; `grep -rn '"safety"' simorgh --include='*.py' | grep -v home/tools.py` -> no consumers
- simorgh/execution/config.py:420 `home_always_human_services: tuple[str, ...] = ()` is read only in home/tools.py:260, never at proposal time

**severity adjustment:** keep

**corrected claim:** Guardian gates effects on a single axis, the `reversibility` label (ReversibilityRule, guardian/rules.py:720-740), and every house/camera/Ring/TV tool except `cam_siren` and `ring_siren` is labelled `reversible` in `_TOOL_POLICY` (105 tools: 54 reversible, 39 read_only, 12 irreversible), so PTZ, camera setup/stream/light, Ring setup, Cast and TV-key actions are auto-allowed in every mode but `locked`, whatever the task's origin. The only per-call refinement, `home_call`, is classified at proposal time (orchestration/tools.py:694-702) from service/target/data alone -- without device_class, alarm state, or the configured `home_always_human_services` -- and Guardian trusts that label rather than recomputing it (no `classify_call` under simorgh/guardian/ despite the comment). The tool later recomputes the full classification (execution/home/tools.py:255-263) but only records it in `metadata["safety"]`, which nothing reads, and calls Home Assistant regardless.

