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

## One thing that does not add up

`git_commit_steps_ok: 1` with `commits: 0`. A `git_commit` step
returned ok and the lab's history grew by nothing. That may be
honest — the commit could have landed in a worktree the landing gate
rejected, which is a real and correct outcome — or it may be a tool
reporting success for an effect that did not happen, which is the
honesty rule this project wrote down after 2026-09-08. **Not
diagnosed.** It needs the lab kept (`--keep`) and the worktree
looked at, and guessing between those two is exactly what the
"measure before naming a cause" rule is for.

## What this changes

- Stage 0 item 30's kill-and-resume acceptance ("the resumed task
  must not redo a step or repeat an irreversible action") is **met**,
  with evidence, for the first time.
- The item is not closed: the trial-suite (3 repeats) and GAIA slice
  it also asks for have not been run.
- Two things worth their own work, neither started: the verifier
  asking for a whole-suite run on a docstring change, and the
  committed-but-no-commit discrepancy above.
