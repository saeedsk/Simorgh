# refute:proportionality:Chat sessions edit the live checkout whi

*Workflow: review · Phase: Refute · Agent id: `a9e21bbb8670d3717` · Tool calls: 9*

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
| 1 | Bash | Read the three cited code locations | WRAP_UP_TEXT = ("Your lookups are over -- no more tools this turn. Answer the person now, in one or two " "sentences, from what you found; say plainly what you  |
| 2 | Bash | Find write-scope definitions for source-editing tools | (eval):1: no matches found: simorgh/execution/tools/*.py ---- __init__.py __pycache__ capabilities.py config.py container.py doctext.py domainstatus.py energy e |
| 3 | Bash | Locate write scope enforcement across the execution tools | simorgh/execution/pathsafety.py:54:# `write_scopes_source` and Guardian's protected list answer -- and simorgh/execution/pathsafety.py:333:def in_write_scope(ra |
| 4 | Bash | Read write scopes, ctx.root assignment, worktree gating, Guardian protection, and writewatch |  # it started with -- docs, tests, tools and the rest are all # things a self-improving system has real reason to edit. Paths # are still repo-relative and `..` |
| 5 | Bash | Check Guardian protected subjects, chat-kind rules, worktree gate, and simloader dirty-tree handling | 21:DEFAULT_PROTECTED_SUBJECTS: tuple[str, ...] = ( 22- "docs/SOUL.md", 23- "src/orchestrator/soul.py", 24- "src/orchestrator/audit.py", 25- "src/orchestrator/ap |
| 6 | Bash | Check boot behaviour on dirty tree, design doc wording, runtime config, and which profiles carry the write tools | ---- simloader boot with dirty tree # imports `simorgh` -- see the module docstring). RESTART_EXIT_CODE = 75 # The last checkout the gate passed. The suite take |
| 7 | Bash | Inspect the untracked simorgh/big.py, the design rationale, and where worktrees are switched on | -rw-r--r--@ 1 saeed staff 6013 Sep 18 18:19 simorgh/big.py # yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy |
| 8 | Bash | Check whether the ledger records a chat-turn write of simorgh/big.py | Exit code 1 ledger index.json idem streams LOCK snapshots (eval):1: no matches found: ledger/*.jsonl latest: |
| 9 | Bash | Search the newest ledger streams for a record of simorgh/big.py being written | trace%3A4ac9ccd3-3db5-4579-b715-e18b9c9b1c6c.jsonl system.jsonl trace%3Abffae277-2f6a-44c6-b68d-5502f9ed7a36.jsonl trace%3A1091ef2d-c5af-4d05-895a-40de8bbfe027. |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line reads as claimed, and the surrounding code closes the escape routes a skeptic would look for. Chat sessions are built with kind="chat", mode="execute" (simorgh/orchestration/worker.py:403), so `_uses_worktree` (session.py:753-754) returns False on kind alone, regardless of the worktrees switch (which defaults on: orchestration/config.py:113, and ~/.simorgh/simorgh.toml has no [orchestration] override). `apply_source_patch` (execution/tools.py:1685) and `replace_in_file` (tools.py:2310) both pass `write_scopes_source`, which is `("simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/", "workspace/")` (execution/config.py:120-126), and resolve against `tool_root`, which returns `config.repo_root` whenever `ctx.root` is None (tools.py:109-122). The CHAT profile also sets `verify=False, max_revisions=0`, so a chat edit to simorgh/ gets no verification pass either. The design doc's stated motive ('a process standing on a moving floor', docs/plans/worktree-landing-design.md:18-20) is exactly the situation chat recreates. The profile's own comment (profiles.py:54-58) says the reason chat got write tools was `workspace/`, so the intent is narrower than what is enforced -- the project's own 'unconnected wire' shape.

Mitigations exist but lower, not remove, the problem: Guardian's `protected_subjects` (guardian/config.py:21-41) keep chat out of guardian/, execution/, contracts/, kernel/, simloader.py, sim.sh and SOUL.md, so the safety core is not exposed; and simloader refuses to trust or roll back a dirty tree (simloader.py:805, 880, 920: `source_fingerprint` returns "" when `is_dirty`). But that backstop converts the hazard into a blocked rollback rather than preventing it -- the memory note 'Live checkout, keep it committed' records the creator hitting exactly that. Everything outside the protected list (orchestration/, persona/, learning/, voice/, cognition/, tests/, tools/) is writable from a chat turn on the live tree, un-gated, and auto-approved as 'reversible' under sim.sh's default.

Scale lens: this is not over-engineering at one-laptop scale. The fix is small and uses machinery that already exists: `_write_scoped_file` already takes `write_scopes` as a parameter, so a per-kind scope (chat -> workspace/ only) is a tuple, and `start_task` is already in the CHAT profile as 'the escape hatch from a one-shot reply into work that resumes' (profiles.py:60-63). The recommendation is aligned with the creator's own design rather than adding new process. One caveat: I did not independently verify that `run_script`/`install_package` operate against the live tree (I confirmed only that they are in the CHAT profile), but the finding does not depend on them -- the two file-writing tools alone establish it. The untracked `simorgh/big.py` (mtime 18:19 today) is a live example of stray untracked code in simorgh/, but the three newest ledger trace streams do not record it, so I do not attribute it to a chat turn.

### evidence

- simorgh/orchestration/session.py:59 `WORKTREE_KINDS = frozenset({"patch", "skill"})`; :753-754 `_uses_worktree` returns False when `session.kind not in WORKTREE_KINDS`
- simorgh/orchestration/worker.py:403 chat Session built with `kind="chat", mode="execute"`
- simorgh/orchestration/profiles.py:59 CHAT tools include `"apply_source_patch", "replace_in_file", "install_package", "run_script"`; :54-58 comment gives the reason as `workspace/` writes; :60-63 `start_task` already present as the escape hatch; CHAT has `read_only=False, max_revisions=0, verify=False`
- simorgh/execution/config.py:120-126 `write_scopes_source = ("simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/", SCRATCH_PREFIX)`
- simorgh/execution/tools.py:109-122 `tool_root` returns `config.repo_root` when `ctx.root` is None; :1685 apply_source_patch and :2310 replace_in_file both use `write_scopes_source` + `tool_root`
- simorgh/orchestration/config.py:113 `worktrees: bool = True`; `grep worktree ~/.simorgh/simorgh.toml` -> no override
- simorgh/guardian/config.py:21-41 DEFAULT_PROTECTED_SUBJECTS covers guardian/, execution/, contracts/, kernel/, simloader.py, sim.sh, SOUL.md, simorgh.toml -- but not orchestration/, persona/, learning/, voice/, cognition/, tests/, tools/
- simloader.py:805 'refusing: the working tree has uncommitted changes'; :880 'a rollback would discard them'; :920 `source_fingerprint` returns "" when dirty -- the backstop turns a chat source edit into a blocked gate/rollback rather than preventing it
- docs/plans/worktree-landing-design.md:18-20 'A process standing on a moving floor. A half-written module sat under a process that might import it ... a bad edit was live before any gate saw it.'
- `git status --porcelain` shows `?? simorgh/big.py` (6013 bytes, 18:19 today): untracked code inside simorgh/ on the live checkout; provenance not established in the three newest ledger streams

**severity adjustment:** keep

