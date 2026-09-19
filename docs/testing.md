# Testing: tiers, markers, and the trade-off

**The problem this solves.** On 2026-09-18 the full suite was 6,652 tests in 16 min 40 s on 12 cores. 1,637 s of that was 23 subprocess tests of the retired v1 CLI (`tests/test_e2e_cli.py`, 45 to 92 s each); the other 881 v1 tests were pure overhead; and the remaining 5,500 in-process tests mostly assert code shape with mocks, which is why the project's own retrospective found they missed every real blocker. Running all of that several times a day stalled development. It is also the wrong unit: an agent changing `memory` needs to know that `memory` still keeps its promises, not that `voice` still compiles.

**The model now.** Tests are organised in tiers by cost, and each module's `CONTRACT.md` names the few files that pin its interface. An agent runs the tier that matches what it touched. The full suite is the bless gate and a nightly job, not a per-commit habit.

## 1. Tiers

| Tier | What runs | When | Cost (12 cores) |
|---|---|---|---|
| **contract** | The 3 to 8 files a module's `CONTRACT.md` lists under "Contract tests", plus the two shared pins (`test_module_boundaries.py`, `test_every_subsystem_reads_its_config.py`) | While iterating; before every commit as the minimum | seconds |
| **module** | `tests/simorgh/<module>/` for each touched module, plus the shared pins; for a substrate module (bus, ledger, kernel, contracts) also the four boot-gate integration files | Before every commit | 5 to 60 s |
| **core** | `simloader.gate_selection()`: what every boot gates on (contracts, bus, ledger, kernel, guardian, cognition, memory, orchestration, planning, verification, execution minus domains, key interface files, five integration flows, the loader's own tests) | When you touched a substrate module; before pushing a stage item that spans modules | ~45 s, 3,348 tests |
| **full** | `tests/` minus `live` | Before `python simloader.py bless`; nightly; after a `contracts` change | minutes (target under 5 once v1 is gone) |
| **live** | Tests marked `live`: real network, Docker, a browser, this machine's engines | By hand, when working on that integration | varies |

Run them with `tools/modtest.py`:

```
python tools/modtest.py memory                  # module tier for one module
python tools/modtest.py --changed               # modules derived from git diff + working tree
python tools/modtest.py --tier contract memory  # just the interface pins
python tools/modtest.py --tier core             # the boot gate
python tools/modtest.py --tier full             # everything but live
python tools/modtest.py --list --changed        # what would run
python tools/modtest.py memory -- -k recall -x  # extra args to pytest after --
```

`modtest` maps changed paths to modules (`simorgh/<m>/` and `tests/simorgh/<m>/` map to `m`; `tests/simorgh/test_*.py` is `shared`; `simloader.py` and `tools/` are their own), adds the shared pins, adds the substrate pins when a substrate module changed, and uses `pytest-xdist` when the selection is large.

## 2. Markers

Declared in `pyproject.toml`.

| Marker | Meaning | Effect |
|---|---|---|
| `live` | needs a real external thing (network service, Docker, browser, an engine on this machine) | excluded everywhere unless `--live` |
| `slow` | more than about two seconds alone: real sleeps, subprocesses, large fixtures | excluded from the module tier by default; runs in core and full |
| `integration` | boots a Kernel or drives several real subsystems together through the bus | runs in core and full; a module's `CONTRACT.md` may name one as a contract test |
| `contract` | pins a module's interface (topics, schemas, streams, config keys, invariants, bus policy) | the contract tier; changing what such a test asserts is a contract change (see `docs/AGENTS.md` section 3) |

A test with a real `asyncio.sleep(> 0.05)`, a `subprocess.run`, or a fixture over a megabyte gets `slow`. A test that boots a `Kernel` gets `integration`. A test that asserts a topic name, a schema field, a stream name, a config default or a bus policy entry gets `contract`.

## 3. What makes a test worth keeping

The 2026-09-18 evaluation (section 4.8) found three kinds of test in this tree. Keep the first two; delete or merge the third.

1. **Behaviour tests.** Real subsystem objects on an in-memory bus and ledger, a fake provider, a fake clock; assert what the system *does*. `tests/simorgh/integration/test_cli_end_to_end.py` is the model: it boots every subsystem and drives `_handle_line`. These found the real bugs. Add a case here when you find a seam bug.
2. **Contract tests.** Small, fast, and specific: this topic exists and has both sides; this schema has these fields; this stream is named here; this config key has this default and is read; only Guardian publishes `action.approved`. These are what let an agent change a module alone.
3. **Shape tests.** A mock is called with these arguments; a method exists; a constant equals itself; a docstring says a thing. These pass when the code is wrong and fail when it is refactored. They are the majority by count and the reason the suite was slow to run and slow to change.

The rule for new tests: if it would still pass with the feature broken, it is a shape test; do not write it. If it needs a mock of the thing under test, it is a shape test. If it takes a second and you could make it take a millisecond with a fake clock, do that.

## 4. The trade-off, stated

Speed and confidence are traded through the tiers, not by skipping tests:

- The **module tier** gives an agent confidence that its module still keeps its promises, in under a minute. It cannot catch a seam bug in another module. That is acceptable because the seam is pinned by the *other* module's contract tests, which that module's owner runs.
- The **core tier** catches a broken boot and a broken action path. It runs at every boot anyway (the loader), so paying it before pushing a substrate change adds nothing new.
- The **full tier** catches everything the suite can catch. It runs before a bless and nightly. If a bug slips past the module tier and is caught by the full tier, the fix is a new contract test in the module that owned the bug, so the module tier catches it next time.
- **Trials** (`tools/trial.py`, `tools/trial_suite.py`) catch what no unit test can: the system doing the wrong thing with a real model on a real task. They are the real quality gate for behaviour changes and belong in `docs/findings/` with numbers.

## 5. Cleanup done on 2026-09-19

- Deleted `tests/test_*.py` (41 files, 881 tests, 11.5k lines) with the v1 tree they tested. The suite dropped from 6,652 to 5,762 tests and from 16:40 to 1:34.
- Still open (stage 0 item 29): `tests/simorgh/execution/media/test_cast.py` hits an unpatched 30 s constant (`cast.py:674`); `tests/simorgh/voice/test_session.py::TestTenTurns`, `tests/simorgh/integration/test_local_multi_worker_crash_resume.py` and `tests/simorgh/execution/test_service.py::TestSkillAcquiredRegistersOnDemand::test_a_second_acquisition_of_the_same_name_does_not_re_register` (a 0.05 s real timeout) are timing-flaky under xdist (each failed once in a full run and passed alone) and need the `slow` marker and a fake clock.
- `pyproject.toml` now declares the markers and `testpaths`; `pytest-timeout` is recommended (`pip install pytest-timeout`, then `--timeout=120` in the full tier) so a hang is a failure, not a stall.

The per-directory value analysis (what each directory covers, which files are the contract tier, which are shape tests to merge or delete, what is not covered at all) has not been written yet; producing it and executing it is stage 0 item 29 in `docs/plan/stage-0-safety-gaps-wires-gate.md`, one module at a time under that module's lock.
