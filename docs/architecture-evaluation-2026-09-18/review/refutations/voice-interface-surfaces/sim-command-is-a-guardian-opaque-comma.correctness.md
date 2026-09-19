# refute:correctness:`sim_command` is a Guardian-opaque comma

*Workflow: review · Phase: Refute · Agent id: `a59c8c8731f77340d` · Tool calls: 12*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "`sim_command` is a Guardian-opaque command channel; `skills` mutates disk outside the action path",
    "kind": "wrong-design",
    "severity": "medium",
    "claim": "The model can run any typed CLI line via the `sim_command` tool -> `ui.command.request` (a topic with no publish policy) -> `dispatch()`, where Guardian only sees the wrapper 'sim_command' (classified irreversible, auto-approved by sim.sh) and not the effect; only `!` shell is refused, while `skills install/approve/enable` copy and delete skill folders directly with `shutil`.",
    "evidence": [
      "simorgh/interface/service.py `_on_command_request`: refuses `line.startswith(\"!\")`, otherwise `outcome = await dispatch(command, ...)` for any parsed command",
      "simorgh/contracts/topics.py:65 `UI_COMMAND_REQUEST = \"ui.command.request\"` with no `PUBLISH_ONLY_BY` entry (grep finds only the definition)",
      "simorgh/orchestration/profiles.py:40 and :197 include \"sim_command\" in CHAT and VOICE_CHAT; orchestration/tools.py:65 `\"sim_command\": (\"irreversible\", False)`",
      "simorgh/interface/dispatch.py `_skills_command` (line 1879, 274 lines): `shutil.rmtree(home)` / `shutil.copytree(folder, home)` and the `review/` staging copies (window 2080-2130), with no `ACTION_PROPOSED`/`_run_tool` in the function (grep)",
      "Known context: sim.sh auto-approves irreversible actions (memory: guardian_auto_approve_default)"
    ],
    "why_it_matters": "The action path's guarantee is that Guardian classifies the real effect; here it classifies a string. Installing a skill (third-party code that will later run) is the highest-consequence thing the CLI can do and it is reachable by the model as one opaque 'irreversible' action.",
    "recommendation": "Turn `sim_command` into an allow-list of verbs that are genuinely UI-level (restart, voice on/off/mute, tv show, tasks, status, help) and reject the rest with 'use the tool'; route `skills install/approve/enable` through `_run_tool` as a real `skills_install` tool so Guardian sees the URL and the target path. Add `UI_COMMAND_REQUEST` to `PUBLISH_ONLY_BY` (execution, voice, interface).",
    "confidence": 0.7
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read the command request handler in interface service | 231: await ctx.bus.subscribe(topics.UI_COMMAND_REQUEST, self._on_command_request), 232- await ctx.bus.subscribe(topics.ACTION_NEEDS_HUMAN, self._on_needs_human) |
| 2 | Bash | Find all uses of the ui.command.request topic and the publish policy table | simorgh/interface/service.py:116: topics.PERCEPT_TIME_SCHEDULED, topics.UI_COMMAND_REQUEST, simorgh/interface/service.py:231: await ctx.bus.subscribe(topics.UI_ |
| 3 | Bash | Locate sim_command tool registration, profile binding and implementation | simorgh/orchestration/profiles.py:40: "sim_command", simorgh/orchestration/profiles.py:197: "music_now", "music_control", "music_play", "sim_command", simorgh/o |
| 4 | Bash | Read the sim_command tool implementation and the voice publisher |  lines = [f"{str(t.get('task_id') or '?')[:12]} {str(t.get('status') or '?'):<10s} {str(t.get('origin') or '?'):<10s} " f"{str(t.get('description') or '')[:110] |
| 5 | Bash | Check the skills command body for shutil usage and any Guardian routing | 1879:async def _skills_command(args: str, *, ledger: LedgerClient, clock, clone=_clone_at, fetch=_fetch_tree) -> Outcome: ends before line 2155 1884: the determ |
| 6 | Bash | Check tool classification table, Guardian handling of irreversible, and auto-approve flag |  "run_tests": ("reversible", False), "draft_candidate": ("reversible", False), # Model-callable since 2026-09-07 (profiles.py's own note): the tools # that actu |
| 7 | Bash | Check auto-approve default, dispatch routing for skills, and whether Guardian rules inspect tool args | --- simorgh/interface/parser.py:44: ("skills", "[list\|show <name>\|review <folder>\|install <git-url>\|approve <name>\|remove <name>]", simorgh/interface/parser.py: |
| 8 | Bash | Check auto-approve wiring, Guardian rules that read the command arg, skills dispatch and approve, and the live toml | simloader.py:531: "tests/simorgh/guardian", "tests/simorgh/cognition", "tests/simorgh/memory", "tests/simorgh/orchestration", simloader.py:537: "tests/simorgh/i |
| 9 | Bash | Find where auto-approve is exported, how Guardian extracts code text, and whether approved skills are loaded as runnable | sim.sh simorgh/execution/security/tools.py:192: raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip() simorgh/execution/security/tools.py:195 |
| 10 | Bash | Confirm the auto-approve default path, that Execution proposes tools to Guardian, and how reversibility is read |  # `sim.sh`'s own default, deliberately looser than `GuardianConfig`'s # own dataclass default (`irreversible_requires_human=True`, kept # safe for anyone const |
| 11 | Bash | Confirm the setdefault and Execution's proposal path to Guardian |  guardian_section = self.config.section("guardian") guardian_section.setdefault("irreversible_requires_human", False) # Every from_mapping ignores a key it does |
| 12 | Bash | Check whether prior reviews already reported this | (Bash completed with no output) |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact checks out against the code today. `SimCommandTool` (simorgh/execution/tools.py:1957-1998) is declared `reversibility = "irreversible"`, refuses only a leading `!`, and publishes `ui.command.request` with the raw line. Interface's `_on_command_request` (simorgh/interface/service.py:766-818) likewise refuses only `!`, then calls `parse(line)` and `dispatch(...)` for any recognised command; `dispatch` routes `skills` straight to `_skills_command` (dispatch.py:367-368), which does `shutil.rmtree`/`copytree`/`move` on `SKILLS_HOME` (dispatch.py:1969-1970, 2088-2090, 2101-2102, 2123-2124, 2139) with no ACTION_PROPOSED/_run_tool anywhere in its 276 lines. `UI_COMMAND_REQUEST` (topics.py:65) has no entry in `PUBLISH_ONLY_BY` (topics.py:295-305). `sim_command` is in CHAT (profiles.py:40) and VOICE_CHAT (profiles.py:197) and classified `("irreversible", False)` in orchestration/tools.py:65. `ReversibilityRule` (guardian/rules.py:720-739) converts an irreversible proposal to "allow" when `irreversible_requires_human` is False, and kernel/service.py:203 `setdefault("irreversible_requires_human", False)` makes that the running default. Two small precision corrections: (1) Guardian does not see *only* the wrapper name — `"command"` is in `_CODE_ARG_KEYS` (rules.py:116), so DenylistRule and ImmunityRule regex-scan the line text; but no rule classifies what `skills install <url>` or `skills approve` does, so the effect (fetching third-party code and enabling it) is still unclassified. (2) The auto-approve default is set in kernel/service.py, not literally in sim.sh. Neither correction weakens the finding. Not in the known-findings list: prior reviews mention that sim.sh flips one boolean, but nothing about `sim_command` being an opaque command channel or `skills` mutating disk outside the action path (grep of the three prior review docs for sim_command/skills install returns nothing). Kind is right (design gap, not a bug); severity medium is fair given that untrusted installs land in `review/` until `approve`, but `approve` itself is one more opaque line away.

### evidence

- simorgh/execution/tools.py:1957-1998 — `class SimCommandTool`, `reversibility = "irreversible"`, refuses only `line.startswith("!")`, then `ctx.bus.request(_Message.new(_topics.UI_COMMAND_REQUEST, source="execution", payload={"line": line, "requested_by": "sim"}))`
- simorgh/interface/service.py:766-818 — `_on_command_request`: refuses empty and `!` lines, `command = parse(line)`, then `outcome = await dispatch(command, bus=..., ledger=...)` for any parsed command
- simorgh/interface/dispatch.py:367-368 — `if name == "skills": return await _skills_command(args, ledger=ledger, clock=clock)`
- simorgh/interface/dispatch.py:1879 `_skills_command` runs to line 2154; grep for `shutil.` in that window: lines 1969, 1970, 2088, 2090, 2101, 2102, 2123, 2124, 2139 (rmtree/copytree/move); grep for `ACTION_PROPOSED|_run_tool` in the window: no hits
- simorgh/contracts/topics.py:65 `UI_COMMAND_REQUEST = "ui.command.request"`; topics.py:295-305 `PUBLISH_ONLY_BY` lists ACTION_APPROVED/DENIED, SYSTEM_*, SELF_MODEL_UPDATED, PLAN_PROPOSED only — no UI_COMMAND_REQUEST
- simorgh/orchestration/profiles.py:40 and :197 — `"sim_command"` in CHAT and VOICE_CHAT; simorgh/orchestration/tools.py:65 `"sim_command": ("irreversible", False)`
- simorgh/guardian/rules.py:720-739 ReversibilityRule: `if ctx.config.irreversible_requires_human: return Decision("escalate", ...)` else allow; simorgh/kernel/service.py:202-203 `guardian_section.setdefault("irreversible_requires_human", False)`
- simorgh/guardian/rules.py:116 `_CODE_ARG_KEYS = ("code", "command")` and rules.py:352-367 `_code_text` — Guardian regex-scans the `command` string (denylist/immunity) but no rule interprets `skills install/approve`
- simorgh/contracts/schema/ui.command.request.v1.json — payload is `{line: string, requested_by: string|null}`, `additionalProperties: true`, no allow-list of verbs
- grep -in 'sim_command|skills install' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md → no output (not previously reported)

**severity adjustment:** keep

**corrected claim:** The model can run any typed CLI line via the `sim_command` tool -> `ui.command.request` (no PUBLISH_ONLY_BY entry) -> `dispatch()`. Guardian sees the proposal as tool `sim_command` (irreversible, auto-allowed by the kernel's `irreversible_requires_human=False` default) plus the raw line as a `command` string that only the regex denylist and immunity rules scan; no rule classifies the effect of the verb. Only `!` shell is refused, while `skills install/approve/remove` copy, move and delete skill folders under `SKILLS_HOME` directly with `shutil`, never passing through `_run_tool`/ACTION_PROPOSED.

