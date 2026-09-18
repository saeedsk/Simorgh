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
