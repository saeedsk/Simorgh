# Stage 7: a helper that forks, acceptance that gates "done", a container that dies with its step (2026-09-22)

Three items finished today. None was measured live; the evidence is the
tests named. Item 10, the long-task suite this stage's findings entry
is meant to report, has not been run -- see the end.

## Item 1: the typed Task, and `isolation: fork` (`0663d70`)

`task`/`delegate` take `{agent, brief, isolation, budget}`, with `budget`
a step count or `{steps: n}`. `isolation: fresh` (the default) starts the
helper from the brief alone; `fork` starts it from a copy of the parent's
conversation, then the job, so a verify helper can check the parent's own
work. Nothing the forked helper does reaches the parent's context.
Pinned in `tests/simorgh/orchestration/test_task_isolation.py`.

One part of the item turned out already built and the plan was wrong
about it: a child's own `session:<id>` stream. Every non-chat session,
children included, already persists its transcript there
(`_persist_transcript`). The plan note that said children ran only on
`task:<id>` is corrected.

## Item 4: a node is done only when its acceptance is met (`c91ee61`)

A plan node's "done when" criteria reached the checkpoint critic, which
decides whether to keep going, but not the final verdict that completes
the child. A child could finish without anyone asking whether its
criteria held. The verify subject now carries `acceptance`, and
`checklist.acceptance_items` puts each criterion first as a REQUIRED
checklist item: answered no, the verdict fails and the child revises.

Not done, on purpose: spawning a project's children through in-process
`Task` instead of Planning's queue. `Task` exists to stop a worker
waiting on its own child; a project session does not wait -- Planning
queues the children and the rollup is a pure function of their statuses.
Moving it would put the decomposition path, which took a week to make
produce a child at all, at risk for no measured gain. To revisit if a
trace shows a project blocked on a child.

## Item 8: a cancelled `run_container` leaves nothing running (`eea2e4b`)

`docker run` ran in a thread no cancel could reach, so a step that ended
by cancel, deadline or pause left its container running. It now runs
through `procs.run_child` in its own process group, and a cancel or a
timeout also sends `docker kill <name>`, because a container outlives its
client and killing the CLI is not enough. The envelope deadline needed no
new wire: Execution already shrinks a tool's timeout to it
(`within_deadline`) and `asyncio.wait_for` cancels the tool.

`tests/simorgh/execution/test_a_cancelled_container_is_gone.py` uses a
stand-in `docker` script; its cancel case fails on the old code, where the
client lived 30 s.

## Left on purpose or still open

- Item 5: `human: question_id` waits are not built.
- Item 6: `planning/reground.py` still re-grounds rather than revising a
  subtree.
- Item 10: the long-task suite (resolved rate at 50+ turns, the share
  ending in budget exhaustion, projects producing and completing
  children, the scripted three-day goal, resume after kill) has not been
  run. The one number that exists is the 2026-09-20 kill-and-resume drill
  (`2026-09-20-kill-and-resume.md`: nothing that had succeeded ran again).
  Note for whoever runs it: every `kill_resume_trial.py` run between the
  growth merge on 2026-09-20 and `efa116a` on 2026-09-22 ran with autonomy
  on (`2026-09-22-growth-merge-leftovers.md`).
