# Supervising a live SWE-bench run (2026-09-22)

The creator started a 30-case `swebench-verified` run in his own session
and asked to have it watched. What watching it found was not what the
warnings said.

## The run could not have scored above zero

Sim booted at 13:56. The fix that makes a SWE-bench case work *inside*
`workspace/swebench/<case>` instead of a git worktree of this repo landed
at 14:00 (`c33c5c6f`). Every case in the run therefore opened a worktree
of the wrong repository, and every case ended the same way:

    14:13:04 task.step worktree_land  landed on main: nothing to land: the worktree made no commits
    14:04:01 task.step worktree_land  landed on main: nothing to land: the worktree made no commits

One case wrote `workspace/notes-13398.md` -- a notes file -- instead of
editing source, and a `run_shell` inside it failed with `fatal: not a git
repository`. Four cases "completed" in 20 minutes, none with a patch.

A running instance is the code it booted with. Nothing in the transcript
says so, which is how three hours of paid work went into a guaranteed
zero. The verdict line a case prints should say when no patch was
produced at all, rather than reporting a clean landing of nothing.

## The `draft` timeouts were Sim cutting off its own calls

Every couple of minutes:

    cognition.provider_failed provider='together_strong' purpose='draft'
      error="Together request failed: TimeoutError('The read operation timed out')"

The obvious reading is that Together is flaky. The evidence says
otherwise. Within one case, Together timed out twice **and** Gemini
answered `504 DEADLINE_EXCEEDED` -- three providers failing the same way
in a row is a deadline, not three outages.

Cognition SHARES a purpose's deadline between candidates
(`router._share_of`: `remaining / (still to try + 1)`) and never exceeds
what the caller will still wait. The worker waited 200 s, so each of four
candidates got **40 s**. Measured over 40 minutes of this run:

| provider / purpose | calls | mean | max |
|---|---|---|---|
| together_strong / draft | 59 | 2.8 s | **24.7 s** |
| together / draft | 10 | 9.6 s | **42.5 s** |
| together_strong / review | 60 | 0.7 s | 1.6 s |

A drafting call on a real case runs to 42.5 s against a 40 s slice. The
slow tail -- the calls doing the most work -- died on its own budget and
the case fell back to the floor model, which cannot write a patch.

`draft` now caps at 300 s and the worker waits 320 s, so a candidate gets
60 s (`eb3e00c7`). Chat and voice are untouched: they are bounded by
chat's own 90 s cap, the smaller of the two.

This is the third instance this week of one bug shape: **a deadline
shared N ways, sized as though it were not.** Memory's consolidation was
the same (30 s over four providers = 8 s each; Gemini's answer arrived
200 OK five seconds after it was abandoned). It is worth stating as a
rule: when a timeout is divided among candidates, size it from the
*measured* duration of the work times the number of candidates, not from
what feels like a long time to wait.

A Together failure now reports `after 41.9s of 40.0s`, so the next one
distinguishes deadline-clipping from a real stall without a bisect.

## There was no way to tell a running Sim anything

Earlier the same day the creator, away from the house, asked for Sim to
be restarted so it would pick up a fix, and it did not happen: there is
no channel that carries a command. `/api/chat` starts a conversational
turn; a Telegram message becomes a percept. Neither can reach `restart`.

`POST /api/command` (`61954531`) is that missing half: one line, through
`_handle_line` -- the keyboard's own path -- so Guardian gates every
effect behind it. Token-gated, refuses anything that parses to chat, and
echoes `[remote] <line>` on Sim's screen, because a command appearing
with no visible cause is how a household stops trusting the thing in the
corner. `tools/sim_say.py restart` is the one-liner.

It shipped with a hole, found by asking what a hostile line would do:
`!rm -rf ...` parses as a command and `dispatch.py` runs `!` as a raw
shell with **no Guardian in it**. At a keyboard that is a person's own
hands; over HTTP it is a remote shell on the house. Refused now
(`d0f7483e`), exactly as `ui.command.request` has always refused it.

## Smaller things worth knowing

- `run swebench-verified 30` is **not** a command -- it parses as chat,
  so the model has to decide to call the benchmark tool. The direct form
  is `benchmark run swebench-verified 30`.
- A stale `ledger.sqlite3` sits beside the live file-based streams in
  `~/.simorgh/ledger/`; querying it looks like a working query and
  answers from 2026-09-20. The streams under `streams/*.jsonl` are the
  live record.
