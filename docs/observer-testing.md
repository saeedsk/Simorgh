# Observer testing

Simorgh's real bugs are found by giving Sim one real task through a
real model and watching it, not by unit tests -- see
`docs/EVOLUTION.md`'s whole history and `tools/trial.py`'s own
docstring. A "wave" is several observers doing this in parallel, each
on a distinct question, reporting back, then the findings get fixed.

Eleven waves were run by hand before `tools/observer_kit.py` existed.
Three real costs showed up every time and none of them needed a faster
model:

1. Every observer did its own `shutil.copytree` of the repo at the
   start of its own run.
2. Observers shared one scratchpad directory and collided in it twice
   in one afternoon.
3. Findings came back as prose, and four observers independently
   finding the same bug read as four essays, not one confirmed line.

A fourth cost was introduced by the fix for the first three, and caught
the same day. Findings and sandboxes originally shared one parent
directory. A 20-agent wave's sandboxes used 10 GB; deleting them to
reclaim disk was the obvious next step once the wave finished, and that
`rm -rf` took the whole findings file with it. Findings now live under
`~/.cache/simorgh-observer-findings`, a directory nothing else has a
reason to delete; sandboxes still live under a system temp directory,
which is exactly where wave-scale disposable data belongs.

`tools/observer_kit.py` closes the second and third for real, and helps
the first without being the dramatic win it might sound like -- see
**What actually got faster** below before assuming this makes a wave
run 10x quicker end to end.

## Running a wave

```
python tools/observer_wave.py --count 10 --label gaia
```

prints one sandbox path per observer and a `RUN_ID`. Give each observer:

- its own path, as the repo it works in (`cd` there, `git init`, go)
- the `RUN_ID`, to set as `SIMORGH_OBSERVER_RUN_ID` in its environment,
  or to pass explicitly to `record_finding(..., run_id=...)`

Each observer calls `observer_kit.record_finding(...)` for anything it
finds, alongside its usual prose report -- the structured record is
what makes aggregation possible, the prose is still what a human reads
for the reasoning behind it. See `tools/observer_kit.py`'s `Finding`
fields for what to fill in; `category` and `file`/`line` are what
`aggregate_findings.py` clusters on.

When the wave is done:

```
python tools/aggregate_findings.py <RUN_ID>
```

prints one line per DISTINCT issue, ranked blocker-first, each showing
how many observers independently confirmed it.

## What actually got faster

Measured on this machine, not assumed:

- **Sandbox copy time, per clone: modest, not dramatic.** `cp -Rc`
  (APFS copy-on-write) against this repo (266 MB, including `.git`'s
  ~4,300 small objects) took ~1.1s; `shutil.copytree` of the same tree
  took ~1.55s. About 30% faster per copy, not an order of magnitude --
  this repo's `.git` has enough small files that clonefile's per-file
  syscall overhead eats into the win a raw byte copy doesn't pay.
- **Real disk usage: this is the genuine win.** Ten clones of the full
  repo used **64 MB** of actual new disk space, not the ~2.4 GB ten
  independent full copies would cost -- the physical pages are shared
  copy-on-write until something writes to them, which most observer
  sandboxes never do to most of the tree. This is what lets many waves
  run back to back without filling the disk, not raw speed.
- **Collision avoidance and structured findings are the real
  multipliers**, and they are not about wall-clock at all. `RUN_ID`
  isolation makes "ten agents wrote into one scratchpad and clobbered
  each other" structurally impossible rather than a rule the brief
  hopes gets followed. `aggregate_findings.py` turns "read ten reports
  and notice which four describe the same bug" into one command --
  that is where a wave's real *triage* time multiplier lives, since a
  coordinator's reading time, not disk I/O, was the actual bottleneck
  between "the wave finished" and "the fixes started."

**What this does NOT speed up, and nothing here should be read as
claiming to:** an observer's wall-clock time is dominated by real model
calls -- a single trial commonly runs minutes because it is waiting on
`cognition.think`, not on disk. Sandbox setup was seconds against a
run that takes minutes to tens of minutes. If the goal is more findings
per hour, the lever is running more observers in parallel (bounded by
whatever API concurrency and cost are acceptable) with genuinely
non-overlapping scope -- not shrinking the seconds this toolkit
touches, and not shortening any observer's own timeouts, which would
make the exact slow-to-trigger bugs (a multi-attempt continuation, a
300-second retry delay, a full test suite run) untestable instead of
faster to test.

**One genuine, safe speedup for the full suite itself:** `pytest -n
auto` (pytest-xdist, in requirements.txt) runs the suite across every
CPU core instead of one. Measured on this machine: 3066 tests, 250s
serial vs 57s across 12 cores, same pass/fail result -- a real 4.4x,
not a marginal one, and unlike shortening a timeout it changes nothing
about what gets tested. Several observers in this project's own waves
stalled for minutes waiting on a serial `pytest tests -q`; use
`pytest tests -q -n auto` instead when running the full suite in a
sandbox, and keep the anti-stall protocol's background-and-poll
discipline for it regardless, since even 57s exceeds a foreground
call's comfort margin.

## Sandbox trials: what got faster, measured (2026-09-08)

A trial's time is model latency plus pytest. The model part is
irreducible; the pytest part was most of the rest, and it is gone:

| what | before | after |
|---|---|---|
| full unit suite | 250s serial | 66s (`-n auto`, 12 cores) |
| one `run_tests` call inside a trial, full suite | ~250s | 72s, rlimits and copy included |
| loader gate, unit half | 250-670s | ~72s |
| lab copy per trial (`make_lab`) | 2.7s, 109 MB of disk each | near-instant, copy-on-write |
| whole 7-trial suite, `--parallel 3` | 25m 37s serial | 4m 34s |

That last row is 5.6x, not 10x, and the gap is honest: with pytest
out of the way a trial is almost entirely waiting on the model, and
three trials at once finish in about the time of the slowest one.
`tools/trial_suite.py --parallel N` runs each trial in its own process
-- it has to, `run_one` does a process-global `os.chdir` and
Orchestration's tool registries are module-level state two kernels
would corrupt. Keep N small: every trial's `run_tests` now uses every
core, and several at once oversubscribe the machine. The loader gate
stays serial on purpose; a gate that refuses under contention is worse
than a slow one.

Two trials fail today for a reason that predates all of this and only
became visible because they now finish inside the cap instead of timing
out: `breaks-the-suite` and `already-done` both commit a change they
should not. Nothing gates a commit on the whole suite passing, and a
model that narrows `run_tests` to one file satisfies "run the tests"
literally (wave 5, self-modification observer, blocker 3). Open.

## Anti-stall protocol (unchanged, still required)

A previous round lost 7 of 11 observers to a 600-second watchdog by
running long trials in the foreground. Every observer must:

- run anything that may exceed ~5 minutes with `run_in_background:
  true`, then poll its output file
- keep every foreground call under 400 seconds
- stop and report after 2-3 failed attempts at the same thing, rather
  than retrying it

## Observe-only, still absolute

Nothing here changes the standing rule: an observer never edits,
commits, tags, or pushes anything in the real repository. Every
sandbox `tools/observer_wave.py` stages is a full, independent clone
specifically so real write tools can run for real without touching
anything that matters.
