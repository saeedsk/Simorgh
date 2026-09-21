# Killing Sim mid-task, and what came back

2026-09-20. Stage 0 item 30's kill-and-resume drill, run with a real
model for the first time. `tools/kill_resume_trial.py --kill-after 2
--max-usd 0.40 --timeout 600`, Together as the provider.

## The result

```json
{
  "kill_after": 2,          "steps_before_kill": 2,
  "a_finished_on_its_own": false,
  "redone_steps": [],       "duplicate_commit_subjects": 0,
  "steps_total": 23,        "final": "unfinished",
  "commits": 0,             "git_commit_steps_ok": 1,
  "ok": false
}
```

**The half the item is about passed.** The child was SIGKILLed after
two completed steps, a second process booted on the same data
directory, the dead lease expired, Planning re-offered the task and
`resume.py` picked it up. Nothing that had already succeeded ran
again (`redone_steps` empty) and no commit was made twice.

**The half nobody asked about failed.** The resumed task never
finished: 23 steps, then `unfinished`. The task streams show it
cycling — `status_changed: blocked, "verification failed after max
revisions"`, then `retrying after being blocked`, repeatedly, across
three task records.

`ok: false` is the tool being strict: its verdict requires the task
to complete as well as not repeat itself. That is the right bar and
this run does not clear it.

## Why it did not finish

The verifier rejected the work, twice for reasons about the test run
rather than the change:

- *"run_tests was called on a narrower target than the whole suite --
  this change was never checked against anything it might have broken
  elsewhere"*
- *"the whole suite was run and it FAILED -- the change is not checked
  until the suite passes"*

So on a task whose whole content is a docstring, the verifier demands
a full-suite run inside a lab, and the lab's full suite did not pass.
Every revision then spends minutes running ~6,800 tests to be told
the same thing, until the revision budget is gone.

This is the same **shape** as the creator's GAIA run earlier the same
evening, where two of five cases ended `blocked -- verification
failed after max revisions` and then completed correctly on retry.
Whether it is the same cause is not established: GAIA questions have
no test suite to run, so at most the "max revisions" loop is shared,
not the reason for entering it.

## The thing that did not add up, and what it was

`git_commit_steps_ok: 1` with `commits: 0`. A `git_commit` step
returned ok and the lab's history grew by nothing.

**Resolved by reading, not guessing.** `GitCommitTool` returns `ok`
only after `git commit` exits zero, and carries the new HEAD in its
metadata — it cannot report a commit it did not make. A code task
works in a git worktree (`execution/worktree.py`), commits there, and
only `worktree_land` moves the lab's own HEAD. This task never
landed, because verification kept refusing it. So the commit exists,
in the worktree, and the lab root correctly shows none. No honesty
violation.

**The drill was wrong, though, and in the direction that matters.**
It counted `rev-list HEAD` in the lab root alone. The whole point of
the drill is to catch an irreversible action REPEATED after a resume,
and a commit repeated inside a worktree — which is where a code task
makes every commit it makes — was not being counted at all. Fixed
the same evening: `_trees()` walks the lab and every worktree, and
duplicate subjects are looked for across all of them. The report
gained `worktrees` and `commits_in_worktrees` so the two places are
never conflated again.

One trap in that fix, with its own test: `git worktree list` prints
the main checkout too, and on macOS under its resolved path — the
lab is `/var/...`, the listing says `/private/var/...`. Comparing the
strings counts one directory twice, and every commit in it twice.

## What this changes

- Stage 0 item 30's kill-and-resume acceptance ("the resumed task
  must not redo a step or repeat an irreversible action") is **met**,
  with evidence, for the first time.
- The item is not closed: the trial-suite (3 repeats) and GAIA slice
  it also asks for have not been run.
- One thing worth its own work, not started: the verifier asking for
  a whole-suite run on a docstring change, then failing the change
  because the lab's suite does not pass.
