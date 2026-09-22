# Context assembly is not where a turn's time goes; retries are judged on the whole task (2026-09-22)

Two stage 4 items, both recorded in `523cfaf` and in the stage 4 plan file.

## Item 4: the ContextBuilder move, measured and deferred

The case for moving prompt assembly out of Cognition into one
ContextBuilder in Orchestration, with readers injected in-process, was
the "0.25 s bus RPCs" per think that the plan's wording assumed. Measured
from the live telemetry (`~/.simorgh/telemetry.sqlite`, each request span
to its `.reply`) over two days, 1,548 thinks:

| round trip per think | mean | max |
|---|---|---|
| `persona.voice` | 0.73 ms | 27 ms |
| `self.summary` | 2.3 ms | 17 ms |
| `world.env.query` | 1.6 ms | -- |
| together | about 5 ms | |
| the provider call itself | 4,460 ms | |

The bus round trips are about a tenth of a percent of a turn. The move
would touch five modules and buy nothing a span can see, so it is
deferred. The half of item 4 that did matter -- a stable, cacheable
system prefix -- landed on 2026-09-19 (`2026-09-19-stage-4-live-fixes-and-stage-5-recall.md`).
What is left is structural (one builder, a person digest in the prefix)
and is tied to stage 6 item 4, which is what would give the prefix a
person digest to carry.

Seen on the way and not explained: `world.env.query` runs about 37,000
times a day. 1,548 thinks over two days is under 800 thinks a day, so
per-think assembly is not what issues most of those queries. Who polls it
has not been found. (`fde9e0e` removed one per-think `world.env.query`,
the household-wide `user_profile` request; that is a small share of the
37,000 by the same arithmetic.)

## Item 8: a retry is judged on the whole task

Verification's `did_anything` asks whether a task that says it changed
something wrote anything. A retry's verify subject carries only its own
attempt's steps, so on every retry the check stood itself down
(`complete_log=False`). A retry that wrote nothing in any attempt and
said it had was never caught mechanically.

`trajectory.writes_in_task` now reads every attempt's write tools from
the task's own stream `task:<id>`, not counting a step Guardian denied
(recorded as "denied: ..."). A retry passes when an earlier attempt wrote
and fails when none did. That completes item 8's trajectory check; the
Stop hook's rules stay until their counters justify retiring them (the
2026-09-20 table in the stage 4 file: `commit` reads zero because almost
no code tasks ran, which is not evidence it is unneeded).

## Status after

Stage 4: items 1-3, 5-11 done; item 4 in part (stable prefix done, the
builder move deferred on the measurement above).
