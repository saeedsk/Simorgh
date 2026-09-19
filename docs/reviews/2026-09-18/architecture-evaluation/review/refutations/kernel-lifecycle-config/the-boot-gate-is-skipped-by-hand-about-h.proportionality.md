# refute:proportionality:The boot gate is skipped by hand about h

*Workflow: review · Phase: Refute · Agent id: `af46901498260b832` · Tool calls: 8*

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
    "title": "The boot gate is skipped by hand about half the time, gates the wrong moment, and runs the judged code with the live environment",
    "kind": "right-design-undermined",
    "severity": "medium",
    "claim": "The 45-48 s core gate is bypassed with the skip key on 34 of 70 gate opportunities in the last five days, cannot be reused while any untracked .py exists (as now), duplicates the landing-time gate that already protects Sim's own commits, treats a config/boot error as a bad image, and inherits the operator's environment and $HOME so the loader's 'never runs the code it is judging' principle is violated on the environment side.",
    "evidence": [
      ".simorgh_loader/decisions.jsonl (99 decisions, 2026-09-14..18): gate_skipped 34, blessed 20, gate_reused 7, tag_withheld 5, gate_failed 4, restart 24, rollback 3, watchdog 1; restart -> next gate decision median 45 s, p90 58 s.",
      ".simorgh_loader/unit_baseline-core.json: {\"tests\": 3348, \"seconds\": 45.67}; a whole-suite gate in the notes: '5940 passed ... in 445.02s (0:07:25)'.",
      "`python3 simloader.py status`: 'untracked CODE -- the gate would run it, no tag can be earned while it is here: simorgh/big.py' (a 2-line scratch file) -- source_fingerprint returns '' so already_verified never matches (simloader.py:916-954).",
      "simloader.py:383-386 `subprocess.Popen(argv, cwd=cwd, ...)` with no env=; sim.sh:22 exports SIMORGH_EXECUTION_REPO_ROOT into that environment; tests/simorgh/kernel/test_the_suite_cannot_see_the_operators_env.py documents the consequence ('5,007 files written into the live data_dir') and the fix lives in the suite's own conftest, i.e. in the judged code.",
      "simloader.py:1042-1048 treats any non-zero exit inside 60 s as a bad image; kernel/cli.py:392-397 returns 2 for both ConfigError and KernelBootError; the one real watchdog event was 'Sim exited 2 after 7s'.",
      "simorgh/execution/worktree.py:22-25: landing already runs 'the gate -- the whole suite -- in a copy of the rebased tree; fast-forward main'."
    ],
    "why_it_matters": "A gate that the operator routinely skips protects the tag ledger, not the boot. Its real catches (4 gate_failed) were all the creator's own un-tested commits; Sim's commits are gated at landing. Meanwhile every restart pays 45 s or a keypress, and the gate cannot tell 'the code regressed' from 'the house is offline'.",
    "recommendation": "Move the default to gate-at-change, not gate-at-boot: `run` reuses the last green verdict for the current commit regardless of untracked non-test scratch (or ignore untracked files outside tests/ and simorgh/ that the suite does not import), gates only when HEAD moved past the newest tag, and offers `--force-gate` for the rest. Give the pytest child a loader-side env allowlist (PATH, HOME=<tmp>, PYTHON*) so the judged code cannot inherit the live data dir. Split exit codes so a ConfigError (2) never triggers the watchdog rollback while a KernelBootError (3) does.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read loader spawn and fingerprint code |  1112 simloader.py elif plain.startswith("→"): self.detail = f"trial {self.done + 1}/{self.total}: {plain[1:].strip()[:60]}" elif plain.startswith(("🔧", "🔍", "🎓 |
| 2 | Bash | Read cmd_run and watchdog logic |  branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip() where = str(repo).replace(str(Path.home()), "~", 1) if _fancy(): card([("repo", wher |
| 3 | Bash | Tally loader decisions and read untracked_code logic | == decisions == 99 .simorgh_loader/decisions.jsonl Counter({'gate_skipped': 34, 'restart': 24, 'blessed': 20, 'gate_reused': 7, 'tag_withheld': 5, 'gate_failed' |
| 4 | Bash | Check commit authors, status output, exit codes, worktree, sim.sh, conftest test | == gate_failed commits authors == 36b9813 Saeed 2026-09-14 `restart` warns when nothing will bring Sim back up dd54876 Saeed 2026-09-14 Guard test allows the on |
| 5 | Bash | Read run_gate, landing gate, conftest env handling, commit authorship, restart timing | == run_gate == def run_gate(repo: Path, *, full: bool, timeout_s: float, notes: Path \| None = None, allow_skip: bool = False, all_tests: bool = False) -> tuple[ |
| 6 | Bash | Check conftest env guard, default data dir, landing gate wiring, Sim commits, gate selection | == conftest locations == tests/simorgh/interface/conftest.py == default data_dir == simorgh/kernel/config.py:40: return Path(explicit).expanduser() simorgh/kern |
| 7 | Bash | Find env guard conftest, landing gate default, and gate function | == env guard == tests/simorgh/kernel/test_the_suite_cannot_see_the_operators_env.py conftest.py 1:"""Test-session isolation from the ambient environment. 3:`ker |
| 8 | Bash | Read loader principle, rollback behaviour, and the watchdog event context | == loader docstring == 16:never runs the code it is judging.** So: 18:- This file is stdlib only. It does not import `simorgh`. If the package 19: is broken eno |

## Structured reply

**refuted:** False

**verdict:** partly-true

**severity adjustment:** lower

**reasoning:** The measurable claims check out, but the framing ("gates the wrong moment", "duplicates the landing gate", "violates the loader principle") and half the recommendation do not survive the code.

Confirmed: decisions.jsonl has exactly the tallied kinds (gate_skipped 34 of 70 gate outcomes; restart->next gate median 45.0 s, p90 59.2 s). simloader.py:916-921 returns "" from source_fingerprint when untracked_code() is non-empty, so already_verified (940-954) never matches and record_green (925-928) silently no-ops; with simorgh/big.py present the core gate re-runs on every restart and can never earn a reuse (6 of 24 restarts ended in tag_withheld, i.e. a full 45 s run whose verdict was thrown away). stream() (simloader.py:383-386) spawns pytest with no env=, sim.sh:22 exports SIMORGH_EXECUTION_REPO_ROOT, and the SIMORGH_* strip lives in the repo root conftest.py:67-76. kernel/cli.py:392-397 returns 2 for both ConfigError and KernelBootError, and simloader.py:1042-1048 treats any non-zero exit within 60 s as a bad image. --force-gate already exists (simloader.py:1084-1085).

Refuted or overstated: (1) "Duplicates the landing gate": git log shows 287 of the last 300 commits are the creator's and 13 are Sim's; the landing gate (execution/service.py:262-264, on by default) only sees Sim's. All 4 gate_failed commits were the creator's, and 3 of them came immediately after a `restart`, so the boot gate is the ONLY gate for the dominant commit source and it already fires at the moment code changes. One catch was 93 failed / 37 errors. That is the gate working, not evidence it is misplaced. (2) "Gate-at-change" is already the design: already_verified reuses a green verdict when HEAD is unchanged and the tree is clean; `restart` re-gates because that is how new code reaches Sim (simloader.py:1030-1036). The only real gap is that the untracked-.py rule, whose documented reason (simloader.py:492-500) is about tags lying, is also applied to boot reuse. (3) "Violates the loader's principle": the principle at simloader.py:16-18 is import-time robustness ("stdlib only ... if the package is broken enough to fail at import, this still runs"), not environment hygiene; a test gate necessarily runs the judged code. A loader-side env allowlist is cheap defence in depth, but the conftest guard must remain the primary location because Sim's landing gate and run_tests tool also spawn pytest and would not be covered by a loader-only fix. (4) The watchdog event: the single 'exited 2 after 7s' on a68ed8e followed a skipped gate, produced no rollback (cmd_rollback refuses a dirty tree, simloader.py:880-882; no rollback or rollback_failed note exists), and the same commit booted fine 23 s later. Splitting exit codes is a ~5-line improvement, not an architectural fault. (5) Skips are a designed `run`-only convenience ("never offered to bless", simloader.py:561-562); every skip is logged and withholds tags, so the rollback ledger stays honest. At one developer / one laptop the cost is a keypress or 45 s per restart (~24 restarts in 5 days), against 4 real regressions caught.

Net: right design, with two small implementation gaps (reuse-for-boot vs reuse-for-tag should be split; exit codes should distinguish config from boot failure) and one optional hardening (env allowlist). Severity should drop to low; the recommendation to "move the default to gate-at-change" describes what already exists.

**corrected claim:** The boot gate's skip key was used on 34 of 70 gate runs in five days (each logged, each withholding a tag). With an untracked .py under simorgh/ present (as now), source_fingerprint returns "" so record_green is a no-op and already_verified can never match: every restart re-runs the 45 s core gate even on an unchanged, previously green HEAD. The pytest child inherits the operator's environment (no env= in stream()), so the SIMORGH_* strip must live in the repo's root conftest.py, which also correctly covers the landing gate and Sim's run_tests. kernel/cli.py returns 2 for both ConfigError and KernelBootError, so the 60 s watchdog cannot tell a config error from a broken image; the one such event did not roll back because the tree was dirty. The gate is not a duplicate of the landing gate: 287 of the last 300 commits are the creator's and are gated nowhere else, all 4 gate failures were such commits, and 3 followed a restart, i.e. the gate already runs at change. --force-gate already exists.

### evidence

- .simorgh_loader/decisions.jsonl: Counter({'gate_skipped': 34, 'restart': 24, 'blessed': 20, 'gate_reused': 7, 'tag_withheld': 5, 'gate_failed': 4, 'rollback': 3, 'watchdog': 1, 'bless_refused': 1}); restart->next gate: n=24 median 45.04 s, p90 59.16 s; outcomes after restart: gate_skipped 8, tag_withheld 6, blessed 5, gate_failed 3, gate_reused 2
- gate_failed commits all authored by the creator: 36b9813, dd54876, 5cadca0 ('93 failed, 2303 passed, 37 errors'), 424c478 (git log -1 --format='%an' each -> Saeed); git log -300 authors: 287 Saeed, 13 Simorgh
- simloader.py:916-921 source_fingerprint: `if is_dirty(repo) or untracked_code(repo): return ""`; :925-928 record_green returns without writing when fingerprint is ""; :940-954 already_verified returns "" on empty fingerprint
- simloader.py:489 _UNTRACKED_CODE = r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg)$|\.(py|pth)$"; :492-500 docstring gives the tag-lie rationale (untracked helper.py, sim-good-0001)
- python3 simloader.py status: 'untracked CODE -- the gate would run it, no tag can be earned while it is here: simorgh/big.py'
- simloader.py:383-386 subprocess.Popen(argv, cwd=cwd, stdout=PIPE, stderr=STDOUT, stdin=DEVNULL, text=True, bufsize=0) -- no env=; sim.sh:22 export SIMORGH_EXECUTION_REPO_ROOT; root conftest.py:38-76 strips SIMORGH_* and sets SIMORGH_COGNITION_PROVIDER_ORDER=floor
- simloader.py:16-18 principle text: 'never runs the code it is judging ... This file is stdlib only. It does not import simorgh. If the package is broken enough to fail at import, this still runs' -- an import-robustness principle, not an env one
- simloader.py:1084-1085 parser.add_argument('--force-gate', ...) already exists; :974 honours it
- simloader.py:1030-1036 restart (exit 75) re-gates the current checkout: 'a restart is exactly how new code from this session reaches a running Sim'
- simloader.py:1042-1048 `if returncode != 0 and ran_for < watchdog_s` -> cmd_rollback; simloader.py:880-882 cmd_rollback refuses a dirty tree (return 2, no note); kernel/cli.py:392-397 returns 2 for both ConfigError and KernelBootError
- decisions around the watchdog: 23:23:11 gate_skipped a68ed8e -> 23:23:18 watchdog 'Sim exited 2 after 7s' -> 23:23:41 gate_skipped a68ed8e (booted); no rollback/rollback_failed note; last_rollback.json is the 424c478 gate_failed rollback
- simorgh/execution/service.py:262-264 gated = getattr(config, 'landing_gate', True); WorktreeManager(..., gate=tests.gate if gated else None) -- landing gate covers only Sim's worktree commits
- simloader.py:558-562 run_gate docstring: skip is 'a run convenience, never offered to bless'; :981-984 a skip writes gate_skipped and tags nothing
- .simorgh_loader/unit_baseline-core.json: {"tests": 3348, "seconds": 45.67}

