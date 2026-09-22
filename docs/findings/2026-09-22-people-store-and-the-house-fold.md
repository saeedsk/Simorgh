# The People store decides, preferences belong to a person, and the house fold that never ran (2026-09-21/22)

Stage 6 items 1 and 3-5. What changed, what was found, and one
correction to the plan's own record.

## The house fold never worked live (item 3) -- correction

The stage 6 plan recorded on 2026-09-20 that "`action.result` of home
tools is folded". The code was written that day and its tests passed, but
it read `payload["metadata"]`, and `action.result` has no such field:
Execution writes a tool's metadata to a Ledger blob and sends
`metadata_ref`. So live, every `home_call` result Sim made folded
nothing into `world:home`. The tests passed because they built a payload
Execution cannot produce.

Fixed in `b6348d9`: `_result_metadata` reads the blob (only for a tool
that is folded; an unreadable blob is treated as no evidence), and the
per-tool rules moved into a pure `home.folded_observations`, which also
folds `media_control` (play/resume/pause/off) and `media_play` onto the
players the house reports as changed. The new tests push every payload
through the message schema and Execution's own `metadata_for_blob`, so a
payload the producer cannot send can no longer make them pass.

So the fold went live on 2026-09-22, not 2026-09-20. Still not folded:
reads (`home_state`, `media_now`, `cal_list`) need Execution to keep rows
in the blob; `home_undo` reports only counts; `percept.home.state_changed`
needs a Home Assistant bridge; the per-area room transcript ring stays
sequenced after stage 4 item 4 (`1b668f2`).

Also item 3, 2026-09-21 (`85008db`): staleness is learned per entity. An
entity is stale once it is older than three times the median gap between
its own state CHANGES (not observations), floored at 5 minutes, capped at
24 hours, and the flat two hours until three changes are seen. On
synthetic rhythms a door flipping every two minutes is trusted for six
minutes and a thermostat moving twice a day for a full day. Nothing live
was measured.

## A role set in the People store is the role Guardian uses (items 4-5)

`people set_role` is a tier-3 action a person confirms, and until
`49e4345` it changed nothing: `PersonRule` read roles only from
`contracts/household.py`. Guardian now asks World Model's People store
first (`DecisionContext.role`, a 0.5 s wait, the same shape as presence)
and falls back to the household file only for somebody the store has no
record of.

Telegram and WhatsApp now admit a handle the store links to a person,
beside the config allow-list, so linking someone is enough to let them
write. Only a link admits: a username that spells a family name does not.

## Preferences belong to the person who said them (item 4)

"call me X" and "I prefer X" were kept in one user model for the whole
household and published with no speaker, so a nickname Ira asked for
became what Sim called everybody, and every chat prompt carried one
household-wide "What you know about the user" block -- Ira's preference
shown on Saeed's turn. Four commits:

- `dfbd9ac` persona: the user model is per person. `attribute(percept)`
  names whose sentence it is -- a named speaker Voice is sure of; the
  owner for the console; nobody for an unplaced or doubtful voice -- and a
  sentence nobody can be named for is not extracted at all.
- `9d5faca` worldmodel: `persona.user_model.updated` is filed in that
  person's `preferences` in `people.json`. Only `preferred_name` and
  `preference` are written; a sentence never writes a permission or a role.
  `world.env.query{what: user_profile}` answers one person, and nobody when
  not told who. No migration: the old facet lived in memory only and named
  nobody, so filing it under the owner would have been a guess.
- `fde9e0e` cognition: the household-wide block is gone. A
  `cognition.think` does not say who is speaking, so the assembler cannot
  pick the right person.
- `bb40929` orchestration: the speaker's own preferences reach their chat
  prompt, framed as the person's words and not as instructions. Before
  this follow-up, the previous three together meant nothing showed
  preferences at all.

## Item 1, closed 2026-09-21

Recorded in the plan with its numbers; summarised here so the findings
carry them. Exponential forgetting (`5b097a1`, half-life 30 days): ten
failures, ninety days, then three successes reads mean 0.64 with
forgetting and 0.27 without. Expected calibration error (`9a30003`) from
bins that had been recorded and read by nothing. Per-provider quality
(`134c8ef`). Snapshots (`51c669b`): the declared `snapshot_every = 200`
was never honoured because the service called `rebuild`, which reads a
snapshot and never writes one. Two of these reached the live session as
schema errors the module tier did not see (`ee88c66`: `samples` became a
float, `ece` was not allowed on the wire); that join is now a test.

## Item 8: no new numbers

The 2026-09-20 figures stand (`2026-09-20-stage-6-safety-numbers.md`: 0
tier-3 actions reached Execution without a human, of 1,823 decisions).
Unprompted utterances per person per day still need a week of ordinary
use over `initiative.offered`/`suppressed`, and presence accuracy still
needs the creator's diary. Neither was taken today.

## Still open in stage 6

Item 3 as above. Item 4: `contracts/household.py` and the config
allow-lists remain as fallbacks beside the store. Item 5: the
per-person permission matrix (Guardian decides by role, not by a matrix
per person). Item 8's two remaining numbers.
