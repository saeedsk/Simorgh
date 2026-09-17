# The threshold that was not the problem

2026-09-17. Asked: "what is the right threshold for voice matching score?"

## The answer: keep 0.5

813 recorded scores, read off the percept streams in the ledger:

| | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| named | 466 | 0.45 | 0.56 | 0.64 | 0.73 | 0.93 |
| unnamed | 348 | 0.05 | 0.24 | 0.32 | 0.39 | 0.50 |

The groups barely touch:

| band | named | unnamed |
|---|---|---|
| 0.00-0.30 | 0 | 152 |
| 0.30-0.40 | 0 | 118 |
| 0.40-0.45 | 0 | 63 |
| 0.45-0.50 | 54 | 15 |
| 0.50-0.60 | 113 | 0 |
| 0.60-1.00 | 299 | 0 |

Unnamed turns sit at a median of 0.32 -- not near-misses. The 15 unnamed
turns at or above 0.45 are already above `lean`; they failed the **margin**
test, meaning two people scored close together. Lowering the threshold
cannot recover them, it can only force a pick between two similar voices --
which is exactly where the twins get confused. 132 turns are already named
"probably X" by the lean rule at 0.45.

70% of turns carry no name. The causes, in order, are none of them the
threshold:

1. `MIN_SECONDS = 0.8` -- shorter turns return before any comparison. 39.6%
   of unattributed turns are under 20 characters, against 13.6% of
   attributed ones.
2. Aran has 0 enrolment takes and can never be matched at any threshold.
3. The TV, which is a voice the book does not know.

## Where the numbers were

Not on the turn record. `VoiceTurn` kept the name and whisper's confidence
and dropped the cosine; the score rode only on the percept, and only
displayed when a speaker was named -- so the failing cases were invisible
on screen and in the ledger both. I first reported there was no score data
at all, having searched the turn stream. There was: 813 of them, one stream
over. The score is now noted against its turn id and rides in the existing
metrics dict.

## Two faults found while looking

**Nothing went on the TV unless somebody asked.** `claimed_tv_act` catches
Sim claiming a TV act it never performed. Its correction handed the model
"write the marker on a line of its own now (... CAST_SHOW: home ...)" after
any loose sentence about the dashboard, and the model obliged. A guard
against lying became a cause of acting. The claim is still corrected; only
the instruction to *act* is now gated on someone having asked for a screen.

**An aside is a thing Sim said.** `_say_aside` spoke without recording that
it had -- its docstring claimed it was "gated by the echo tracker like
everything else" and it was the one utterance that never reached the
tracker. "One more second." came back through the microphone, passed
`is_echo` (three words, under its four-word floor), became the next turn,
took the floor, and the answer 28 seconds in the making failed the
request-id check on every chunk and was dropped as stale. Only the recents
ring catches an utterance that short, and nothing put an aside in the ring.

## The lesson, again

Four wrong guesses at a root cause this week, each settled by one command.
This time the question was answerable from data that already existed, and
the first answer given -- "there is no score data" -- was wrong because the
wrong stream was searched. Measure, then name the cause; and when the
measurement comes back empty, doubt the measurement before the system.
