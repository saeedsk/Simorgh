# Words as they are said

2026-09-17. Asked to re-architect interactive voice, having watched other
systems build a sentence word by word: "they are recognizing my voice word
by word and gradually building the sentence ... they may correct the
sentence and heard word mid way".

## What the measurement said, before any framework argument

1120 live turns that day:

| stage | median | p90 | what it is |
|---|---|---|---|
| endpoint silence | 1.00s | — | a fixed timeout before the turn is even over |
| final STT decode | 2.23s | 3.40s | whisper decodes the **whole utterance again** |
| LLM | 1.65s | 6.52s | the actual thinking |
| first audio | 0.78s | 2.41s | Kokoro |
| **response** | **5.46s** | **12.48s** | |

Roughly 3.2s of the 5.5 was structural waste, not model speed.

The decisive number was decode cost against audio length: **median 1.65x
real time, max 4.54x** -- a 0.78s utterance cost 3.54s, a 1.32s one cost
5.02s. Cost per decode is near-constant, because whisper pads every input
to its 30s window. So partials could not arrive faster than one every
2-3.5s no matter how the interval was configured: **median 1 partial per
turn, max 3**. There was never a sentence being built.

That killed the first recommendation (a better partial policy over
whisper) before it was written. Word-by-word needs a streaming-native
recogniser; whisper is structurally the wrong shape.

## What replaced it

`sherpa-onnx` was already installed -- it runs TitaNet for speaker
identification. Only a model was missing. Measured on the same clip:

    6.29s of audio decoded in 0.20s   ->  0.03x real time
    16 revisions instead of 1, punctuation included
    confidence 0.687 -- a real one

`whisper_server` reports a flat `confidence=1.0` and always has, which is
why a morning of mangled transcripts ("Go on level the cold one", "Hello
Steam", "Good morning, Said") looked exactly like a clean one: 24 turns,
confidence 1.00 on every one.

## Decisions worth keeping

- **Not in `auto`.** The model is zh-en; this house speaks en,fa. Making it
  automatic would have silently stopped understanding Farsi.
- **The session must not wrap a streaming engine.** `IncrementalRecogniser`
  re-decodes the whole buffer repeatedly -- exactly the cost being removed.
- **The draft belongs in the live-status footer**, not the scrolling
  output. `_out` already clears and restores it around every printed line,
  so a revision can never interleave with a backchannel or a task line.
  `clear()` keeps the text and `_out` restores it; only `render("")`
  forgets, or the draft reappears under the settled turn.
- **The endpoint is untouched.** Only one endpointer is in play: the VAD
  one. `is_endpoint` is consulted nowhere, so ~1s of the turn is still the
  fixed silence timeout. The latency win here is the decode, not the wait.

## What the audit of the new engine found

Two settings that did nothing, both introduced by the commit that added
the engine:

- `stt_partials` -- offered in `voice set`, ignored by the streaming
  engine.
- `stt_stream_model` -- a config key in no settable list and no engine
  list: unreachable by anyone but its author, and unable to reopen the
  engine if it had been reachable.

And a check that proved nothing: the first test of the partials fix fed
silence and got zero partials either way, unable to distinguish
"suppressed" from "nothing to transcribe". Real speech, both directions.

## The lesson, restated

Six hypotheses died on contact with evidence in this session: the TV
autostart cause, the gated tokenizer, the flaky test, the margin hole in
`identify`, the "loader always takes the latest tag", and the partial
policy above. Each took one command to settle. The habit that works is to
run the thing, not to reason about it.

## Sim answered its own voice, and put a child's name on it

Turn 82, live, 21:08. Iris counted her spelling score; Sim replied "Nice
counting, Iris -- eight right out of fifteen...". The next turn in the
record is `heard: "Nice counting, Iris"`, `speaker: Iris`, answered with
"Hey, that's my line!".

Nobody said it. The 2.10 s of audio kept for that turn embeds to **-0.114
against Iris** and matches nobody in the book (best 0.135, Soodeh, against
a threshold of 0.50), while carrying the highest energy of any turn nearby
(rms 0.0147, 39% of its 20 ms frames above the speech floor, against 0.0032
and 1% for Iris's real 13 s turn beside it). Loud, dense, continuous, and
like no human in the house: a speaker playing into a microphone.

The timeline, from `voice:turns`:

```
turn-80 speech_end       ...886.78
turn-80 Sim audio START  ...895.59   (speech_end + response 8.814)
turn-82 wav window       ...894.94 -> ...897.04   -- overlaps Sim by 1.45 s
turn-82 STT finished     ...903.83   (speech_end + stt 6.785)  <- echo guard
turn-80 playback END     ...904.10   <- `recent_said.append` used to be here
```

**The guard ran 0.27 s before the reply it needed was recorded.** The
matcher was never at fault: `echoes_recent("Nice counting, Iris", [that
reply])` returns True, tested against the real strings. It was asked the
question too early. Any echo whose transcription finishes before Sim stops
talking escaped -- which, with whisper at 6.8 s and replies at 8.5 s, is
the common case, not the rare one.

The fix is the lesson the aside path had already written down for itself:
Sim remembers saying something when it commits to saying it. All three
speak paths now append to `recent_said` before `_play`, not after;
`last_said` still moves only when the reply is really finished, because
`repeat` means the reply.

## The words and the name come from different audio

Same turn, and the more interesting fault. `_identify` scored **0.513 for
Iris on 0.87 s**, while the recogniser transcribed **2.10 s**. Two buffers,
one turn (session.py:393-401):

```python
self._frames.put_nowait(frame)                    # recogniser: EVERY frame
keep = self._audio.get(self._capturing)
if keep is not None and event.kind in ("speech_start", "speech") \
        and not self._echo.active(now):           # speaker book: clean speech only
    keep += frame
```

The echo gate on the speaker buffer is deliberate and correct -- a child's
take captured over Sim's own prompt once scored 0.68 against her father.
The consequence is not: when the two buffers diverge, the transcript can be
Sim's echo while the name is measured from whatever clean frames sat beside
it. Iris was standing there, so Iris got the name, at 0.513 -- thirteen
thousandths over the line.

Nothing yet notices the divergence. `speech_s` (the identified audio) and
the kept wav's length are both recorded per turn; a turn whose two numbers
disagree by more than about a second is a turn whose name should not be
trusted. Not fixed here.

## Three wrong causes, again

Named and killed in one evening, each by one command: that the matcher's
`min_words = 4` floor let a three-word echo through (it does, but
`echoes_recent` catches it anyway -- ran it); that the exchange window had
closed (it is 20 s and the gap was 8 s); that whisper had hallucinated a
line onto near-silence (the audio is the loudest of its neighbours). And
one reversal in the other direction: the timing looked like it *exonerated*
the echo theory until the arithmetic was redone with the recorded
`response` metric instead of `answered_at - spoken_seconds`.

## The record asked for the speaker in the wrong place (2026-09-18)

23 of 122 named turns reached `voice:turns` with `speaker: ""` while
their own metrics carried the name the book had given them -- turn 70 at
0.787, turn 95 at 0.65, both well clear of the 0.50 threshold. Nothing
was wrong with the identification. The record asked the wrong object.

A turn's speaker is settled in `_ask_and_speak`. The record is written
from another method, after the model and after the whole reply has been
spoken -- seconds later -- and it re-read `last_speaker` and
`last_identification` there: session-level singletons being asked a
per-turn question. Whatever turn began in the meantime answered it.

Turn 468 shows it inside one function: `""` into the ledger record, and
`"Soodeh"` into the episodic line four lines further down, across a
single `await`, for the same turn. Both reads were the same expression.

The name is now kept per turn beside `_scored`, and the record and the
episodic line both read that. The singletons remain for the places that
legitimately mean "whoever Sim is talking to now".

**The first theory was wrong, and measuring killed it.** The obvious
explanation was an overlapping turn -- but 0 of the 23 were overlapped by
another *recorded* turn. The turn that overwrites the singleton is one
that never produces a record of its own, which is exactly why the
overlap test came back empty and why the singleton is the wrong place to
keep this.

This is the same fault as the echo above, in the other direction: there a
stale name was applied to audio nobody spoke; here a real name was
erased. One cause -- per-turn facts kept in session-level state -- two
opposite symptoms.
