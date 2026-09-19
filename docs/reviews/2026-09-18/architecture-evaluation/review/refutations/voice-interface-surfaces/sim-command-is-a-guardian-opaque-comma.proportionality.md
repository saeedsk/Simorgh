# refute:proportionality:`sim_command` is a Guardian-opaque comma

*Workflow: review · Phase: Refute · Agent id: `a52a9fd5fcdb082ea` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "voice-interface-surfaces". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Check topic policy and sim_command tool registration | 65:UI_COMMAND_REQUEST = "ui.command.request" 295:PUBLISH_ONLY_BY: dict[str, frozenset[str]] = { 363: allowed = PUBLISH_ONLY_BY.get(type_name) --- (eval):1: no m |
| 2 | Bash | Read publish policy and find all sim_command / ui.command.request references | SUBSCRIBE_ONLY_BY: dict[str, frozenset[str]] = { ACTION_PROPOSED: frozenset({"guardian"}), ACTION_APPROVED: frozenset({"execution"}), } # Only these subsystem n |
| 3 | Bash | Read sim_command tool, interface handler, scaffold text | === execution/tools.py 1940-2010 === lines = [f"{str(t.get('task_id') or '?')[:12]} {str(t.get('status') or '?'):<10s} {str(t.get('origin') or '?'):<10s} " f"{s |
| 4 | Bash | Locate skills command, tool arg summary, parser command list, auto-approve | === _skills_command === 307: return await _run_tool(bus=bus, ledger=ledger, tool="memory_forget", session_id=session_id, timeout=30.0, 846: return await _run_to |
| 5 | Bash | Read command list and full skills command body | === parser COMMANDS 22-60 === COMMANDS: tuple[tuple[str, str, str], ...] = ( ("status", "", "health, vitals, posture and git in one panel"), ("domains", "[name] |
| 6 | Bash | Check trusted orgs, skill execution, Guardian classification inputs, auto-approve defaults, live config | === TRUSTED_ORGS === 182:TRUSTED_ORGS: tuple[str, ...] = ("anthropics", "google", "microsoft", "huggingface", "trailofbits") 183- 184- 185-@dataclass(frozen=Tru |
| 7 | Bash | Check auto-approve wiring, Guardian handling of sim_command, use_skill semantics, bus publish enforcement | === auto approve wiring === simorgh/guardian/config.py:103: irreversible_requires_human: bool = True simorgh/guardian/config.py:138: """`[guardian]` table -> Co |
| 8 | Bash | Read Guardian arg-inspecting rules, find auto-approve wiring, skill loader, tests | === rules.py 110-130 === return "\n".join(changed) # Arguments that are a program rather than a path: whatever they name, # they name it INSIDE their text. A ru |
| 9 | Bash | Confirm auto-approve wiring, Guardian text inspection of command arg, tests, skill loading semantics | === sim.sh auto approve === === toml guardian === === _code_text + DenylistRule === 352:def _code_text(proposal: Proposal) -> str \| None: 353- """The free-form  |
| 10 | Bash | Locate auto-approve wiring, clone method, run_script gating, tool command nesting, command count | === env var anywhere in repo === simorgh/execution/security/tools.py:192: raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip() simorgh/execu |
| 11 | Bash | Confirm auto-approve wiring, run_script gating, mcp approve path | === kernel/service.py 185-210 === self.bus = make_bus_client(self._bus_backend, source="kernel", ledger=self.ledger, clock=self._clock.now, policy=policy) # `si |

## Structured reply

**refuted:** False

**verdict:** partly-true

**severity adjustment:** lower

**corrected claim:** `sim_command` lets the model press any of the 29 parsed CLI verbs (interface/service.py:766-813 refuses only `!`, then `dispatch()`s whatever `parse()` accepts), and `skills install/update/approve/remove` mutate ~/.simorgh/skills with shutil and a `git clone` via run_shell with no ACTION_PROPOSED (dispatch.py:1840, 1969-1970, 2088-2090, 2101-2102, 2123-2124, 2139). But Guardian does NOT see only the wrapper name: `command` is in `_CODE_ARG_KEYS` (guardian/rules.py:116) so DenylistRule, ImmunityRule, StaticAnalysisRule and ShellcheckRule scan the typed line (rules.py:352-371, 582), and when it escalates the human is shown the line (service.py:73-91). What Guardian lacks is per-verb semantics: `status` and `skills approve x` are both "irreversible" (orchestration/tools.py:65), and under the kernel's auto-approve baseline (kernel/service.py:203 `setdefault("irreversible_requires_human", False)`; ~/.simorgh/simorgh.toml has no [guardian] section) both pass. The genuine narrow gap is that human-approval verbs (`skills approve`, and the same shape for `mcp approve`, `tasks clear`, `auto`) become self-approvable by the model, defeating the review/ staging that `skills install` deliberately builds for untrusted orgs. Skills are SKILL.md instruction folders loaded as text (orchestration/session.py:1372-1395), not code that runs on install; any script they ship runs only through the Guardian-gated `run_script` (orchestration/tools.py:86).

**reasoning:** The structural facts check out: the topic has no PUBLISH_ONLY_BY row (topics.py:295-305; only execution/tools.py:1984 and voice/session.py:1601 publish it), the tool is in CHAT and VOICE_CHAT (profiles.py:40, 197), the handler dispatches any parsed command, and `_skills_command` writes disk directly. Three parts of the claim are overstated. (1) "Guardian only sees the wrapper" is wrong: the `command` arg is scanned as program text by the denylist/immunity/shellcheck/static rules, and the approval question prints it; the docstring at execution/tools.py:1948-1957 shows the creator deliberately chose "irreversible" so Guardian sees every call. (2) "third-party code that will later run" is overstated: installation copies instructions; execution of bundled scripts still goes through `run_script` (irreversible, Guardian-gated) and untrusted-org installs land in `review/` as "waiting", not enabled. (3) "outside the action path" is by design for the whole CLI, human-typed included; the action path was never the gate for CLI commands, the review+approve staging was. The materially new and correct point is that `sim_command` exposes the human's approval verbs to the model, so the staging gate can be closed by the party it was meant to gate. At this system's scale (one laptop, one developer who asked for auto-approve and for Sim to run "any other cli command I ask it to run", zero skills actually installed: ~/.simorgh/skills holds only search-cache.json), this is a small, cheap fix, not a medium architectural defect. The recommendation is disproportionate in two of three parts: a new `skills_install` tool through `_run_tool` adds a second install path while the human one still bypasses Guardian, and PUBLISH_ONLY_BY on an in-process bus whose only publishers are trusted subsystem code buys little. The proportionate fix is a short deny-list of approval/destructive verbs in `_on_command_request` (or a Guardian rule that escalates `sim_command` whose `command` starts with `skills approve|install|remove`, `mcp approve`, `tasks clear`, `auto`) so those verbs stay human-only even under auto-approve. Note `sim_command` -> `tool <name>` nests correctly: dispatch `tool` calls `_run_tool` which publishes ACTION_PROPOSED (dispatch.py:1183, 1330), so tool effects reached this way are still gated on their own terms.

### evidence

- simorgh/interface/service.py:766-813 `_on_command_request`: refuses empty and `!` lines, then `command = parse(line)`; any command with a name is `dispatch()`ed and echoed as `[sim ran: ...]`
- simorgh/interface/parser.py:22-52 COMMANDS; `python3 -c 'from simorgh.interface.parser import COMMAND_NAMES; print(len(COMMAND_NAMES))'` -> 29, including skills, mcp, tasks, auto, improve, exit, restart
- simorgh/contracts/topics.py:295-305 PUBLISH_ONLY_BY has no UI_COMMAND_REQUEST row; grep shows publishers only at simorgh/execution/tools.py:1984 (source="execution") and simorgh/voice/session.py:1601
- simorgh/orchestration/profiles.py:40 and :197 list "sim_command"; simorgh/orchestration/tools.py:65 `"sim_command": ("irreversible", False)`
- simorgh/execution/tools.py:1948-1957 SimCommandTool docstring: creator 2026-09-15 asked that Sim be able to run 'any other cli command I ask it to run'; 'Irreversible on purpose ... Guardian must see every call'; :1975 refuses `!`
- simorgh/guardian/rules.py:116 `_CODE_ARG_KEYS = ("code", "command")`; :352-371 `_code_text` joins `command` so DenylistRule (:371-393), ImmunityRule (:669-681) scan the sim_command line; ShellcheckRule :582 reads `proposal.args.get("command")`
- simorgh/guardian/service.py:73-91 `approval_question` prints each arg, so an escalated sim_command shows the actual line to the human
- simorgh/guardian/rules.py:720-740 ReversibilityRule: irreversible -> escalate only if `irreversible_requires_human`; simorgh/kernel/service.py:203 `guardian_section.setdefault("irreversible_requires_human", False)` (auto-approve is the kernel baseline, not a sim.sh export: `grep -n AUTO_APPROVE sim.sh` returns nothing); `grep -n guardian ~/.simorgh/simorgh.toml` returns nothing, so the baseline is in force
- simorgh/interface/dispatch.py:1879 `_skills_command`; :1840 `git clone` via run_shell; :1966-1970 install copies to `<org>/` if trusted else `review/`; :1926-1927 status 'enabled' only if `source.trusted and review.clean`; :2117-2124 `skills approve` moves review/ -> approved/; :2139 remove rmtree; no ACTION_PROPOSED/_run_tool in the function (grep 1879-2145)
- simorgh/contracts/skills.py:182 TRUSTED_ORGS = anthropics, google, microsoft, huggingface, trailofbits; :197 trusted only on github.com
- simorgh/orchestration/session.py:1372-1395 `_use_skill`: loads SKILL.md body as text, 'never goes to Guardian'; header tells the model to run shipped scripts with run_script; simorgh/orchestration/tools.py:86 `"run_script": ("irreversible", True)` (Guardian-gated)
- simorgh/interface/dispatch.py:1183 and :1330: the `tool <name>` command goes through `_run_tool` which publishes ACTION_PROPOSED, so `sim_command('tool run_shell ...')` is still gated on the inner tool
- `ls -la ~/.simorgh/skills/` -> only search-cache.json (no skill has ever been installed on this machine)
- tests/simorgh/interface/test_command_request.py:40-61 covers dispatch, unknown command, and `!` refusal only; no test asserts any verb is withheld from the model

