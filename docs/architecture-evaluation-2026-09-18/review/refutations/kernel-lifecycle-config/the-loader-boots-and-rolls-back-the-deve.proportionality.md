# refute:proportionality:The loader boots and rolls back the deve

*Workflow: review · Phase: Refute · Agent id: `a019d8489e2f8fa45` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "The loader boots and rolls back the development checkout, so rollback is refused when it is needed, detaches HEAD, and diverts Sim's own landings",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "Running the A/B-image pattern against the same git checkout the creator edits means rollback is disabled whenever the tree is dirty (most of the time during development), a successful rollback leaves HEAD detached with no roll-forward, worktree landing then fast-forwards that detached HEAD instead of main, and sim.sh's loader self-repair itself dirties the tree and thereby disables rollback.",
    "evidence": [
      "simloader.py:877-897 cmd_rollback: `if is_dirty(repo): say(\"refusing: the working tree has uncommitted changes...\"); return 2` (no write_note on this path), then `git checkout -q target` (line 888) -- detached HEAD; grep for 'checkout' in simloader.py finds no return-to-branch logic.",
      ".simorgh_loader/decisions.jsonl lines 59-60: `{\"kind\": \"watchdog\", \"commit\": \"a68ed8e\", \"why\": \"Sim exited 2 after 7s, inside the 60s watchdog\"}` followed 23 s later by `{\"kind\": \"gate_skipped\", ...}` with no rollback/rollback_failed note between -- the watchdog rollback was silently refused.",
      "simorgh/execution/worktree.py:192 `main_head = _git(self.repo, \"rev-parse\", \"HEAD\")` and the landing `merge --ff-only` (worktree.py, ~line 229) run in the live repo, i.e. 'main' means whatever HEAD is; the module docstring (lines 22-25) says 'fast-forward main'.",
      "sim.sh:45 `git checkout \"$LAST_GOOD\" -- simloader.py` modifies a tracked file, which is_dirty (simloader.py:444-450, `--untracked-files=no`) then reports as dirty.",
      "git log: all three real rollbacks (dd54876, 5cadca0, 424c478) were on commits authored 'Saeed'; `git log --author=Simorgh --oneline | wc -l` = 94 of 856 commits -- Sim's own commits land pre-gated via worktree.land and have never been the thing rolled back.",
      "Memory note feedback_live_checkout_uncommitted: 'sim.sh boots from the repo I edit; half-done edits get gated and block rollback'."
    ],
    "why_it_matters": "The bootloader analogy works in embedded systems because the image slot is not the engineer's workbench. Here the same directory is the workbench, the deploy target, and Sim's landing target, so the three interfere: the human's uncommitted edit blocks the rollback, the rollback strands the human on a detached HEAD, and Sim's next patch lands on that detached HEAD where a later `git checkout main` orphans it.",
    "recommendation": "Separate deploy from dev with one git worktree: the loader owns `~/.simorgh/live` (git worktree add on a `live` branch), boots Sim from it, and rollback/roll-forward are `git -C live reset --hard sim-good-NNNN` / `... main` there -- the dev tree's state never matters, HEAD is never detached in the creator's checkout, and landing targets the `main` branch by name (`rev-parse main`, `update-ref`), not HEAD. Roughly 50 lines in simloader.py and sim.sh. Also write a note on the dirty-refusal path so Sim can see that a rollback did not happen.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read is_dirty and cmd_rollback in simloader.py | # ------------------------------------------------------------------- git def git(*args: str, cwd: Path, check: bool = False) -> subprocess.CompletedProcess: do |
| 2 | Bash | Check decisions log, sim.sh self-repair, worktree landing, git counts | {"ts": 1789623012.6040409, "kind": "gate_skipped", "commit": "2cb3960", "why": "skipped by the operator during the unit suite"} {"ts": 1789623529.007793, "kind" |
| 3 | Bash | Read the watchdog path in run loop and landing merge | 30:both fast-forward the same main. `git merge --ff-only` refuses if the 148: head = _git(path, "rev-parse", "HEAD") 159: exists = _git(self.repo, "rev-parse",  |
| 4 | Bash | Check reflog for detached-HEAD periods and rollback context | 22:424c478 HEAD@{2026-09-17 03:07:41 -0700}: checkout: moving from af3055c4985f1514a25b2c0921e886695eded342 to main 23:af3055c HEAD@{2026-09-17 02:54:34 -0700}: |
| 5 | Bash | Check for commits made while detached and the watchdog-time reflog | 6a92d49 HEAD@{2026-09-17 17:15:19 -0700}: commit: Words as they are said: a streaming recogniser 3746e15 HEAD@{2026-09-17 03:12:05 -0700}: commit: Persian is a  |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every mechanism the finding names is real and I verified it in code and in the loader's own logs: the dirty-tree refusal writes no note (simloader.py:880-882), rollback is a bare `git checkout -q <tag>` with no return-to-branch anywhere in the file (simloader.py:888; grep for checkout/switch/symbolic-ref finds nothing), worktree.land reads `rev-parse HEAD` and runs `merge --ff-only` in the live repo so it would advance a detached HEAD rather than `main` (worktree.py:192, 243), and sim.sh's self-repair `git checkout "$LAST_GOOD" -- simloader.py` (sim.sh:45) dirties a tracked file that is_dirty (`--untracked-files=no`, simloader.py:449) then counts. The watchdog event at decisions.jsonl:59 was indeed followed by no rollback/rollback_failed note and the reflog shows no checkout at 2026-09-16 23:1x, so that rollback was silently refused while older tags existed (previous_tag would have found an ancestor tag).

What the finding overstates is the consequence at this system's scale, and therefore the severity and the shape of the fix. The reflog shows the three real rollbacks each left HEAD detached for 4, 1 and 13 minutes (06:06->06:10 on 09-14, 18:23->18:24 on 09-15, 02:54->03:07 on 09-17), the creator returned to main by hand every time, and no commit or landing happened while detached -- zero orphaned work in 856 commits. The one silent watchdog refusal was recovered by the operator 23 s later (decisions.jsonl:60). The `gate_skipped ... by the operator` notes (lines 55-62 and many more) prove the loader runs with the developer at the keyboard, which is exactly the regime where 'rollback refused because you have uncommitted edits' is the correct, low-cost answer rather than a failure. The recommended second `live` worktree is not a free 50 lines: the loader's own comments (simloader.py:1024-1027) say a `restart` is 'exactly how new code from this session reaches a running Sim', i.e. the creator relies on booting the checkout he edits; a `live` worktree reset to `main` would make uncommitted edits invisible to Sim and force a commit before every restart, trading a rare, hand-recoverable inconvenience for friction on every iteration. The design (boot the dev checkout, refuse to destroy uncommitted work) is defensible for one developer on one laptop; what is missing are three small implementation gaps: a note on the dirty-refusal path, landing that names `refs/heads/main` (rev-parse main + update-ref) instead of HEAD, and re-attaching after a rollback (e.g. `git checkout -B` onto a rollback branch, or printing the detached state loudly). That is category (b), not (a) 'wrong design', and medium rather than high: the unattended case (rollback -> detached -> Sim lands -> branch deleted, commit only in reflog) is a genuine latent loss path, but it has never fired and the narrow fix in worktree.land closes it without moving the deploy target.

### evidence

- simloader.py:880-882 `if is_dirty(repo): say("refusing: the working tree has uncommitted changes; a rollback would discard them", "fail"); return 2` -- no write_note on this path (write_note is only called at 893 and 896).
- simloader.py:888 `done = git("checkout", "-q", target, cwd=repo)` -- detaches HEAD; `grep -n "checkout\|reset --hard\|switch" simloader.py` shows no code that returns to a branch; only simloader.py:963 status card knows HEAD can be '(detached)'.
- simloader.py:449 `git("status", "--porcelain", "--untracked-files=no")` -- tracked changes count as dirty; sim.sh:45 `git checkout "$LAST_GOOD" -- simloader.py` modifies a tracked file.
- simorgh/execution/worktree.py:192 `main_head = _git(self.repo, "rev-parse", "HEAD")`, :243 `merge = _git(self.repo, "merge", "--ff-only", landed_from)`, :246 `new_main = _git(self.repo, "rev-parse", "HEAD")` -- 'main' is whatever HEAD is; docstring lines 22-25 say 'fast-forward main'.
- .simorgh_loader/decisions.jsonl:59 `{"kind": "watchdog", "commit": "a68ed8e", "why": "Sim exited 2 after 7s, inside the 60s watchdog"}` at ts 1789626198; line 60 `gate_skipped` at ts 1789626221 (23 s later); no rollback/rollback_failed between; `git reflog` shows no checkout on 2026-09-16 23:1x, only commits d5debc1 23:11, a68ed8e 23:16, 4ada997 23:25 -- the operator was present and committing.
- git reflog --date=iso: `af3055c 02:54:34 checkout: moving from main to sim-good-0015` then `424c478 03:07:41 checkout: moving from af3055c... to main`; `91c7fb4 18:23:39 moving from main to sim-good-0008` then `5cadca0 18:24:38 ... to main`; `e7a1caa 06:06:53 moving from main to sim-good-0004` then `d5703da 06:10:02 ... to main` -- three detached windows of 13, 1 and 4 minutes, no commit entries inside any of them.
- decisions.jsonl:5,27,71 -- exactly three `rollback` notes; `git log --author=Simorgh --oneline | wc -l` = 94; `git log --oneline | wc -l` = 856; `git status --porcelain --untracked-files=no | wc -l` = 0 today; `git branch --show-current` = main.
- simloader.py:1024-1027 comment: 'a `restart` is exactly how new code from this session reaches a running Sim' -- the edit->restart loop depends on booting the checkout the creator edits, which a separate `live` worktree reset to main would break for uncommitted edits.
- decisions.jsonl:55-62 and 69-76: repeated `gate_skipped ... skipped by the operator during the unit suite` -- the loader runs with the developer at the keyboard.

**corrected claim:** The loader boots and rolls back the same checkout the creator edits, so a rollback is refused (silently, with no note) whenever tracked files are modified, a successful rollback leaves HEAD detached with nothing that re-attaches it, and worktree.land fast-forwards HEAD rather than the `main` branch by name. All three are verified in code and one silent refusal is visible in the loader log. At this system's scale the observed cost has been nil: three rollbacks in 856 commits, each detached window closed by hand within 1-13 minutes, no commit ever made or landed while detached. The design (boot the dev checkout; never discard uncommitted work) is reasonable for one developer who visibly relies on the edit->restart loop; the gaps are implementation: write a note on the dirty-refusal path, make landing target `refs/heads/main` (rev-parse main + update-ref) instead of HEAD, and re-attach or loudly report the detached state after a rollback. A second `live` worktree is not needed and would cost the live-edit loop.

**severity adjustment:** lower

