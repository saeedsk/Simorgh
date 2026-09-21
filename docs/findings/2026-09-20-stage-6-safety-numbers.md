# Stage 6's safety numbers, from the live decision log (2026-09-20)

Stage 6 item 8 asks for presence accuracy, unprompted utterances per person
per day, and the count of tier-3 actions that reached Execution without a
human. Two of those three can be answered from what is already recorded;
the third needs the creator.

Source: `~/.simorgh/telemetry.sqlite` (1,823 `guardian.decide` spans) and
`~/.simorgh/ledger/streams` (1,954 stream files), on the machine the
creator has been using this week.

## Tier 3 without a human: zero

| | count |
|---|---|
| Guardian decisions recorded | 1,823 |
| approved | 1,813 |
| denied | 10 |
| **tier-3 decisions** | **10** |
| **tier-3 approved** | **0** |

Every tier-3 decision in the log was a denial. Nothing that reaches
outside the house, changes who Sim trusts, or touches a siren has run
without a person, which is the number stage 0 was opened for -- the
before-figure was 0 escalations out of 26,737 physical-class actions.

The ten denials are all the same event, and it is one I broke and fixed
today: Sim proposing `people` on its own initiative was read as "a voice I
cannot place" and refused outright rather than escalated. Those will show
as escalations from now on (`guardian/tiers.py`, the `sim` role). The count
that matters -- tier 3 reaching Execution without a human -- stays zero
either way.

What Guardian actually spends its time on is cameras: `ring_live` (838),
`cam_snapshot` (687), `cam_stream` (54). Tier 0 and 1, all approved, which
is the system working as designed and also a reminder that the decision log
is mostly one household's cameras breathing.

## The tier is not on the span, and should be

`guardian.decide` records `{layer, mode, tool, verdict}`. It does not record
the tier, so the table above was computed by re-deriving each tool's tier
from `contracts/tiers.py` in the analysis. That is fine once and wrong as a
habit: the whole point of putting the tier on the decision is that a person
reading the log a month later sees what Guardian thought at the time, not
what today's table would say. Stage 6 item 5's own wording asks for "tier
and rule recorded on every decision and as span attrs", and the rule is
there while the tier is not.

**Next change, and it is small**: add `tier` and the deciding rule's name to
the `guardian.decide` span.

## Unprompted utterances per person per day: nothing to count yet

Zero unprompted proposals appear in the ledger. Initiative has been the only
path for them since this morning, the interest and check-in paths landed
today, and `initiative.offered` did not exist until today either -- so there
is no history to count, and the honest answer is "ask again after a week of
ordinary use". The machinery to count it now exists: `initiative.offered`
carries the kind and the person, and `initiative.suppressed` carries what was
held back and why, so the ratio the item wants is a one-line query over those
two streams rather than an inference from proposals.

## Presence accuracy: needs the creator

The item asks for presence belief against a family-corrected diary over two
weeks. That cannot be synthesised -- the whole value of it is that a person
says where they actually were. It stays open, and it is the one row here that
no amount of instrumentation will fill.
