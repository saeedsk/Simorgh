# refute:proportionality:The reversibility taxonomy has had no ru

*Workflow: review · Phase: Refute · Agent id: `ae38e569b0dabc66e` · Tool calls: 11*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "tools-domains-integrations". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Read cited Guardian rule, config, and execution config lines |  # Tools whose args plausibly cause a model call (drafting); anything # else never checks the budget table at all -- a read_file proposal # is not slowed down b |
| 2 | Bash | Check deployment auto-approve, toml, always_human, and reversibility consumers | ---toml 27:model = "qwen3:4b-instruct" ---always_human simorgh/contracts/home/policy.py:67: always_human: tuple[str, ...] = ()) -> Class: simorgh/contracts/home |
| 3 | Bash | Locate auto-approve flag, reversibility consumers, home policy, and rigor usage | ---sim.sh simorgh/execution/security/tools.py:192: raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip() simorgh/execution/security/tools.py: |
| 4 | Bash | Check human-class handling, Guardian use of home policy, sim.sh flag, escalate path | ---human-handling 18:drift. Anything classed `human` is proposed as `irreversible`, which 259: always_human=tuple( 260: getattr(self._config, "home_always_human |
| 5 | Bash | List ledger files and count action.* event kinds | ---ledger blobs heads idem index.json LOCK snapshots streams 1.4G /Users/saeed/.simorgh/ledger ---decision-kinds (eval):1: no matches found: /Users/saeed/.simor |
| 6 | Bash | Inspect ledger streams, home docstring, Guardian escalate branch, rigor usage, and label counts | ---streams action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl action%3A |
| 7 | Bash | Count decision outcomes, reversibility labels, and escalations across ledger action streams | streams 26737 types [('received', 26737), ('decided', 26737), ('verified', 26703)] outcomes Counter({None: 26737}) deny layers Counter({'': 26703, 'denylist': 1 |
| 8 | Bash | Sample verified/decided payloads, count rigor per reversibility, list label declarations and gates | DECIDED SAMPLE {"kind": "approved", "layer": ""} DECIDED SAMPLE {"kind": "approved", "layer": ""} rigor by reversibility [(('reversible', None), 24402), (('read |
| 9 | Bash | Read escalation branch, count verification streams, check undo/before handling and escalation tests | ---needs_human-branch source="guardian", )) self._decided[action_id] = (fingerprint, True) return if verdict.kind == "needs_human": question = approval_question |
| 10 | Bash | Check verify subject resolution, rigor in verify streams, Guardian escalation tests, and label source | ---resolve_subject async def _resolve_subject(self, subject_ref: str) -> dict[str, Any]: ctx = self._ctx assert ctx is not None if not subject_ref: return {} tr |
| 11 | Bash | Read Guardian label cross-check, sample a verify stream, and inspect the hard-coded reversible label | ---guardian-500-535 self._decided[action_id] = (fingerprint, False) task = self._tasks.get(p.get("task_id") or "", _TaskInfo()) proposal = Proposal( action_id=a |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The measurement is real and reproduces: under the deployed posture the ReversibilityRule escalate branch has never fired, every one of 691 irreversible proposals (run_shell 570, run_script 56, worktree_land 35, install_package 17, sim_command 11, run_container 2) was approved, and shell=True is the code default. But the finding overstates the label's inertness and misattributes the switch. (1) The auto-approve default lives in kernel/service.py:203 (`setdefault("irreversible_requires_human", False)`), not the env var; simorgh.toml has no [guardian] section so mode=guarded and the rule returns allow. (2) ReversibilityRule is not the label's only consumer: guardian/service.py:522-526 derives ToolInfo.read_only from it for ModeRule (the plan-mode fix), the same rule denies in locked mode, and verification/service.py:162-164 feeds it to select_rigor; so 'verification rigor not wired' is false in code (whether the subject blob carries a real label is unconfirmed; it defaults to 'reversible'). (3) 85% of the 26,737 decisions are `ring_live` polling labelled 'reversible', so the headline number is inflated by one loop and the 'reversible' class is mostly a tool with no before-state at all. (4) Recommendation (b) is already implemented where it makes sense: home/tools.py:290-299 records `before` and HomeUndoTool consumes it; a generic Execution-level snapshot cannot know what cast_play/run_tests/ring_live touch. (5) Recommendation (a)'s notify clause (notify.py:326 declares it irreversible) would put a human prompt on every notification of an assistant built to speak unprompted; the house clause duplicates known finding 1 and guards a tool that ran once in nine days. (6) The escalation wire exists, is unit-tested (test_pipeline.py:63) and reaches ui.prompt (guardian/service.py:605-628), and kernel/service.py:189-200 documents the choice: at one-laptop/one-developer scale this is a deliberate posture with a working off-switch, not a design undermined by implementation. The actionable residue is small: say shell=True in the tool hint, and (already known) make Guardian actually consult the home policy.

### evidence

- simorgh/guardian/rules.py:720-739 ReversibilityRule: read_only->allow; reversible->allow unless locked; irreversible->allow in trusted, deny in locked, escalate only `if ctx.config.irreversible_requires_human`, else allow
- simorgh/kernel/service.py:189-203: comment 'the creator asked for auto-approve as the real, running-sim.sh default' and `guardian_section.setdefault("irreversible_requires_human", False)`; simorgh/guardian/config.py:84 `mode: str = "guarded"`, :103 dataclass default True, :155-157 env override only
- `grep -n '^\[guardian\]' ~/.simorgh/simorgh.toml` -> no match (only `model = "qwen3:4b-instruct"` at :27), so deployed mode=guarded, requires_human=False
- simorgh/execution/config.py:193 `shell: bool = True` with the 'give sim file system write access and shell access' comment
- Ledger script over ~/.simorgh/ledger/streams (26,737 action streams): types received 26737 / decided 26737 / verified 26703; decided payload sample `{"kind": "approved", "layer": ""}`; denied layers denylist 15, protected 12, paused 7 (=34); escalation/needs_human events 0; reversibility labels reversible 24414, read_only 1632, irreversible 691; irreversible tools run_shell 570, run_script 56, worktree_land 35, install_package 17, sim_command 11, run_container 2; home tools home_describe 2, home_find 2, home_call 1
- Top 'reversible' tools: ring_live 22849, cam_stream 721, run_tests 129, cast_show 114, replace_in_file 96 -- 85% of all decisions are ring_live polling
- simorgh/guardian/service.py:522-526 `tool=ToolInfo(name=..., read_only=proposal.reversibility == "read_only", reversibility=proposal.reversibility)` -- the label drives ModeRule's read_only gate (live-caught plan-mode fix)
- simorgh/verification/service.py:162-164 `reversibility=subject.get("reversibility", "reversible")` then `rigor = select_rigor(req, self._config)`; simorgh/verification/rigor.py:24 `config.rigor_by_reversibility.get(req.reversibility, ...)` -- rigor IS wired to the label in code
- simorgh/execution/home/tools.py:290-299: home_call already returns `metadata={... "safety": worst, "undoable": undoable, "before": before}`; :302-319 HomeUndoTool reads args['before'] -- recommendation (b) already done for the house
- `grep -rn 'home.policy\|classify_call' simorgh/guardian/ simorgh/kernel/` -> no matches, while simorgh/execution/home/tools.py:15-16 claims 'which Guardian imports too'; contracts/home/policy.py:22-24 docstring 'sim.sh auto-approves irreversible actions by default. For the house that default is wrong'
- simorgh/execution/notify.py:326 `reversibility = "irreversible"`; simorgh/execution/worktree.py:365 worktree_land irreversible
- simorgh/guardian/service.py:605-628 needs_human branch publishes ACTION_NEEDS_HUMAN then UI_PROMPT with prompt_id=action_id; tests/simorgh/guardian/test_pipeline.py:63 `test_escalate_without_a_later_deny_becomes_needs_human` -- the escalation wire exists and is tested

**severity adjustment:** lower

**corrected claim:** Under the deployed posture (mode=guarded; kernel/service.py:203 sets irreversible_requires_human=False as the running default, overridable by SIMORGH_GUARDIAN_AUTO_APPROVE or simorgh.toml), ReversibilityRule's escalate branch has never fired: 26,737 decisions, 26,703 approved, 34 denied by denylist/protected/paused, 0 needs_human; all 691 irreversible proposals (run_shell 570, run_script 56, worktree_land 35, install_package 17, sim_command 11, run_container 2) were approved, and `[execution] shell = True` is the code default. The reversibility label is not otherwise inert: it drives ModeRule's read_only gate for plan sessions, the locked-mode denials, and Verification's rigor selection. 85% of decisions are `ring_live` polling labelled 'reversible'. home_call already records `before` for undo; the real gap is the already-known one that Guardian never consults contracts/home/policy.py, so a `human`-class house call would be auto-approved (home_call has run once). This is a deliberate, documented, tested-off-switch posture at one-family scale; the cheap fixes are a truthful shell=True hint and wiring the home policy into Guardian, not a generic before-state capture or escalating notify.

