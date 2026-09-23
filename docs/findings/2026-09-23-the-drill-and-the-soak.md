# What a night of running Sim against itself found (2026-09-23)

The creator went out and asked for Sim to be run in simulation, in eight
instances, for eight hours, with bugs found and fixed as they appeared.

## The short version

Hundreds of household scenarios passed and found nothing. The
kill-and-resume drill found three real bugs on its first proper run.
Reading my own diffs from the day before found three more, two of them
security holes I had written and described as safe.

**A green scenario tells you it is still green.** Adversity -- a crash
mid-task, a signal during boot, a hostile reading of one's own code --
is what finds things.

## The three crash-resume bugs

Sim is one process with a jsonl ledger; the claim the architecture makes
is that a SIGKILL costs nothing but the work in flight. Three ways that
was untrue:

1. **A killed attempt's edits belonged to nobody.** `kept`/`created`
   come from a record written when an attempt ENDS, and a kill writes
   none. The resumed session did not know it owned the file, so
   `git_commit` refused: "this task did not write tools/x.py". Every
   crash-resume of a task that had written something was doomed this
   way. Now read from the steps' side effects, which are recorded as
   they happen.

2. **The same edits were then applied again.** The block that explains
   an inherited tree ("STILL IN THE TREE: do not re-apply them") was
   gated on a summary that also only exists when an attempt ends
   cleanly. So the one case where the model most needs telling was the
   only case it was never told. `redone_steps: [2]`, every run; now
   empty.

3. **A commit could be repeated.** With (1) fixed and (2) not, a later
   crash point produced `duplicate_commit_subjects: 1` -- an
   irreversible action done twice, which is the exact thing the drill
   exists to catch. Fixing (2) closed it.

The drill reported `"final": "unfinished"` throughout, which is true and
says nothing. All three were found by reading its step log.

## The tools were lying by omission

Six fixes to the harness before it could be trusted:

- the soak died three times, silently, each time a later foreground
  command's process group was cleaned up (`nohup` survives a hangup, not
  that). It is a real daemon now, and the watch alerts on silence --
  which is how the third death was caught in minutes rather than hours;
- a finding kept the last 4,000 characters of output, which for a house
  run is the tail of a list of PASSES with the failure cut off;
- sandboxes were cloned once, so an eight-hour run tested the code of
  the hour it began and none of the fixes it prompted;
- every instance ran the DEFAULTS, and the creator runs barge-in off,
  VAD high, a speaker threshold of 0.2;
- the drill printed nothing until its final JSON, so half an hour of
  work was indistinguishable from wedged;
- and `--kill-after 2` counted `worktree_open`, so the kill landed after
  ONE piece of real work.

## The tools were also the outage

Two abandoned labs and eight sandboxes cloned `workspace/` -- 9.7 GB of
voice models, venvs and camera stills. Copy-on-write costs nothing until
something writes, and then it costs gigabytes a copy. Free space went
from 31 GB to 12 GB before I noticed; the cleanup was the last line of
the drill, so a crash skipped it.

Labs and sandboxes now take the code and share the models by symlink
(362 MB instead of 10 GB), cleanup is a `finally`, and each run clears
the last run's data -- which is better science anyway.

## Reading my own diffs found what tests did not

- **A privilege escalation I wrote.** The Guardian exemption that lets
  Sim edit somebody else's program keyed on a `.simorgh-checkout.json`
  manifest in any ancestor. Sim can write files; `simorgh/memory` is not
  a protected path; a manifest is JSON with no denylisted pattern in it.
  Writing one there would have exempted Sim's own memory package from
  the rule that stops it giving itself a subprocess. A checkout must now
  be under `workspace/` as well.
- **A remote shell, one hop on.** Refusing `!` over `POST /api/command`
  was cosmetic while `tool run_shell {...}` was allowed, and Guardian's
  auto-approve is this house's default. The token was shell access on a
  0.0.0.0 bind.
- **A hush that could not be undone by voice.** "Sim, restart" and
  "voice off" were heard as chatter while hushed, leaving the keyboard
  as the only way back for a household that may not be near one.

Each of these was written the day before, with a docstring explaining
why it was safe.

## Four wires that had never carried anything

`tools/scan_half_wired.py`, which checks both ends of every declared
relation mechanically:

- `research.finding.recorded` -- a topic, a schema, a consumer that turns
  a finding into a patch scoped to one file, and no publisher. Every
  research task Sim has ever run ended as prose nobody acted on;
- `task.wake` -- the only manual way a waiting task returns, subscribed
  since waiting tasks existed, published by nothing: a task parked on an
  event that never came had no way back;
- `learn.self_patch.reverted` -- the loader rolls back and the Self Model
  records it privately; the two subsystems built to learn from a
  reverted patch never heard;
- `reflect.review.request` -- Reflection answers what patterns it sees,
  and nothing could ask.

One it flagged was a false alarm (a topic chosen by a conditional), and
the scanner now reads that shape too: a scanner nobody trusts is not a
scanner.
