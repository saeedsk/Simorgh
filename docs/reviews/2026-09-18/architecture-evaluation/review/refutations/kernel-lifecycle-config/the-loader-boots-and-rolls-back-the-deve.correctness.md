# refute:correctness:The loader boots and rolls back the deve

*Workflow: review · Phase: Refute · Agent id: `afe015a6064cc06f2` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 2 | Bash | Read sim.sh self-repair and worktree landing code | === sim.sh 30-60 === fi # The loader gates every file except itself, and it lives in the same # commit as the code it judges -- so Sim could, in one commit, des |
| 3 | Bash | Check loader notes, git history, memory note, and landing lines | === decisions 57-62 === {"ts": 1789624021.0150201, "kind": "gate_skipped", "commit": "fa847ea", "why": "skipped by the operator during the unit suite"} {"ts": 1 |
| 4 | Bash | Read the loader run loop and check known-findings docs | === cmd_run 957-1075 === def cmd_run(repo: Path, notes: Path, *, full: bool, timeout_s: float, max_rollbacks: int, watchdog_s: float, sim_args: list[str], force |
| 5 | Bash | Confirm repo root wiring, detached-HEAD checks, exact line numbers, reflog | sim.sh:22:export SIMORGH_EXECUTION_REPO_ROOT="${SIMORGH_EXECUTION_REPO_ROOT:-$REPO_ROOT}" simorgh/execution/config.py:60: # `SIMORGH_EXECUTION_REPO_ROOT` enviro |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is true of the code today. simloader.py:880-882 refuses a rollback on a dirty tree and returns 2 without write_note; line 888 does `git checkout -q <tag>` which detaches HEAD, and main()'s command choices are only run/bless/status/rollback (no roll-forward; previous_tag's docstring at 851-859 says the mechanism "must never step forward"). The reflog independently confirms the human consequence: on 2026-09-09, 09-14, 09-15 and 09-17 HEAD moved "from <sha> to main" by a manual checkout after each rollback. worktree.py:192 reads `rev-parse HEAD` of the live repo and line 243 does `merge --ff-only` in that repo, with no abbrev-ref/symbolic-ref/branch-name check anywhere in the file, so on a detached HEAD the landing advances the detached HEAD, not main, while the docstring (lines 22-25) promises "fast-forward main" -- a latent bug not yet observed in history but real in code. sim.sh:45 `git checkout "$LAST_GOOD" -- simloader.py` writes a tracked file, which is_dirty (simloader.py:442-448, `--untracked-files=no`) counts as dirty, so the loader's own self-repair disables the subsequent rollback. decisions.jsonl line 59 is a watchdog note at commit a68ed8e followed at line 60 by gate_skipped with no rollback/rollback_failed note; cmd_run's watchdog branch (simloader.py ~1041-1046) calls cmd_rollback and both silent return paths (dirty=2, no older tag=1) write nothing, so "silently refused" holds even if the exact cause is not provable from the note. All three real rollbacks (dd54876, 5cadca0, 424c478) are Saeed-authored commits; 94/856 commits are Simorgh's. The finding is not in the orchestrator's known list; the audit doc lists the bootloader only as a strength. The dirty-tree half is partially acknowledged in the creator's private memory note, but the detached-HEAD/landing interaction and the sim.sh self-repair interaction are new. One soft spot: "most of the time during development" is an assertion (the tree is clean right now), but it does not affect the mechanism.

### evidence

- /Users/saeed/ws/Simorgh/simloader.py:880-882 -- `if is_dirty(repo): say("refusing: the working tree has uncommitted changes; a rollback would discard them", "fail"); return 2` with no write_note on that path
- /Users/saeed/ws/Simorgh/simloader.py:888 -- `done = git("checkout", "-q", target, cwd=repo)`; `grep -n checkout simloader.py` shows no checkout/switch back to a branch; main() choices are ("run", "bless", "status", "rollback")
- /Users/saeed/ws/Simorgh/simloader.py:851-859 previous_tag docstring: "it must never step forward" -- roll-forward is deliberately absent
- `git reflog --date=short | grep 'to main'` -> 424c478 HEAD@{2026-09-17}: checkout: moving from af3055c... to main; 5cadca0 HEAD@{2026-09-15}: moving from 91c7fb4... to main; d5703da HEAD@{2026-09-14}; f5bfbee HEAD@{2026-09-09} -- the creator returned from a detached HEAD by hand after each rollback
- /Users/saeed/ws/Simorgh/simorgh/execution/worktree.py:192 `main_head = _git(self.repo, "rev-parse", "HEAD")`; :243 `merge = _git(self.repo, "merge", "--ff-only", landed_from)`; `grep -n 'abbrev-ref\|detached\|symbolic' worktree.py` returns nothing; docstring :22-25 says "fast-forward main"
- /Users/saeed/ws/Simorgh/sim.sh:22 exports SIMORGH_EXECUTION_REPO_ROOT=$REPO_ROOT (the live checkout is the landing repo); sim.sh:45 `git checkout "$LAST_GOOD" -- simloader.py`
- /Users/saeed/ws/Simorgh/simloader.py:442-448 is_dirty uses `git status --porcelain --untracked-files=no` -- a restored tracked simloader.py counts as dirty
- /Users/saeed/ws/Simorgh/.simorgh_loader/decisions.jsonl:59 `{"kind": "watchdog", "commit": "a68ed8e", "why": "Sim exited 2 after 7s, inside the 60s watchdog"}` then :60 `{"kind": "gate_skipped", "commit": "a68ed8e", ...}` 23s later; grep for '"rollback' finds only lines 5, 27, 71
- /Users/saeed/ws/Simorgh/simloader.py ~1041-1046 watchdog branch: `if rollbacks < max_rollbacks and cmd_rollback(...) == 0: say("rolled back...")`; `return 4` -- a refused rollback leaves no note
- `git log --oneline | wc -l` = 856; `git log --author=Simorgh --oneline | wc -l` = 94; dd54876/5cadca0/424c478 are all authored Saeed
- ~/.claude/projects/-Users-saeed-ws-Simorgh/memory/feedback_live_checkout_uncommitted.md exists and records the 2026-09-14 refused rollback
- docs/architecture-audit-2026.md:10 lists the bootloader only as a strength; the known-findings list given by the orchestrator does not include dirty-tree refusal, detached HEAD, or landing-on-HEAD

**severity adjustment:** keep

