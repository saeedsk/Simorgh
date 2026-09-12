# Simorgh
A multi-agent cognitive architecture that orchestrates specialized emotional, technical, and persona-driven sub-routines into a unified, highly skilled, and adaptive human-like artificial consciousness.

## Talking to Sim (voice, fully local)

`./sim.sh`, then `voice on`. Speech in and out run on this machine after
a one-time download; no cloud speech service is in the path.

**Setup**

```
python tools/voice_setup.py          # pinned packages + models (~2.2 GB: Kokoro, a Farsi Piper voice, whisper large-v3-turbo)
brew install whisper-cpp ffmpeg      # macOS; whisper-cli uses Metal on Apple Silicon
```

Then in Sim: `voice bench` (measures the engines here), `voice test hello`,
`voice on`. `voice set` lists the settings you can change from the prompt
(rate, volume, language, voice, barge-in, end-of-turn silence, VAD
sensitivity, engines); a change applies at once and is saved to
`~/.simorgh/simorgh.toml`. Everything else lives in that file's `[voice]`
table (`simorgh/voice/config.py` documents every key).

**Hardware.** Measured on an Apple M3 Pro, 36 GB: first audio 0.3-0.55 s
after the answer arrives, synthesis at 0.2x real time, a 4 s utterance
transcribed in 1.9 s, 684 MB peak. Any recent laptop CPU runs Kokoro and
Piper in real time; whisper.cpp wants Metal or a strong CPU for
`large-v3-turbo` -- on a weaker machine, `voice models small` and
`voice set stt_language en` with `base.en` are the light choices.
Headphones make barge-in clean; on speakers the level gate handles it,
and `voice barge aec on` adds echo cancellation.

**Switching providers.** `voice set tts kokoro|piper|say` (say is the
macOS system voice, an emergency fallback only), `voice set stt
whisper_cli|faster_whisper`, `voice set vad_sensitivity low|balanced|high`.
Farsi replies use Piper's `fa_IR-amir-medium` automatically; `voice set
tts_farsi_voice <id>` after `voice models piper-fa` picks another. Every
engine is optional and refused by name with what to install when absent.

**Troubleshooting.** `capabilities` shows which speech engines are
present. "heard nothing": `voice devices`, then `voice listen 5 only`.
Sim answers itself: turn barge-in off (`voice set barge_in off`) or use
headphones. Farsi comes out as gibberish: `voice models piper-fa`. Farsi
is not recognised: `voice models large-v3-turbo` and `voice set
stt_language ""`. Slow first reply: the first `voice on` warms the models;
`voice bench` shows where the time goes. Licences and model sources:
`THIRD_PARTY_NOTICES.md`; the design: `docs/plans/voice-design.md`; what
is built: `simorgh/voice/README.md`.
