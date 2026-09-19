# refute:proportionality:Protected paths are enforced on the prop

*Workflow: review · Phase: Refute · Agent id: `a583e5677b9e42462` · Tool calls: 16*

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
| 2 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/worktree.py (from line 170) | 170 return Opened(path, head.stdout.strip() if head.returncode == 0 else "", True, branch) 171 172 # -- land --------------------------------------------------- |
| 3 | Read | /Users/saeed/ws/Simorgh/simorgh/execution/tools/shell.py (from line 80) | File does not exist. Note: your current working directory is /Users/saeed/ws/Simorgh. |
| 4 | Bash | Locate shell refusal rules and protected-subject config | (eval):1: no matches found: simorgh/execution/tools/*.py --- ls: simorgh/execution/tools/: No such file or directory --- simorgh/guardian/rules.py:31:_SUBJECT_A |
| 5 | Bash | Read ProtectedRule, find the shell tool and protected subject list |  # # But `read_only` describes whether EXECUTION tracks a write # side-effect for this tool's normal outputs -- not whether its # payload can write to disk. `ru |
| 6 | Bash | Read shell refusals, protected subjects, writewatch, and land wiring | # Patterns refused outright, with the reason the model is told. Ordered # by how bad the accident is, not by how likely. DEFAULT_SHELL_REFUSALS: dict[str, str]  |
| 7 | Bash | Check for protected-path checks in execution tools, pathsafety, git_commit, shell cwd | ---PROTECTED-IN-EXEC simorgh/execution/pathsafety.py:54:# `write_scopes_source` and Guardian's protected list answer -- and simorgh/execution/pathsafety.py:55:# |
| 8 | Bash | Check simloader bless and Proposal/DecisionContext shapes | ---SIMLOADER 500: commit, and the loader had verified a different tree.""" 547:def gate_selection(repo: Path, *, all_tests: bool) -> list[str]: ---CONTRACTS sim |
| 9 | Bash | Find the Guardian rule pipeline entry point and read git_commit | __init__.py __pycache__ api.py charter.py config.py pipeline.py posture.py README.md rules.py service.py tokens.py --- simorgh/guardian/pipeline.py:15:class Pip |
| 10 | Bash | Check ToolContext root and simloader bless flow | 2:112: A task working in its own worktree (execution/worktree.py) carries 3:113: that tree on `ctx.root`, set by the service from the task id, and 4:116: of wor |
| 11 | Bash | Read Guardian pipeline, rule list, and simloader run gating | """Runs `rules.DEFAULT_PIPELINE` in order and folds the per-rule Decisions into one Verdict (09-guardian.md section 5.1): the first deny wins outright; otherwis |
| 12 | Bash | Run the Guardian rule pipeline offline against the four claimed commands | Traceback (most recent call last): File "/private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/scratchpad/repro.py", line 2, in < |
| 13 | Bash | Check Posture, ReversibilityRule, and live config for guardian settings | 17:class Posture: 18- level: str = "guarded" 19- baseline: str = "guarded" 20- reasons: list[str] = field(default_factory=list) 21- 22- def tighten(self, to: st |
| 14 | Bash | Rerun the offline Guardian pipeline reproduction with the repo on the path | irreversible_requires_human True bandit True approved apply_skill [] import os \| def run(text): \| os.execvp('/bin/sh',['sh','-c', approved apply_skill [] import |
| 15 | Bash | Run the offline Guardian pipeline reproduction under a unique filename | classifier_enabled False irreversible_requires_human True CMD: cp workspace/rules.py simorgh/guardian/rules.py guardian: denied [protected] ("'simorgh/guardian/ |
| 16 | Bash | Check where worktrees live and how the land tool is invoked | ---WORKTREE-PATH 94: """Owns `<home>/<task_id>` worktrees of `repo`. 95- 96- `gate` runs the whole suite against a tree and returns a 97- `ToolResult`; `None` l |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual claim checks out against the code as it is today, and the offline reproduction matches the finding's evidence line for line. ProtectedRule is a substring scan over `[\w./-]+` tokens (rules.py:152-161) gated by a write-sign regex (rules.py:198-209, 228-231), compared against `protected_subjects` by `in` (rules.py:327-333); the rule's own comments admit a path assembled from pieces defeats it (rules.py:147-151, 310-312). `_land` (worktree.py:178-251) does status -> rebase -> gate -> `merge --ff-only` and never inspects `git diff --name-only main_sha..branch_sha`. The shell refusal for the main checkout only matches the `git -C <...>Simorgh` form (shell.py:115); `cd /Users/saeed/ws/Simorgh && git add -A && git commit` is approved by Guardian and not refused by the shell. Additionally `GitCommitTool` (tools.py:2406-2470) has no write-scope or protected-path check at all, which config.py:35 already notes and which is still true. The only downstream defences are simloader's unit-suite gate on boot (which passes any edit to guardian/ that keeps tests green) and creator-only bless, neither of which looks at which paths a Simorgh-authored commit touched.

On the skeptic's lens (is it a problem at one-laptop scale, is the fix proportionate): the threat model here is not an adversarial model but a task that drifts into editing guardian/execution/simloader, and the project's own history (rules.py:219-223, config.py:32-37) shows that exact accident already happened and landed. So this is not hypothetical. The core recommendation (a `git diff --name-only` check in `_land` against the 12 protected strings) is genuinely a handful of lines and is the exact, cheap check the finding says it is; it is proportionate. Two parts of the recommendation are over-built or misdirected for this scale: (1) making the live checkout unreadable to run_shell / a GIT_DIR sandbox is heavy and would break `_attribute`'s legitimate test runs on main (worktree.py:277) and the creator's own workflow; (2) a protected-path check in the bootloader's `bless` is pointless as written, because bless is run by the creator on the creator's own commits, which legitimately touch protected files -- if anything the loader should screen only commits authored `Simorgh <simorgh@localhost>` (the identity `_land` and `git_commit` stamp) that touch protected paths. Also note the `_land` check alone does not close the `cd`-to-live-checkout hole the finding itself raises; a cheaper exact closure is to snapshot main's HEAD before/after each run_shell/run_script and refuse or report when it moved, in the same style as writewatch.py. Severity stays high: it is a right-design-undermined case where the load-bearing boundary is a regex and the two cheap exact checkpoints (landing, git_commit) have none.

### evidence

- Offline reproduction (PYTHONPATH=/Users/saeed/ws/Simorgh, Pipeline(rules.DEFAULT_PIPELINE), classifier_enabled=False, run_shell proposals): `cp workspace/rules.py simorgh/guardian/rules.py` -> denied [protected]; `cp workspace/rules.py simorgh/guardi*/rules.py && git add -A && git commit -qm x` -> approved; `python3 -c "open('simorgh/gu'+'ardian/rules.py','w').write('')"` -> approved; `cd /Users/saeed/ws/Simorgh && git add -A && git commit -qm 'direct to main'` -> approved, shell refusal None; `git -C /Users/saeed/ws/Simorgh commit -am x` -> approved by Guardian but refused by shell ('acts on the main checkout from a worktree')
- simorgh/guardian/rules.py:147-152 `_PATHISH = re.compile(r"[\w./-]+")` with comment 'under-matches a path assembled from pieces ... under-matching costs the whole protection model, which is the trade this makes'
- simorgh/guardian/rules.py:310-312 'A path assembled from pieces already defeats the scan above'
- simorgh/guardian/rules.py:327-333 protected check is `protected in path or protected in canonical or ...` substring only
- simorgh/execution/worktree.py:178-251 `_land`: status --porcelain, rev-parse, merge-base, rebase, gate, `git merge --ff-only`; no `diff --name-only` and no reference to protected paths (grep 'protected' over simorgh/execution/*.py hits only pathsafety.py comments at :54-55)
- simorgh/execution/shell.py:115 the only main-checkout refusal: r"\bgit\s+-C\s+\S*Simorgh\b(?!/\S)"; shell.py:216-217 runs `subprocess.run(command, shell=True, cwd=root)` so a `cd` inside the command escapes the worktree root freely
- simorgh/execution/tools.py:2406-2470 GitCommitTool.run: tool_root -> nested_git_root -> git add/commit; no in_write_scope or protected check (config.py:35 'git_commit (which has no write-scope check)' still accurate)
- simorgh/guardian/config.py:21-31 DEFAULT_PROTECTED_SUBJECTS includes 'simorgh/guardian/', 'simorgh/execution/', 'simorgh/contracts/', 'simorgh/kernel/', 'simorgh.toml' plus simloader/sim.sh
- simloader.py: `grep -n 'protected\|name-only' simloader.py` returns nothing; simloader.py:21 'Sim cannot bless itself' and cmd_run (957-986) gates HEAD only by running tests
- simorgh/execution/worktree.py:277 `_attribute` runs `self.rerun(self.repo, candidates)` on the live checkout, so making the live checkout unreadable to tools would break landing itself

**severity adjustment:** keep

**corrected claim:** ProtectedRule is a substring scan over path-like tokens and is bypassed by a glob, a concatenated string, or a `cd` to the live checkout; neither `WorktreeManager._land` nor `GitCommitTool` re-checks touched paths against `protected_subjects`, and the bootloader only gates by test outcome. The cheap exact fix is a `git diff --name-only` check in `_land` (and in `git_commit`); a bless-time check should screen only Simorgh-authored commits, and a filesystem sandbox around the live checkout is disproportionate for this deployment and would break `_attribute`'s runs on main.

