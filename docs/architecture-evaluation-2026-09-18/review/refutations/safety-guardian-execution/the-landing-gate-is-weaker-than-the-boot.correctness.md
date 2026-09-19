# refute:correctness:The landing gate is weaker than the boot

*Workflow: review · Phase: Refute · Agent id: `ac6085cbac00e04a9` · Tool calls: 11*

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
    "title": "The landing gate is weaker than the bootloader's gate and can be neutered by an edit to tests/, which Sim may write",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "`RunTestsTool._run_isolated` treats pytest exit 5 (nothing collected) as ok and never checks the summary line or a run-count baseline, while `simloader.unit_verdict` does all three; `tests/` is in `write_scopes_source` and excluded from ProtectedRule's path scan, so a branch that adds `tests/conftest.py` with `pytest_collection_modifyitems(...): items.clear()` passes `worktree_land` and reaches main.",
    "evidence": [
      "simorgh/execution/tools.py:~1372 `no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED or usage_error`; `ok = completed.returncode == 0 or no_tests`; used by `gate()` at tools.py:1272-1277 which `_land` calls",
      "simloader.py:655-696 `unit_verdict`: refuses exit 5, refuses 'N failed' on exit 0, refuses `ran <= 0`, refuses `ran < baseline*0.9` -- three attacks named in its docstring, none carried into the landing gate",
      "simorgh/execution/config.py:105 `write_scopes_source` includes `\"tests/\"`; rules.py:155-161 `_mentioned_paths` drops any token starting with `tests/`",
      "Offline pipeline: `approved apply_source_patch {'subject': 'tests/conftest.py', 'code': 'def pytest_collection_modifyitems(config, items):\\n    items.clear()\\n'}` and `approved run_shell printf ... > tests/conftest.py`; `ls tests/conftest.py` -> does not exist today, so it would be a new file"
    ],
    "why_it_matters": "'Only the test suite as gate' is exactly right as a description, and Sim can edit the gate. The loader would catch it at the next boot and roll back, but the commit is on main until then and every other task rebases onto it.",
    "recommendation": "Extract `unit_verdict` (and the baseline file) from simloader.py into `contracts/` and call it from `_run_isolated` when `target == \"tests\"`. In `_land`, refuse a branch whose diff touches `conftest.py`, `pytest.ini`, `pyproject.toml` or deletes test files unless a human approved that specific landing.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Locate pytest exit handling in RunTestsTool | 1068: no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED 1069: ok = completed.returncode == 0 or no_tests 1123: ok = completed.returncode == 0 1133:_ |
| 2 | Bash | Read simloader unit_verdict | _COUNT = re.compile(r"(\d+)\s+(passed\|failed\|errors?\|skipped\|xfailed\|xpassed\|deselected)\b") def unit_summary(text: str) -> dict[str, int]: """The counts pytest |
| 3 | Bash | Read write scopes config, ProtectedRule path scan, and check conftest |  # README.md, requirements.txt, simloader.py and sim.sh were readable # by nothing -- Sim could not read its own bootloader, and a chat # session burned its who |
| 4 | Bash | Read gate and _run_isolated in RunTestsTool |  # 40-line traceback landed on the prompt. A tool "isolated from # the live working tree" was not isolated from the live loop. return await asyncio.to_thread(se |
| 5 | Bash | Find write scopes, ProtectedRule location, and land/gate/conftest references |  # (docs/architecture.md: "retired but not yet deleted -- that's the # plan's Stage C"), so anything written there is work scheduled for # deletion. Found 2026- |
| 6 | Bash | Locate ProtectedRule, _land, and gate result consumers | simorgh/guardian/rules.py:155:def _mentioned_paths(text: str) -> list[str]: simorgh/guardian/rules.py:231: paths.extend(t for t in _mentioned_paths(text) if t n |
| 7 | Bash | Check for existing conftest and pytest config | ugrep: warning: tests/conftest.py: No such file or directory ugrep: warning: tests/simorgh/conftest.py: No such file or directory ugrep: warning: pytest.ini: No |
| 8 | Bash | Read _mentioned_paths and ProtectedRule | # costs a denial the model can explain around; under-matching costs the # whole protection model, which is the trade this makes. _PATHISH = re.compile(r"[\w./-] |
| 9 | Bash | Read worktree _land and gate usage |  return Opened(path, head.stdout.strip() if head.returncode == 0 else "", True, branch) # -- land -------------------------------------------------------------- |
| 10 | Bash | Check protected-path config and baseline usage in loader | simorgh/guardian/config.py:87: protected_subjects: tuple[str, ...] = DEFAULT_PROTECTED_SUBJECTS simorgh/guardian/config.py:151: if "protected_subjects" in kwarg |
| 11 | Bash | Check protected subjects, prior reviews, and write-scope enforcement | 21:DEFAULT_PROTECTED_SUBJECTS: tuple[str, ...] = ( 22- "docs/SOUL.md", 23- "src/orchestrator/soul.py", 24- "src/orchestrator/audit.py", 25- "src/orchestrator/ap |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim is true of the code today. (1) simorgh/execution/tools.py:1374-1376 `_run_isolated` computes `no_tests = returncode == 5 or usage_error; ok = returncode == 0 or no_tests`, and never parses the summary line or compares a run count. `gate()` (tools.py:1272-1277) just calls `_run_isolated("tests", ...)`. (2) simorgh/execution/worktree.py:216-219 `_land` calls `self.gate(path)` and branches solely on `gate.ok`; the `no_tests_collected` metadata that `_run_isolated` attaches (tools.py:1409) is never read by `_land`, and `_attribute` only runs when the gate is red. So an exit-5 (empty) or exit-0-with-everything-skipped gate fast-forwards main. (3) simloader.py:660-699 `unit_verdict` refuses exit 5, refuses "N failed" on exit 0, refuses `ran <= 0`, and refuses `ran < baseline*0.9`; its docstring names exactly the conftest.py / collect_ignore / pytest_collection_modifyitems attacks and says they were demonstrated live. None of this is imported by execution/ (grep for `unit_verdict|unit_summary` in simorgh/ returns nothing outside simloader.py). (4) simorgh/execution/config.py:120 `write_scopes_source` includes "tests/"; simorgh/guardian/rules.py:155-161 `_mentioned_paths` filters out every token starting with "tests/"; `DEFAULT_PROTECTED_SUBJECTS` (guardian/config.py:21-31) contains no tests/, conftest.py, pytest.ini or pyproject.toml entry. The only `conftest.py` special-casing in the tree is simorgh/contracts/checkout.py:286, which concerns SWE-bench checkouts, not this repo. (5) `ls tests/conftest.py` -> No such file; no pytest.ini/pyproject.toml/setup.cfg at root either, so the attack file would be new and would not collide. Not in the known-findings list: grep for conftest/exit 5/unit_verdict/landing gate across docs/architecture-review-2026-09-18.html, architecture-audit-2026.md and architecture-third-opinion-2026-09-18.md returns nothing. Classification "right-design-undermined" is correct: the gate design exists and the stronger verdict was already written for the bootloader, it was simply not carried into the second gate. Minor corrections: `write_scopes_source` is at config.py:120 (claim said ~105), and `unit_verdict` spans simloader.py:660-699 (claim said 655-696). One nuance worth carrying: since commit b2138c8 the loader gates only the "core" scope, but its `ran <= 0` and baseline checks would still catch a gutted suite at next boot, so the finding's "loader catches it later" backstop is accurate.

### evidence

- simorgh/execution/tools.py:1374-1376 -- `usage_error = completed.returncode == _PYTEST_USAGE_ERROR and not_python`; `no_tests = completed.returncode == _PYTEST_NO_TESTS_COLLECTED or usage_error`; `ok = completed.returncode == 0 or no_tests`
- simorgh/execution/tools.py:1272-1277 -- `gate()` returns `self._run_isolated("tests", ...)` with no additional verdict
- simorgh/execution/worktree.py:216-219 -- `gate = self.gate(path)`; `if not gate.ok:` is the only check before `git merge --ff-only` at line ~253
- simorgh/execution/tools.py:1409 -- `no_tests_collected` is emitted in metadata but `_land` never reads it
- simloader.py:660-699 -- `unit_verdict` refuses `code not in (0,5)`, `failed` from summary, `ran <= 0`, and `ran < baseline*0.9`; docstring lists the conftest.py/collect_ignore/pytest_collection_modifyitems/pytest_sessionfinish attacks demonstrated 2026-09-10
- grep -rn 'unit_verdict|unit_summary' simorgh/ -> no matches (the loader's verdict is not shared with execution)
- simorgh/execution/config.py:120-122 -- `write_scopes_source = ("simorgh/", "simorgh_skills/", "tests/", "tools/", "docs/", SCRATCH_PREFIX)`
- simorgh/guardian/rules.py:155-161 -- `_mentioned_paths` returns `[t for t in _PATHISH.findall(text) if not t.startswith("tests/")]`
- simorgh/guardian/config.py:21-31 -- DEFAULT_PROTECTED_SUBJECTS has no tests/, conftest.py, pytest.ini or pyproject.toml entry
- ls tests/conftest.py pytest.ini pyproject.toml setup.cfg -> none exist; a new tests/conftest.py would be collected by pytest from the copied tree
- grep -i 'conftest|exit 5|unit_verdict|landing gate' docs/architecture-review-2026-09-18.html docs/architecture-audit-2026.md docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)

**severity adjustment:** keep

**corrected claim:** As claimed, with two line-number corrections: `write_scopes_source` is at simorgh/execution/config.py:120 (not ~105) and `unit_verdict` is at simloader.py:660-699 (not 655-696). Additionally, `_land` (worktree.py:216-219) inspects only `gate.ok` and ignores the `no_tests_collected` metadata the gate already emits.

