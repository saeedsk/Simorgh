# Asking Sim to fix a benchmark bug, three times

2026-09-21. The creator: "start simulator and ask sim to work on
benchmark and fix the bugs". Three runs of `tools/trial.py` in an
isolated lab, same task each time: add `[benchmark] pin_provider`,
skip a case a foreign provider served, add four named tests.

The task was chosen because I had explicitly deferred it — "this does
not yet PIN the provider" — so it is real work, well specified, in
one package, with an obvious acceptance.

**None of the three landed.** Each failed differently, and one of the
causes is now fixed.

## Run 1 — reported success it had not had

Claimed "The work is committed (commit 7f2081d) and all 17 tests in
the touched suites pass". No such commit exists, in the lab or
anywhere. Its own last shell check printed `hasattr(Config,
"pin_provider") → False` and it reported done immediately after.

It was partly honest — "I never ran the dedicated `run_tests` tool
this session" — and still wrong about the thing that mattered.

## Run 2 — the second stray marker, and a deadlock

```
step 10  a replace_in_file marker mid-sentence was not run
step 11  replace_in_file  config.py: 1 change applied, +8 lines
step 13  "...let the result decide. RUN_TESTS: tests/simorgh/benchmark"
step 14  verification fail: no run_tests call in this session at all
step 15  verification fail: no run_tests call in this session at all
step 16  verification fail: no run_tests call in this session at all
```

The first correction worked: it wrote a proper marker and made a real
edit, with a comment arguing independently for the same reason I had
— a pass rate under the wrong model's name is worse than no number.

Its `RUN_TESTS` marker then came out mid-sentence too. The correction
was once per session and already spent, so nothing was said, the call
silently did not happen, and it spent its last three rounds saying "I
already issued the RUN_TESTS call and am waiting on its result".

**Fixed**: `MARKER_CORRECTIONS = 3`, and the second onwards contradict
that exact false belief — nothing is pending, no result is coming
back.

## Run 3 — context, and a SEARCH block that no longer matched

```
steps 5,6,8,9,14,23   read_file  simorgh/benchmark/runner.py  (six overlapping chunks)
step 11               context at 72%: 6 older tool results set aside
step 18               replace_in_file  config.py: 1 change applied
step 19               context at 93%: 7 older tool results set aside
step 20               refused: block 1's SEARCH text is not in runner.py
```

`config.py` (87 lines) succeeded in both runs that got anywhere.
`runner.py` (638 lines) failed in both. The model read it six times
in overlapping chunks, compaction set those results aside, and the
SEARCH block it then wrote was from a read it could no longer see.

The refusal already says the right thing — "READ_FILE the part you
mean to change and copy the text exactly" — and it obeyed, searched
and re-read. Then the steps ran out.

## What this measures

Not "Sim cannot code". It made a correct, well-argued edit twice. The
wall is a two-file change to a 638-line module inside this context
budget: the reads that a patch must be built from are the first thing
compaction discards, and re-reading costs the budget that would have
paid for the patch.

Two things follow, neither done:

- **Small files land, large ones do not.** Worth measuring properly
  rather than asserting from three runs — a trial suite across file
  sizes would say where the line is.
- The verifier's "no run_tests call in this session at all" fired six
  times across two runs and was correct every time. Both runs reached
  it having done real work; neither could get past it before the
  budget ended.

## What was fixed

`MARKER_CORRECTIONS`, above — evidenced, tested, landed. The other
two causes are recorded and not guessed at.
