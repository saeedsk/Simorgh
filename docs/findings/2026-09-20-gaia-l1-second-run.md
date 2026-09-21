# gaia-l1, twice in one evening

2026-09-20. Two runs of the same five cases, same model label.

| | first run | second run |
|---|---|---|
| score | 1/5 (20%) | **2/5 (40%)** |
| wall clock | 313 s | 943 s |
| cost | $0.47 | $1.12 |

## What changed between them

`blocked` stopped being a terminal outcome (`benchmark/runner.py`).
In the first run, two cases were scored wrong the moment they
blocked and then completed afterwards, one of them correctly. In the
second, case 2 (Mercedes Sosa) answered 3 and scored correct.

Whether the fix or the model produced that is not established: case 2
completed on its first attempt this time and never blocked, so the
re-scoring path was not exercised by it.

## Case 1: a unit, not a capability

"…how many **thousand** hours would it take…". Both runs computed
~17,061 hours correctly and both answered `17000`. The answer is 17.

**Deliberately not fixed.** The obvious move is a line in
`ANSWER_FORMAT` about answering in the scale the question names.
That file already carries the argument against it: the instruction is
GAIA's own, "a system that answers correctly in the wrong shape
scores zero on the real leaderboard too, so we must not be kinder
here". A number that is only good because we coached past a mistake
GAIA counts is not comparable to anyone else's, and 40% earned that
way tells us less than 20% earned honestly.

Written down so that the next person to see this twice does not
quietly add the line.

## Case 5: ten minutes, six attempts, one answer

Six attempts, every one concluding `FINAL ANSWER: 2`, every one
refused with "verification failed after max revisions", until the
600 s case timeout. Roughly half the run's wall clock and half its
cost.

Planning's no-progress guard existed and compared whole summaries;
each attempt wrote a different paragraph above the same answer, so
six identical answers looked like six different ones. It compares
the answer now (`contracts/text/answer.py`).

The cost was not only time: one attempt found an Adélie penguin and
answered 3, and the loop talked it back down to 2.

## What the run did to the repo, which it should not have

A research case committed the creator's uncommitted working-tree
edits to `main`, as him, under a message describing code that was
not in the diff. Fixed (`commit_of_unwritten_refusal`) and written
up in the commit; noted here because a benchmark run that modifies
the repository is not a benchmark run.

Eleven skill-writing tasks were also queued behind it, one named
after a YouTube id. Fixed: distillation now refuses a task whose
origin is `benchmark`.

## Still open

- The provider label. Four failovers appear in this run's log and the
  card showed no warning, but the provider-attribution change landed
  around the same time as the boot, so it may simply not have been in
  the running image. Needs one more run to say.
- Media audio answered as a person: YouTube narration was transcribed,
  matched to the creator at 0.37 against a 0.30 threshold, and
  answered as conversation.
