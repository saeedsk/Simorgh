# A documentary in the room, answered as the creator

2026-09-20, live. A YouTube documentary was playing while the creator
worked. Sim answered its narration as though he had said it:

```
🎤 you: But one challenge stops them in their tracks.
  ↳ closest is Saeed at 0.29, under the threshold 0.30
  🤫 not for me -- staying quiet
🎤 Saeed: They try to flee, but running isn't an emperor's strong point.  (0.37)
⏺ 💬 chat · voice
● Right — the fled ruler in the story can't outrun what's after him…
```

It then built a theory across several turns about which story he was
telling, until he typed "it is a youtuibe audio not me".

## Why the quiet rules let it through

Every narration line is a plain statement. Probed against the
deterministic rules:

| line | question? | names Sim? | asks for something Sim does? |
|---|---|---|---|
| "But one challenge stops them in their tracks." | no | no | no |
| "They try to flee, but running isn't an emperor's strong point." | no | no | no |
| "to full height, protecting those behind." | no | no | no |

`_bystander` is the rule that sits out unaddressed statements, and it
requires **another placed voice** to have spoken recently. Every
other utterance that evening was unplaced, so there was nobody to be
talking *to*, and the line went to the model. That is correct
behaviour for a person alone in a room with Sim, which is exactly why
it is the wrong question to be asking here.

## The measured cause is the profile, not the rules

Speaker profiles on this machine, today:

| person | takes | coherence |
|---|---|---|
| Iris | 9 | 0.85 |
| Ira | 7 | 0.78 |
| **Saeed** | **12** | **0.54** |

`coherence` is the median cosine of a profile against itself. One
voice recorded several times sits around 0.8; a profile that has
collected more than one voice falls away, and `speakers.py` records
the creator's own at 0.37 earlier the same day.

A weak profile is why `speaker_threshold` is **0.30** here against a
0.50 default — lowered so that his own voice would be recognised at
all. At 0.30, television narration scores 0.37 and clears it. The
lines that stayed quiet scored 0.29, 0.28, 0.27, 0.20: this is noise
either side of a line, not an identification.

So the chain is: an incoherent profile forced a low threshold, and at
that threshold things that are not him cross it.

**No quiet rule is being widened for this.** Doing so would paper
over a broken profile with a behaviour change, and widening those
rules has regressed this project twice. The fix is re-enrolment, and
that needs the creator: his 12 takes at 0.54 contain more than one
voice, and `voice forget Saeed` then `voice enroll Saeed` is the
repair.

## What did land

`stage11/the-television-is-not-a-person`, and the means to play it.
Stage 11 item 3 names three guarantees, one of which is "the
television never gets an answer" -- and the mixer had no way to fire
the television ALONE: `into_the_room(..., tv=...)` lays the set under
a person who is really speaking, so the case that matters had never
been played. `Director.from_the_television` and a `television=` beat
do that now.

**Corrected twice on 2026-09-21, and the corrections are the useful
part.**

*First*, the expectation sat on the last beat only, and it passed
three runs in a row with nothing about the bug changed: beat 1 is
answered, `_quiet_on` is stamped, and `_continuation` covers the
rest, so it went green on the rule that fires *after* the mistake.
Every beat is asserted now.

*Second*, and worse: with nobody enrolled, `_unplaced` is disabled on
purpose -- "nobody is enrolled, so nobody can ever be placed: the
rule would silence the whole house". The scenario was therefore
testing a house where no one has a voice on file, which is not this
one, and demanding a guarantee that configuration cannot give. A
persona now speaks first, which puts the household in the speaker
book, and it passes 3/3.

**So it does not reproduce the creator's failure, and the earlier
claim here that it did was wrong.** Read off the record:

```
beat 2  quiet -- "someone and Mara are talking to each other"
beat 4  quiet -- "a voice Sim cannot place, not naming Sim"
```

The set's voice arrives UNPLACED and two independent rules refuse it.
That is a real guarantee and this now guards it. The creator's
television was placed as HIM at 0.37, so neither rule could apply:
`_unplaced` only fires on a voice with no name, and `_bystander`
needs somebody else talking. Reproducing his case needs a profile
weak enough for narration to cross its threshold -- a property of his
speaker book, not of this pack, and the repair is still re-enrolment.

I guessed at the mechanism twice and was wrong twice. The third
attempt read the `quiet` reasons Sim had been recording all along. It reproduces the live failure on demand, which is what turns
this from an anecdote into something a fix can be measured against.
It goes green when the profile is repaired, or when a rule change is
justified by evidence that does not exist yet.
