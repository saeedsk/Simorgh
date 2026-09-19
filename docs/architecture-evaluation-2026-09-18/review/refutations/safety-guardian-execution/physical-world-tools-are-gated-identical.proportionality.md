# refute:proportionality:Physical-world tools are gated identical

*Workflow: review · Phase: Refute · Agent id: `aaf9cbda2116d91f7` · Tool calls: 10*

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
| 1 | Bash | Read the cited Guardian, tools, and home code regions |  ) return Decision("abstain", self.layer) def similarity(code: str, excerpts: list[str], threshold: float) -> tuple[float, str] \| None: """Shared by `ImmunityRu |
| 2 | Bash | Find tool policy table and origin handling in Guardian | simorgh/contracts/toolargs.py:104: # required string field, `query` -- see `_TOOL_POLICY`'s comment on simorgh/contracts/home/policy.py:113: """The `_TOOL_POLIC |
| 3 | Bash | Read policy table, home classifier, Guardian proposal intake, ModeRule, and tool profiles | == POLICY TABLE (home/cam/ring/cast/tv entries) == 3: # Proposed by the session runner, never by the model (no marker): 4: # a task's own worktree, and its land |
| 4 | Bash | Check which profiles/origins bind world tools, Guardian home policy import, and volume caps | == profiles structure == 12:CHAT = Profile( 13: name="chat", 97:PATCH = Profile( 98: name="patch", 131:RESEARCH = Profile( 136: name="research", 155:PLAN = Prof |
| 5 | Bash | Introspect profiles, task-kind mapping, policy counts, home tool post-classification, and autonomous origins | == which profiles bind world tools == CHAT 72 ['cam_light', 'cam_ptz', 'cam_siren', 'cam_stream', 'cast_play', 'cast_volume', 'home_call', 'home_undo', 'ring_li |
| 6 | Bash | Check media volume caps, curiosity task kinds, plan step kinds, and assistant origin | == media unattended/quiet hours == energy_meters: dict = field(default_factory=dict) energy_tariff_path: str = "workspace/energy/tariff.json" # An inline tariff |
| 7 | Bash | Check start_task kinds, task enums, Guardian defaults, live config, and camera tool guards | == start_task kinds == 13: kind = str(args.get("kind") or "patch").strip().lower() 14: if kind not in ("patch", "research", "project"): 15: kind = "patch" 25: # |
| 8 | Bash | Check plan step kinds, camera tool guards, auto-approve effect on the human class, and unattended home_call callers | == plan step kind validation == __init__.py __pycache__ api.py bridge.py config.py dag.py decomposer.py dedupe.py intake.py model.py planmode.py reground.py rol |
| 9 | Bash | Check decomposer step kinds and auto-approve wiring | == decomposer step kinds == 59: step_id=sid, kind="research", description=research_match.group(1).strip(), 79: step_id=uuid.uuid4().hex[:8], kind="patch", descr |
| 10 | Bash | Check auto-approve default wiring in kernel and launcher |  # `sim.sh`'s own default, deliberately looser than `GuardianConfig`'s # own dataclass default (`irreversible_requires_human=True`, kept # safe for anyone const |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual core holds: Guardian's only physical-vs-code axis is the `reversibility` string (ReversibilityRule, rules.py:720-740), the camera/cast/TV tools are labelled `reversible` in _TOOL_POLICY (orchestration/tools.py:116-172), and home_call's proposal-time classification (tools.py:698-704) omits device_class and alarm_state, while the tool's richer recomputation (execution/home/tools.py:255-262) only lands in result metadata as "safety" and never refuses (lines 276-298). One extra detail the finding missed: the comment at tools.py:94-97 says Guardian recomputes the home class, but `grep classify_call simorgh/guardian/` is empty -- Guardian trusts the proposer's label (harmless because the proposer is Orchestration, not the model).

But the "why it matters" and the recommendation do not survive the code. (1) The unattended scenario cannot occur: world tools are bound only in the CHAT and VOICE_CHAT profiles; PATCH, RESEARCH, PLAN and SKILL bind zero of them (introspected). Autonomous origins can only produce kinds patch/research/project (planning/intake.py:145,183,195; execution/tools.py start_task restricts to patch/research/project; decomposer.py emits research/patch), for_task maps project and mode=plan to PLAN, and a chat-kind task is created only when origin=="human" (intake.py:145). So the profile layer already implements exactly the "world tools only for human-originated sessions" split the proposed WorldRule would add -- at tool-binding time, which is stronger because the model never even sees the tool. A WorldRule keyed on autonomous origins would have nothing to act on. (2) The "TV at full volume at 2am" example is already handled domain-side: media_max_volume_unattended=60, media_quiet_hours 22:00-07:00 with cap 20 (execution/config.py:442-444), enforced before the call in media/tools.py:63-73. (3) The PTZ-at-a-neighbour example is a human chat turn, which the recommendation itself says should be let through, so the recommendation does not address its own example; and cam_ptz's only guard is command-name validation (cameras.py:728), which a domain axis would not change.

What remains is a narrow, local gap, not an architectural one: for home_call, a switch/light with no security word in its id, called while the alarm is armed_away, classifies `unattended` at proposal time -> `reversible` -> Guardian allows; the tool then computes worst="human" and proceeds anyway, tagging metadata. That is a design that is right (pure shared classifier) but undermined by the implementation (the informed classification is computed after the decision and discarded). The fix is inside home_call (refuse or re-propose when worst=="human" and the proposal was not escalated, or consult the registry at proposal time), not a new protocol axis across 105 tools. Note also that under sim.sh's auto-approve default (kernel/service.py:188-200) `human` -> `irreversible` -> allowed anyway, despite policy.py's docstring saying `human` "is meant to survive it" -- but that is the already-known auto-approve item.

At this scale (one family, one laptop, one developer) adding a `domain` field to every tool class plus a new Guardian rule is disproportionate to a problem the profile layer and the media caps already cover; the one real hole is a few lines in one tool.

### evidence

- simorgh/guardian/rules.py:720-740 ReversibilityRule: `r = proposal.reversibility` is the only physical-vs-code discriminator; `reversible` -> allow in every mode except locked
- simorgh/orchestration/tools.py:103,116-172: home_call/cast_*/tv_*/cam_ptz/cam_light/cam_stream/cam_setup all ('reversible', ...); cam_siren is irreversible
- python -c introspection: `_TOOL_POLICY` has 105 entries, Counter({'reversible': 54, 'read_only': 39, 'irreversible': 12}) (finding's 98/51/37/10 is slightly stale)
- simorgh/orchestration/tools.py:698-704: classify_call(service, target, data=...) -- no device_class, no alarm_state; comment at 94-97 claims Guardian recomputes it
- grep -rn classify_call simorgh/guardian/ -> no matches: Guardian never recomputes the home class; it uses p['reversibility'] as sent (guardian/service.py:502-505, 522-526)
- simorgh/execution/home/tools.py:255-262 computes `worst` with device_class and alarm_state; lines 276-278 and 296-298 only store it as metadata 'safety'; no refusal path on worst=='human'
- python -c over simorgh.orchestration.profiles: CHAT binds 11 world tools (cam_light, cam_ptz, cam_siren, cam_stream, cast_play, cast_volume, home_call, home_undo, ring_light, ring_siren, tv_key), VOICE_CHAT the same 11; PATCH, RESEARCH, PLAN, SKILL bind [] of them
- simorgh/orchestration/profiles.py:232-244: BY_KIND maps project->PLAN, mode=='plan'->PLAN; for_percept returns CHAT/VOICE_CHAT only for conversational percepts
- simorgh/planning/intake.py:145 `kind="chat" if origin == "human" else "patch"`; intake.py:183,195 reflection/research create kind=patch; planning/decomposer.py:59,79 steps are kind research or patch; execution/tools.py:1807-1809 start_task clamps kind to patch/research/project
- simorgh/guardian/rules.py:245-268 ModeRule already keys on proposal.origin in ctx.config.autonomous_origins; guardian/config.py:108 autonomous_origins = (curiosity, reflection, research, project, assistant)
- simorgh/execution/config.py:438-444: media_max_volume_unattended=60, media_quiet_hours='22:00-07:00', media_quiet_hours_max_volume=20; simorgh/execution/media/tools.py:63-73 enforces both before the cast call
- simorgh/execution/home/cameras.py:728: cam_ptz's only guard is `refused: command is one of {_PTZ}`
- simorgh/contracts/home/policy.py:20-23 docstring: 'sim.sh auto-approves irreversible actions by default... `human` here is meant to survive it'; reversibility_of maps human->'irreversible' (line 113-116); grep 'home|always_human' simorgh/guardian/ -> empty, so nothing in Guardian special-cases it; kernel/service.py:188-200 documents the auto-approve baseline

**severity adjustment:** lower

**corrected claim:** Physical-world tools share Guardian's single `reversibility` axis with code tools, and home_call's proposal-time class ignores device_class and alarm state, so a call on a non-security-named entity while the alarm is armed is approved as `reversible` and the tool's own later `human` classification is only recorded, never enforced (execution/home/tools.py:255-298). However, the "autonomous action on the world" scenario the finding warns about is already prevented one layer up: only the CHAT and VOICE_CHAT profiles bind any world tool, autonomous origins can only create patch/research/project tasks whose profiles bind none, and loud/late TV volume is already capped by the media domain. The right fix is local to home_call (enforce `worst` or classify with the registry at proposal time), not a new `domain` axis on every tool plus a Guardian WorldRule.

