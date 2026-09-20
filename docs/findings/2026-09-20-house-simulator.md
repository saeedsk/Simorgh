# The household simulator: what the room does (2026-09-20)

Stage 11 items 1-3. Measured on the real path -- Kokoro speaks, the
sherpa CAM++ model embeds, whisper large-v3-turbo transcribes -- with
the five personas of `simorgh/evals/house/people.py`.

## Choosing the voices was a measurement, not an opinion

The first household was picked by ear. `af_heart` (the owner) and
`af_bella` (a child) scored **0.77** against each other: two personas
the embedder cannot tell apart, which would have read as Sim
misidentifying people in every scenario built on them.

All 28 Kokoro voices were then synthesised on one sentence and
embedded. The five whose worst pair is furthest apart:

| | af_river | bm_lewis | bf_isabella | am_puck | af_nicole |
|---|---|---|---|---|---|
| **af_river** | — | 0.12 | 0.17 | 0.17 | 0.23 |
| **bm_lewis** | | — | 0.14 | 0.00 | 0.02 |
| **bf_isabella** | | | — | 0.11 | 0.24 |
| **am_puck** | | | | — | 0.22 |

Worst pair **0.24**, against a target of 0.40. Enrolled through the
real book: identification 0.89–0.95, profile coherence 0.86–0.92,
zero too-alike pairs. `tools/house_voices.py` re-runs this when Kokoro
or the speaker model changes.

## Identification against distance and room noise

Range across the five personas, score against their own profile.

| room (SNR at 1 m) | 0.3 m | 1 m | 3 m | 6 m |
|---|---|---|---|---|
| clean (60 dB) | 0.88–0.92 | 0.90–0.92 | 0.85–0.90 | 0.76–0.88 |
| quiet (30 dB) | 0.82–0.86 | 0.82–0.87 | 0.80–0.85 | 0.68–0.87 |
| kitchen (20 dB) | 0.77–0.85 | 0.77–0.85 | 0.76–0.83 | 0.68–0.76 |
| dishwasher (10 dB) | 0.73–0.81 | 0.73–0.83 | 0.71–0.81 | 0.61–0.72 |
| party (5 dB) | 0.65–0.77 | 0.65–0.78 | 0.64–0.75 | 0.57–0.68 |

It degrades the way it should, and at the plan's reference point --
3 m, 10 dB -- every persona is between **0.71 and 0.81**, comfortably
over the 0.50 threshold. The 6 m column is where a household would
start being misidentified: the worst cell, 0.57, is above the 0.45
lean but under the threshold, so a voice from across the room is
"probably" somebody rather than known. That matches what the creator
saw live before his profile was repaired, and it says the threshold is
defensible.

## Word error: the hiss bed is not the problem

Whisper large-v3-turbo transcribed the test sentence **perfectly in
every cell of the table above** — WER 0.00 at 6 m in a party, and
still 0.00 when the bed was pushed to −6 dB SNR, far worse than any
room in the table.

That is a finding about the *scene*, not about Sim. Smoothed Gaussian
noise, however loud, does not trouble a modern recogniser. A first
draft of this document had a table of 0.09s in every cell, which was a
bug in the scorer (punctuation stripped from the hypothesis and not
from the reference) — the real number was zero all along, and a
constant column is always worth distrusting before it is published.

## Word error: a talking television is the problem

The interference that matters is other speech. A person 3 m away,
quiet room, with the television on behind them:

| TV gain | WER | what whisper returned |
|---|---|---|
| 0.0 | 0.00 | the person |
| 0.3 | 0.00 | the person |
| 0.6 | **1.00** | *the television* |
| 1.0 | **1.00** | *the television* |

At 0.6 the recogniser does not degrade — it switches speaker. It
returns a clean transcript of the wrong voice, which is the worst
possible failure for everything downstream: the words look confident,
they are attributed to whoever was nearest, and Sim answers the
television. The television alone, with nobody speaking, also
transcribes cleanly.

So the "never answer the television" guarantee is a real test with a
real regime behind it, and the scene's `playing=` bed is the knob that
produces it. Future work on the scene belongs here — babble, clatter,
a second person — rather than in louder hiss.

## What is not measured yet

- **The three guarantees** (echo never a turn, television never
  answered, a named persona always answered) need audio driven through
  the microphone into the real session, which arrives with the script
  engine (item 4). The regimes that produce them are established above.
- **Real-room acoustics.** Every number here is synthetic speech in a
  synthetic room. The 50 recorded turns stage 3 item 6 is waiting for
  are what say whether the creator's kitchen behaves like this table.
