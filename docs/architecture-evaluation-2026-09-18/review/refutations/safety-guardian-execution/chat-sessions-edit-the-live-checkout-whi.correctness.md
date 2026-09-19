# refute:correctness:Chat sessions edit the live checkout whi

*Workflow: review · Phase: Refute · Agent id: `ac9fcda0a91da40da` · Tool calls: 7*

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
    "title": "Chat sessions edit the live checkout while patch tasks get a worktree, so the discipline covers the less common path",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "`WORKTREE_KINDS = {\"patch\",\"skill\"}` so only those task kinds branch; the CHAT profile carries `apply_source_patch`, `replace_in_file`, `run_script` and `install_package`, all of which write to or run against the live tree the running process imported from, with no landing gate at all.",
    "evidence": [
      "simorgh/orchestration/session.py:59 `WORKTREE_KINDS = frozenset({\"patch\", \"skill\"})`",
      "simorgh/orchestration/profiles.py:12-66 CHAT tools include `apply_source_patch`, `replace_in_file`, `install_package`, `run_script`",
      "simorgh/execution/tools.py:109-124 `tool_root` returns `config.repo_root` when `ctx.root is None`",
      "docs/plans/worktree-landing-design.md 'Why' section lists 'a process standing on a moving floor' as the problem worktrees solve"
    ],
    "why_it_matters": "The worktree design is right; the exemption swallows it. A chat turn is the most frequent way the creator drives Sim.",
    "recommendation": "Restrict chat-profile writes to `workspace/` (the stated reason chat got write tools was 'write access to its workspace directory'), and route any `simorgh/`, `tests/`, `tools/`, `docs/` edit from chat through `start_task` so it gets a worktree and a landing.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read worktree kinds and chat profile tool list | simorgh/orchestration/session.py:59:WORKTREE_KINDS = frozenset({"patch", "skill"}) simorgh/orchestration/session.py:754: if not self._worktrees or session.kind  |
| 2 | Bash | Read tool_root, worktree branch, and write-scope checks | # fetch of docs.python.org's asyncio page (observer, 2026-09-08) is # 177,075 bytes -- under the cap, so it survived by luck; a page even a # little larger woul |
| 3 | Bash | Check write scopes, config, and whether Guardian distinguishes chat from patch |  # `use_skill`, and the files beside it (references, scripts) with # `read_file`. Read-only -- a skill is never edited by a task, and # its scripts run only thr |
| 4 | Bash | Check known-findings docs, chat session kind, and Guardian protected paths | ---KNOWN docs/architecture-audit-2026.md:9:2. **Worktree Isolation for Self-Patching:** Using isolated git worktrees to draft and verify patches before applying |
| 5 | Bash | Check Guardian protected subjects, worktree root lookup, run_script root, and prior docs | ---PROTECTED 19-# every cognitive subsystem but never the parts that decide what it may 20-# do (AGI-04 section 9, corrigibility). 21:DEFAULT_PROTECTED_SUBJECTS |
| 6 | Bash | Check Guardian scope rule, proposal scope origin, run_script root, and prior HTML review | ---SCOPERULE class ScopeRule: name = "scope" layer = "scope" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: # A full task-vs-pr |
| 7 | Bash | Locate the four write tools, run_script's working tree, and check prior review and landing checks | simorgh/execution/packages.py:246: name = "install_package" simorgh/execution/tools.py:1672: name = "apply_source_patch" simorgh/execution/tools.py:2246: name = |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual element of the claim checks out against the code today. (1) `WORKTREE_KINDS = frozenset({"patch", "skill"})` at simorgh/orchestration/session.py:59, and `_uses_worktree` (session.py:753-754) returns False for any other kind or mode. Chat sessions are created with `kind="chat", mode="execute"` at simorgh/orchestration/worker.py:403, so they never get a worktree. (2) Execution resolves the tree per call: service.py:795 `root = self._worktrees.root_for(task_id)`; worktree.py:129-136 `root_for` returns None unless `<path>/.git` is a worktree file, and tools.py:109-123 `tool_root` then falls back to `config.repo_root`, i.e. the live checkout the process imported from. (3) The CHAT profile (profiles.py:12-66) does carry `apply_source_patch`, `replace_in_file`, `install_package`, `run_script`, and its own comment says "a chat turn now IS [a patch profile] once it can write, install and run". (4) The write scope for those tools is `write_scopes_source` = `simorgh/, simorgh_skills/, tests/, tools/, docs/, workspace/` (execution/config.py:120-126); there is no chat-specific narrowing anywhere: Guardian's `ScopeRule` abstains unconditionally (guardian/rules.py:337-349), and no Guardian rule mentions kind or profile (grep of simorgh/guardian for "chat" returns nothing). The only cross-kind shield is `ProtectedRule` with DEFAULT_PROTECTED_SUBJECTS (guardian/config.py:21-31: guardian/, execution/, contracts/, kernel/, SOUL.md, simorgh.toml, bootloader), so a chat turn can still rewrite simorgh/orchestration, cognition, persona, learning, tests/, tools/ in place with no rebase, no suite gate and no landing. (5) `run_script` (execution/script.py:82-90) always runs with `cwd=repo_root` and `PYTHONPATH=repo_root` regardless of worktree, so it runs against the live tree for every kind, which slightly broadens the finding beyond chat. Minor precision notes that do not change the verdict: `install_package` mutates the shared interpreter environment, which a worktree would not isolate anyway, so it is a weaker example than the file tools; and the safety core (guardian/execution/contracts/kernel) IS protected from chat writes, so the exposure is "the rest of simorgh/ plus tests/tools/docs", not the whole tree. Not in the known-findings list: the prior reviews (architecture-audit-2026.md:9, architecture-review-2026-09-18.html:57, third-opinion:18) all rate worktree isolation as "real/accurate" without noting that the most frequent write path bypasses it. The design/undermined classification is correct: the landing discipline exists and works for patch tasks; the profile change of 2026-09-09 routed the same write tools around it.

### evidence

- simorgh/orchestration/session.py:59 `WORKTREE_KINDS = frozenset({"patch", "skill"})`; session.py:753-754 `_uses_worktree` returns False when `session.kind not in WORKTREE_KINDS`
- simorgh/orchestration/worker.py:403 chat sessions are created with `kind="chat", mode="execute"`
- simorgh/execution/service.py:795-798 `root = self._worktrees.root_for(task_id) ...; ctx = ToolContext(..., root=root)`; simorgh/execution/worktree.py:129-136 `root_for` returns None when no worktree dir exists for the task id
- simorgh/execution/tools.py:109-123 `tool_root` returns `config.repo_root` when `ctx.root` is None
- simorgh/orchestration/profiles.py:47-56 CHAT tools include `apply_source_patch`, `replace_in_file`, `install_package`, `run_script`; profiles.py:71-73 comment: 'Matched to the patch profile, which is what a chat turn now IS once it can write, install and run'
- simorgh/execution/config.py:120-126 `write_scopes_source = ("simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/", SCRATCH_PREFIX)` -- the same scope applies to chat and patch; tools.py:1685 and 2309-2310 both use `write_scopes_source`
- simorgh/guardian/rules.py:337-349 `ScopeRule.evaluate` always returns `Decision("abstain", ...)`; `grep -rn chat simorgh/guardian/*.py` returns no matches -- Guardian has no kind/profile-aware write gate
- simorgh/guardian/config.py:21-31 DEFAULT_PROTECTED_SUBJECTS covers only guardian/, execution/, contracts/, kernel/, SOUL.md, simorgh.toml and the bootloader -- orchestration/, cognition/, persona/, learning/, tests/, tools/ are writable from chat on the live tree
- simorgh/execution/script.py:82,90 `run_script` sets `PYTHONPATH=repo_root` and `cwd=str(self._config.repo_root)` for every kind, worktree or not
- docs/architecture-review-2026-09-18.html:57 and docs/architecture-third-opinion-2026-09-18.md:18 rate worktree isolation as 'accurate'/'sound' with no mention of the chat-profile bypass; the finding is not in the known list

**severity adjustment:** keep

**corrected claim:** Only `patch` and `skill` task kinds get a worktree (session.py:59, worker.py:403 makes chat kind="chat"); the CHAT profile carries `apply_source_patch`, `replace_in_file` and `run_script` (and `install_package`), which resolve to `config.repo_root` when no worktree exists (service.py:795, tools.py:109-123) and are bounded only by `write_scopes_source` (simorgh/, simorgh_skills/, tests/, tools/, docs/, workspace/) plus Guardian's ProtectedRule (guardian/, execution/, contracts/, kernel/, SOUL.md, simorgh.toml, bootloader). So a chat turn can edit the non-core packages of the running process, its tests and tools, in the live checkout with no rebase, suite gate or landing; `run_script` additionally always runs at repo_root for every kind. `install_package` is a weaker example since worktrees never isolated the interpreter environment.

