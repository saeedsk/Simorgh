# refute:correctness:Protected paths are enforced on the prop

*Workflow: review · Phase: Refute · Agent id: `a5502d89374a0c267` · Tool calls: 19*

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
    "title": "Protected paths are enforced on the proposal's text, not on the diff that lands; a glob or a concatenated string walks straight through, and worktree_land never re-checks",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "ProtectedRule is a substring scan of path-looking tokens in the command/code (rules.py:152-161, 212-232) and its docstring admits 'a path assembled from pieces already defeats the scan'; `WorktreeManager._land` rebases and fast-forwards whatever the branch contains with no `git diff --name-only` check against protected subjects, so the one place a protected-path check is cheap and exact has none.",
    "evidence": [
      "Offline pipeline (live default): `denied cp workspace/rules.py simorgh/guardian/rules.py` but `approved cp workspace/rules.py simorgh/guardi*/rules.py && git add -A && git commit -qm x` and `approved python3 -c \"open('simorgh/gu'+'ardian/rules.py','w').write('')\"`",
      "simorgh/execution/worktree.py:190-260 `_land`: status -> rebase -> gate -> `git merge --ff-only`; no path inspection of `main_sha..branch_sha`",
      "simorgh/guardian/rules.py:147-151 'Deliberately crude ... under-matching costs the whole protection model, which is the trade this makes'",
      "Offline pipeline: `approved cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm 'direct to main'` (shell refusal only matches `git -C .../Simorgh`, shell.py:107-108) -- landing can be bypassed entirely by cd-ing to the live checkout"
    ],
    "why_it_matters": "The corrigibility boundary (guardian/, execution/, contracts/, kernel/, simloader.py) is the load-bearing safety idea of the whole system and it is enforced by a regex over model text. The landing step already has the exact list of touched files for free.",
    "recommendation": "In `_land`, run `git diff --name-only <main_sha>..<branch_sha>` and refuse if any path matches `protected_subjects` (pass the list in from Guardian's config or duplicate the 12 strings; it is a 6-line change). Do the same in the bootloader's bless. Add `cd`-to-repo-root and `git commit` outside the worktree to the shell refusals, or better, run `run_shell` from a worktree with `GIT_DIR`/`GIT_WORK_TREE` unset and the live checkout path made unreadable by the sandbox.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/guardian/rules.py (from line 130) | 130 proved the consequence, 2026-09-09: a `run_container` proposal whose 131 `command` was `["python3", "-c", "import subprocess; subprocess.run(...)"]` 132 rea |
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/worktree.py (from line 150) | 150 return Opened(path, head.stdout.strip(), False, branch) 151 # A directory that looks like a worktree but git cannot read: 152 # start over rather than work  |
| 3 | Bash | Read shell refusal and grep landing/bootloader for protected-path checks | sed: /Users/saeed/ws/Simorgh/simorgh/execution/tools/shell.py: No such file or directory ---- /Users/saeed/ws/Simorgh/simorgh/execution/worktree.py:204: conflic |
| 4 | Bash | Locate shell tool refusal, protected subjects definition, and any land-time path check | ---- simorgh/execution/pathsafety.py simorgh/kernel/service.py ---- simorgh/guardian/config.py:21:DEFAULT_PROTECTED_SUBJECTS: tuple[str, ...] = ( simorgh/guardi |
| 5 | Bash | Find shell tool file, pathsafety protected handling, kernel service wiring, and ProtectedRule.evaluate | simorgh/execution/config.py simorgh/execution/tools.py simorgh/execution/shell.py ---- simorgh/execution/pathsafety.py:54:# `write_scopes_source` and Guardian's |
| 6 | Bash | Read shell refusal list, pathsafety protections, protected subject list, and shell cwd handling |  "changes permissions on the whole tree", r"\bcrontab\s+-r\b": "deletes the user's scheduled jobs", r"\bfind\s+/\s[^\|]*-delete\b": "deletes everything it finds  |
| 7 | Bash | Find how tests build a Guardian pipeline offline | simorgh/guardian/pipeline.py:1:"""Runs `rules.DEFAULT_PIPELINE` in order and folds the per-rule simorgh/guardian/pipeline.py:15:class Pipeline: simorgh/guardian |
| 8 | Bash | Read test fixture helpers, pipeline fold logic, and the default pipeline order | """Per-rule tables for `simorgh.guardian.rules` (09-guardian.md section 5.1's pipeline). Each rule is a pure function of (Proposal, DecisionContext), so these a |
| 9 | Bash | Read ToolInfo and Proposal field definitions | 37:class ToolInfo: 38- name: str 39- read_only: bool 40- reversibility: str 41- 42- 43-@dataclass(frozen=True) 44-class BudgetStatus: 45- provider: str 46- frac |
| 10 | Bash | Run the Guardian pipeline offline on the four cited commands | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/repro.py", line 2, in < |
| 11 | Bash | Check bootloader bless for path checks, shell refusal application and cwd routing | 21: it independently verified that commit. Sim cannot bless itself. 34: python simloader.py bless gate HEAD and, if green, tag it known-good 85:# still has the  |
| 12 | Bash | Check whether prior reviews already report this finding | ---- protected, scope, denylist, static analysis, shellcheck, package, grant, immunity, budget, reversibility — protected paths protected paths, write scopes, |
| 13 | Bash | Run the Guardian pipeline offline on the cited commands with repo on the path | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/repro.py", line 25, in  |
| 14 | Bash | Check the post-run writewatch in run_shell for a protected-path check after execution | 49:# Safe to import at runtime: `writewatch` depends on nothing in this 52:from . import writewatch 213: before = writewatch.snapshot(root) 257: # command to sa |
| 15 | Bash | Read bootloader bless for any protected-path check | def cmd_bless(repo: Path, notes: Path, *, full: bool, timeout_s: float) -> int: rule("bless") if is_dirty(repo): say("refusing: the working tree has uncommitted |
| 16 | Bash | Rerun the offline pipeline reproduction printing the Verdict fields | denied protected ("'simorgh/guardian/rules.py' is protected ('simorgh/guardian/'); only the creator may edit it directly",) \| run_shell {'command': 'cp workspac |
| 17 | Bash | Check how ctx.root is set per task and whether git_commit tool checks paths |  tool = await self._load_skill(skill_name, path=f"{self._config.skill_dir}/{skill_name}.py") if tool is None: await self._publish_result(message, action_id, ok= |
| 18 | Bash | Check the prior review documents for overlap with this finding | 158: protected, scope, denylist, static analysis, shellcheck, package, grant, immunity, budget, reversibility — 175:as protected paths precisely because of that |
| 19 | Bash | Test shell refusal on the cd-based bypass and inspect worktree_land tool metadata | None \| cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm x 'acts on the main checkout from a worktree; land work with worktree_land' \| git -C /Users/sa |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every claim in the finding checks out against the code as it is today, and I reproduced the Guardian verdicts offline with the real DEFAULT_PIPELINE (no boot, no model). (1) ProtectedRule's path detection is `_PATHISH = re.compile(r"[\w./-]+")` (rules.py:152) applied to `code`/`command` text only when `_looks_like_a_write` matches (rules.py:212-232); `*` and `+` are not in the character class, so `simorgh/guardi*/rules.py` tokenises to `simorgh/guardi` and `/rules.py` and `'simorgh/gu'+'ardian/rules.py'` to two fragments, none containing a protected subject. The comment at rules.py:147-151 and the docstring at rules.py:308-309 ('A path assembled from pieces already defeats the scan above') admit this. (2) `WorktreeManager._land` (worktree.py:178-251) does status -> rebase -> gate -> `merge --ff-only`; the only `diff --name-only` in the file is at line 204 and it lists rebase conflicts (`--diff-filter=U`), not touched paths; `grep -n protected simorgh/execution/worktree.py simloader.py` returns nothing, and `cmd_bless` (simloader.py:803-847) runs only is_dirty/untracked_code/run_gate. So neither landing nor bless inspects which files a branch changed. (3) The shell refusal for the main checkout is a single regex `\bgit\s+-C\s+\S*Simorgh\b(?!/\S)` (shell.py:115, not 107-108 as cited, a minor line slip); `refusal_for('cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm x')` returns None while the `git -C` form is refused. Task-scoped run_shell runs with cwd=worktree (service.py:794, shell.py:212-224), so a `cd` to the live checkout inside the command escapes the worktree. Worse for the design: run_python_sandboxed runs with `cwd=str(self._config.repo_root)` (script.py:90), i.e. the LIVE checkout, so the concatenated-path write lands on the real simorgh/guardian/rules.py with no landing step involved at all. Not in the known-findings list: prior reviews (architecture-review-2026-09-18.html:175,243; audit 2026:9-10; third-opinion:58) cite protected paths and worktree isolation only as strengths/remediations. Classification 'right design undermined by implementation' is apt: the corrigibility boundary is real config (guardian/config.py:21-40) but is enforced solely by a text scan on proposals, and the one exact, cheap check (the landed diff's file list) does not exist. Severity 'high' is fair; I would not raise it because it requires a model that is already trying to evade, and sim.sh's auto-approve is a known separate finding.

### evidence

- Reproduced with `PYTHONPATH=. python3 repro.py` building Pipeline(DEFAULT_PIPELINE) with Config() defaults, posture guarded, tool read_only=False: `denied protected ("'simorgh/guardian/rules.py' is protected ('simorgh/guardian/'); ...") | run_shell cp workspace/rules.py simorgh/guardian/rules.py`; `approved () | run_shell cp workspace/rules.py simorgh/guardi*/rules.py && git add -A && git commit -qm x`; `approved () | run_python_sandboxed open('simorgh/gu'+'ardian/rules.py','w').write('')`; `approved () | run_shell cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm 'direct to main'`
- /Users/saeed/ws/Simorgh/simorgh/guardian/rules.py:152 `_PATHISH = re.compile(r"[\w./-]+")` and :161 `_mentioned_paths` filters only `tests/` prefixes; :212-232 `_subject_paths` extends with mentioned tokens only if `_looks_like_a_write`
- /Users/saeed/ws/Simorgh/simorgh/guardian/rules.py:147-151 comment: 'Deliberately crude -- it looks for the literal name ... under-matches a path assembled from pieces ... under-matching costs the whole protection model, which is the trade this makes'; :308-309 'A path assembled from pieces already defeats the scan above'
- /Users/saeed/ws/Simorgh/simorgh/execution/worktree.py:178-251 `_land`: status --porcelain (183), rev-parse (192-193), merge-base --is-ancestor (197), rebase (201-202), gate (215-240), `merge --ff-only` (243); the only name-only diff is :204 `diff --name-only --diff-filter=U` for rebase conflicts. `grep -n 'protected\|name-only' simorgh/execution/worktree.py simloader.py` -> only worktree.py:204 (conflicts) and no 'protected' hit in either file
- /Users/saeed/ws/Simorgh/simloader.py:803-847 `cmd_bless`: is_dirty, untracked_code, run_gate, tag -- no per-file inspection
- /Users/saeed/ws/Simorgh/simorgh/execution/shell.py:115 `r"\bgit\s+-C\s+\S*Simorgh\b(?!/\S)"` is the only main-checkout refusal; `python3 -c` with `refusal_for`: `None | cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm x` vs `'acts on the main checkout from a worktree; land work with worktree_land' | git -C /Users/saeed/ws/Simorgh commit -qm x`
- /Users/saeed/ws/Simorgh/simorgh/execution/service.py:794 `root = self._worktrees.root_for(task_id)`; shell.py:212,224 `root = getattr(ctx, 'root', None) or self._config.repo_root` ... `subprocess.run(command, shell=True, cwd=root ...)` -- run_shell's cwd is the worktree, which an in-command `cd` escapes
- /Users/saeed/ws/Simorgh/simorgh/execution/script.py:90 `cwd=str(self._config.repo_root)` -- run_python_sandboxed runs in the live checkout, so the concatenated-path write hits the real protected file without any landing step
- /Users/saeed/ws/Simorgh/simorgh/guardian/config.py:21-40 DEFAULT_PROTECTED_SUBJECTS includes simorgh/guardian/, simorgh/execution/, simorgh/contracts/, simorgh/kernel/, simloader.py, sim.sh
- Prior reviews: docs/architecture-review-2026-09-18.html:175,243 and docs/architecture-audit-2026.md:9-10 and docs/architecture-third-opinion-2026-09-18.md:58 mention protected paths / worktree isolation only as strengths; none reports the text-scan-only enforcement or the missing landing-time check

**severity adjustment:** keep

**corrected claim:** Minor line correction only: the `git -C` shell refusal is at simorgh/execution/shell.py:115 (not 107-108), and `_land` spans worktree.py:178-251 (not 190-260). Additionally, run_python_sandboxed runs with cwd = the live repo_root (script.py:90), so the concatenated-path bypass writes the real protected file directly, not via landing.

