# External channels, and why MisoTTS never made a sound

2026-09-16, late. A second round after
`2026-09-16-voice-cameras-task-quality.md`. Everything below was
measured, including the three times I was confidently wrong.

## What was asked

- "sim should be able to easily see its git history, status and remember
  it has that skill"
- "CHANGE THE CONTRACT AND INTRODUCE EXTERNAL VOICE/TEXT CHANNELS LIKE
  WHATSAPP AND TELEGRAM"
- "lets enable MisoTTS as one of sim's voice engine ... sim should store
  voice engine selection and automatically keep that setting over
  restarts"
- "when i run `voice set` sim should show options including their current
  value in a pleasant and organize format"
- "fix the voice tts malloc issue"

## MisoTTS: five faults stacked on one another

The creator heard Kokoro all evening while every screen said `miso`.
There was no single bug. Peeling them off, in the order they were found:

1. **A numpy 2 ABI break** in the engine's venv (torchtune -> datasets ->
   pyarrow). `import generator` failed; `import torch` did not.
2. **The readiness probe asked the wrong question.** `available()` ran
   `engine_available("miso", "torch", ...)` -- a DEPENDENCY, not the
   engine. Torch imported perfectly while the engine could not load at
   all, so the probe passed, `open_synthesiser` saw nothing to fall back
   from, and the refusal guard in `service._set` never fired. Chatterbox,
   which probes `chatterbox`, would have been caught.
3. **`expressive_lane` did not reopen the engines.** It decides how the
   synthesiser is BUILT (`open_synthesiser` wraps in a `LaneSynthesiser`
   only when it is not "always"), but it was in neither `_ENGINE_KEYS`
   nor `_SESSION_KEYS`. So `voice set expressive_lane always` was saved,
   reported, and had no effect; the stale pair object kept routing to
   Kokoro until an unrelated `voice set tts miso` forced a rebuild.
4. **A gated tokenizer.** `generator.py` loads Llama 3.2's tokenizer from
   `meta-llama/Llama-3.2-1B`, which is `gated=manual`. Measured, with a
   valid token for the creator's account:

   | repo | gated | download |
   |---|---|---|
   | `meta-llama/Llama-3.2-1B` | manual | 403 GatedRepoError |
   | `unsloth/Llama-3.2-1B` | False | fine |

   Same tokenizer: vocab_size 128256, bos/eos 128000/128001, llama.
5. **No MPS kernel for `aten::unfold_backward`** in torch 2.4. Synthesis
   raised NotImplementedError on Apple Silicon and no wav was ever
   written. `PYTORCH_ENABLE_MPS_FALLBACK=1` runs that one operator on the
   CPU.

End to end, once all five were off:

```
handshake  {"ready": true, "engine": "miso", "device": "mps", "rate": 24000}
synthesis  2.32 s of speech in 103.4 s   -- 44x real time
wav        2.32 s @ 24000 Hz, peak 24633, HAS AUDIO
```

44x is a `voice test` and a typed reply, never a spoken turn. Chatterbox
is 2-3x, Kokoro renders five times faster than it speaks.

## Every layer reported success over silence

Worth listing together, because the pattern is the finding:

- `voice test` printed `_engine_names["tts"]` -- for two lanes, the PAIR
  (`kokoro+miso`) -- so no output could ever answer "which am I
  hearing?". Fixed once for the lane case, and I left the single-engine
  case still reporting the CONFIGURED name, which looked fixed and was
  not. Fixed properly: an engine sets `last_engine` only after real
  audio comes back.
- `_one` returned `Audio(b"", rate)` for an empty file without looking.
- `_start` read exactly ONE line and json-parsed it. MisoTTS prints
  "Downloading the model from the Hugging Face Hub..." before its
  handshake -- measured one second apart, 228 s and 229 s -- so the
  progress note WAS the handshake, parsed to nothing, and the engine was
  declared failed while loading correctly.
- `stderr` went to DEVNULL unless `SIMORGH_TTS_DEBUG` was set, so the
  403 that explained everything was discarded as it was produced.

## Where I was wrong

- **Twice** I said the engine change had been "refused and reverted" and
  that a broken pick could never be persisted. The console showed it
  saved at 21:57:45. The guard is real; it had been handed a false
  answer by the probe in (2).
- I blamed **memory**: 18 GB of swap, an 8B model, a process vanishing.
  Plausible, wrong. `log show` found no jetsam record and the load ran
  fine on a quiet machine.
- I called the gated repo **not** the blocker on the strength of
  `model_info` answering happily. `model_info` answers for any
  authenticated user; only a file download 403s. The permission that
  matters is the one the code exercises.

The common thread: I reasoned from a reading of the code instead of
measuring, three times, on a question a single measurement settled.

## The channels

`contracts/channels.py` names every channel in one place and the
`percept.text.received` enum is built from it, so a new one is a line
rather than a hunt through six files -- and the enum stays CLOSED, which
is what caught `"dashboard"` when that was published years of bugs ago.

What makes a channel external is trust, not transport: `cli` and `voice`
need someone in the room; WhatsApp needs only the address. So both
adapters deny by default, a stranger is met with silence rather than a
refusal that confirms something is listening, and no address ever goes
on the bus -- the ledger keeps what it is given for good.

Telegram shipped first (bot token, outbound long-poll, nothing exposed).
WhatsApp is dialled into: Meta's signature on every body, the
subscription handshake, and duplicate-delivery suppression, because Meta
retries what it thinks failed.

## Still open

- Miso at 44x real time is a curiosity on this machine, not a voice.
  A GPU box would change that; nothing else will.
- `meta-llama/Llama-3.2-1B` access is still pending at Meta. The mirror
  makes that not matter.
- Sim called Iris "Ira" on a two-speaker turn. The prompt said "You are
  speaking with Saeed" while the room lines showed Iris; the model
  reached for the wrong twin. Not wiring, and not yet fixed.
