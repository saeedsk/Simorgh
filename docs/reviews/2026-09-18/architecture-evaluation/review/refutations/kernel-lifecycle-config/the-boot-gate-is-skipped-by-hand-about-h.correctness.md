# refute:correctness:The boot gate is skipped by hand about h

*Workflow: review · Phase: Refute · Agent id: `a7a688c6d421bca14` · Tool calls: 8*

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
| 1 | Bash | Inspect loader decisions ledger and baseline | decisions.jsonl last_green.json last_rollback.json last_trials.txt last_unit.txt unit_baseline-core.json unit_baseline.json --- 99 .simorgh_loader/decisions.jso |
| 2 | Bash | Compute gate stats and read cited loader lines | gate opportunities 70 skipped 34 2026-09-14 05:14:51.070030 2026-09-18 17:46:21.387453 restart->gate n 24 median 45.04262399673462 p90 59.16111397743225 gate_fa |
| 3 | Bash | Read cited lines in loader, sim.sh, cli, worktree and env test | 8:watchdog timer, and load and run sim. If sim boots up and can pass all 40:Once the gate passes it hands off to Sim, with a start-up watchdog: if 41:Sim exits  |
| 4 | Bash | Read untracked-code logic, skip flow, watchdog context, conftest guard | def head(repo: Path) -> str: return git("rev-parse", "--short", "HEAD", cwd=repo, check=True).stdout.strip() def is_dirty(repo: Path) -> bool: """Tracked change |
| 5 | Bash | Find env guard conftest, gate runner, rollback refusal, commit authors | conftest.py --- == conftest.py 1:"""Test-session isolation from the ambient environment. 3:`kernel/config.py::_apply_env_overrides` lets `SIMORGH_<SECTION>_<KEY |
| 6 | Bash | Check loader principle text, landing gate, HOME use, conftest guard, status output | 16:never runs the code it is judging.** So: 647: judged; the summary line is what pytest says happened. Reading both 909:# (or a `restart`) of source the gate h |
| 7 | Bash | Read loader principle, run status, analyze restart chains | watchdog timer, and load and run sim. If sim boots up and can pass all unit tests successfully, we accept this run and tag it ... if the code is not reliable or |
| 8 | Bash | Check status untracked line, authors of restarted commits, restart exit code | 4:[simloader] HEAD: 38a9049 5:[simloader] untracked (ignored by the gate's dirty check): .Rhistory, .obsidian/app.json, .obsidian/appearance.json, .obsidian/cor |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The numbers and the code citations check out, but two of the five sub-claims are overstated and the recommendation asks for things the loader already has. Verified true: 34 of 70 gate decisions in .simorgh_loader/decisions.jsonl (2026-09-14 05:14 .. 2026-09-18 17:46) are gate_skipped; restart->next gate median 45 s, p90 59 s; simloader.py stream() at 383-386 calls Popen with no env= so the pytest child inherits the operator's environment including SIMORGH_EXECUTION_REPO_ROOT exported by sim.sh:22; the only env guard is the repo-root conftest.py:65-76 autouse session fixture, which is inside the tree being judged, and $HOME is not isolated while kernel/config.py:97 and :157 default data_dir to ~/.simorgh; kernel/cli.py:392-397 returns 2 for both ConfigError and KernelBootError and simloader.py:1042-1048 rolls back on any non-zero exit inside the watchdog; untracked_code() at simloader.py:489-500 matches any untracked *.py anywhere, so source_fingerprint() (916-921) returns "" and already_verified() can never match while simorgh/big.py exists (status output confirms). Overstated: (1) "duplicates the landing-time gate" -- worktree.py Landing.land (216-219) does run the whole suite before fast-forwarding, but every commit the boot gate actually re-gated or failed in the log (36b9813, dd54876, 5cadca0, 424c478, and the tag_withheld/gate_skipped chains 496444a..e99a02b, e3f8839..fa5e66e, 469b8c7) is authored "Saeed", not "Simorgh"; for the creator's own commits the boot gate is the only gate, and it caught 4 real regressions. (2) "cannot be reused ... (as now)" -- simorgh/big.py was created 2026-09-18 18:19, after the last recorded decision, so it explains none of the 34 skips. The real driver of repeated skips is that a skipped gate never calls record_green (simloader.py:981-984 vs 986-987), so a restart of the very same commit (469b8c7 -> 469b8c7, e3f8839 -> e3f8839) cannot reuse anything and must be gated or skipped again; skipping is self-perpetuating. (3) The recommendation's `--force-gate` already exists (simloader.py:1070, used at 975-977) and gate reuse for a clean unchanged HEAD already exists (already_verified, 7 gate_reused events), so the design is already gate-at-change when the tree is clean; the gaps are narrower than "move the default". The finding is not on the known list. Severity stays medium: right design, undermined on three concrete points (skip leaves no green record, any-untracked-.py veto, loader-side env not scrubbed) plus one genuine exit-code conflation.

### evidence

- .simorgh_loader/decisions.jsonl: 99 rows, Counter({'gate_skipped': 34, 'restart': 24, 'blessed': 20, 'gate_reused': 7, 'tag_withheld': 5, 'gate_failed': 4, 'rollback': 3, 'watchdog': 1, 'bless_refused': 1}); first ts 2026-09-14 05:14:51, last 2026-09-18 17:46:21; restart->next gate decision n=24 median 45.0 s p90 59.2 s
- Restart chains on the SAME commit still re-gate: 'restart 469b8c7 prev_gate gate_skipped 469b8c7 -> next gate_skipped 469b8c7'; 'restart e3f8839 prev_gate gate_skipped e3f8839 -> next gate_skipped e3f8839' -- because simloader.py:981-984 (gate_skipped branch) breaks without record_green(), which only runs on the ok branch at 986-987
- simloader.py:489-500: _UNTRACKED_CODE = re.compile(r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg)$|\.(py|pth)$") applied to every untracked path; simloader.py:916-921 source_fingerprint returns '' if untracked_code(repo); `python3 simloader.py status` prints 'untracked CODE -- the gate would run it, no tag can be earned while it is here: simorgh/big.py'
- stat simorgh/big.py: 'Sep 18 18:19:00 2026' -- created after the last decision (17:46), so it caused none of the 34 skips
- simloader.py:383-386: subprocess.Popen(argv, cwd=cwd, stdout=PIPE, stderr=STDOUT, stdin=DEVNULL, text=True, bufsize=0) -- no env=; sim.sh:22 export SIMORGH_EXECUTION_REPO_ROOT=...; conftest.py:65-76 @pytest.fixture(autouse=True, scope='session') _no_ambient_simorgh_env deletes SIMORGH_* and model keys -- lives in the judged checkout; kernel/config.py:97 and :157 default data_dir '~/.simorgh' via expanduser, HOME never overridden
- simloader.py:15-16 principle: 'the loader never runs the code it is judging' (context: stdlib-only, no import simorgh)
- simorgh/kernel/cli.py:392-397: except ConfigError -> return 2; except KernelBootError -> return 2. simloader.py:1042-1048: if returncode != 0 and ran_for < watchdog_s -> write 'watchdog' note and cmd_rollback(); log has 'watchdog a68ed8e Sim exited 2 after 7s, inside the 60s watchdog' with no rollback row after it (cmd_rollback refuses a dirty tree, simloader.py:880-882)
- simorgh/execution/worktree.py:216-219: if self.gate is not None: gate = self.gate(path); if not gate.ok: ... refuse landing -- Sim's commits are gated at landing
- git log authors: 761 Saeed, 94 Simorgh; all four gate_failed commits (36b9813, dd54876, 5cadca0, 424c478) and every commit in the restart->skip/withheld chains (496444a, 3930fc7, 51d8274, 0bf18f4, e99a02b, e3f8839, 98d5c62, cd7d022, fa5e66e, 469b8c7) are authored 'Saeed' -- the boot gate is the only gate those commits get
- simloader.py:1070 parser.add_argument('--force-gate', ...); :975-977 verified = '' if force_gate else already_verified(...) ; say('gate not needed: ... (--force-gate runs it anyway)') -- gate reuse and --force-gate already exist

**severity adjustment:** keep

**corrected claim:** The boot gate (core selection, ~46 s for 3348 tests) is a sound A/B-image design that its own bookkeeping undermines: the operator skipped it on 34 of 70 gate decisions in the last five days, and a skip records no green verdict, so a restart of the very same commit must be gated or skipped again (skipping is self-perpetuating; 17 of 24 restarts re-gated). Reuse of a green verdict already exists but is vetoed by any untracked .py anywhere in the tree (simorgh/big.py does this now, though it post-dates the logged skips). The gate is not redundant with landing: landing gates only Sim's worktree commits, while every gate_failed and every re-gated restart in the log was a creator commit. Two genuine defects remain: the pytest child inherits the operator's environment and $HOME with no loader-side scrub (the only guard is conftest.py inside the judged tree, and data_dir defaults to ~/.simorgh), and kernel/cli.py returns exit 2 for both ConfigError and KernelBootError so the 60 s watchdog treats a config mistake as a bad image and attempts rollback. --force-gate and clean-HEAD reuse already exist; the fixes are: record a provisional verdict or at least the skipped commit, narrow the untracked-code veto to paths the suite imports, scrub env/HOME loader-side, and split the exit codes.

