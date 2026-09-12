# Third-party notices: the voice stack

Every model and package the spoken conversation runs on, with the
exact version this was built against (2026-09-11) and its licence.
All inference is local; the network is used once, to fetch these.

## Models and weights

| model | version / file | source | licence | used for |
|---|---|---|---|---|
| Kokoro-82M | v1.0, `kokoro-v1.0.onnx` + `voices-v1.0.bin` (ONNX export) | hexgrad/Kokoro-82M, via thewh1teagle/kokoro-onnx release `model-files-v1.0` | Apache-2.0 (weights) | the primary voice: English and the other languages Kokoro ships |
| Piper voice `fa_IR-amir-medium` | piper-voices v1.0.0 | rhasspy/piper-voices on Hugging Face | dataset CC0 (datacula.com); model card carries no separate licence | the Farsi voice |
| Piper voices `fa_IR-gyro/ganji/reza_ibrahim-medium` | piper-voices v1.0.0 | same | same | evaluated (all male, 106-137 Hz); not used by default |
| Whisper `large-v3-turbo` | `ggml-large-v3-turbo.bin` (1.6 GB) | ggerganov/whisper.cpp on Hugging Face (converted from openai/whisper) | MIT (OpenAI Whisper weights) | speech recognition, all languages |
| Whisper `base.en` | `ggml-base.en.bin` | same | MIT | English-only recognition (smaller, faster, cannot hear Farsi) |
| Silero VAD | silero-vad 6.2.1 (bundled weights) | snakers4/silero-vad | MIT | voice activity detection |

## Packages

| package | version | licence | note |
|---|---|---|---|
| kokoro-onnx | 0.6.1 | MIT | runs Kokoro through onnxruntime; brings `onnxruntime` (MIT) and `numpy` (BSD-3) |
| piper-tts | 1.8.0 | **GPL-3.0** | the maintained Piper (OHF-Voice/piper1-gpl); the original rhasspy/piper is archived. It bundles espeak-ng (GPL-3.0) for phonemisation. Used as an optional, separately installed engine; nothing in this repository links against it, and a machine without it simply has no Farsi voice. Anyone redistributing a bundle that includes it must honour the GPL. |
| silero-vad | 6.2.1 | MIT | brings `torch` |
| sounddevice | 0.5.6 | MIT | PortAudio binding (PortAudio: MIT-style) |
| soundfile | 0.14.0 | BSD-3 | libsndfile (LGPL-2.1) |
| whisper.cpp (`whisper-cli`) | 1.9.1, Homebrew | MIT | recognition on Apple Silicon with Metal |
| ffmpeg | system, Homebrew | LGPL-2.1+ / GPL-2+ depending on build | capture fallback and decoding; not linked, invoked |
| faster-whisper | optional | MIT | CTranslate2 Whisper, when whisper.cpp is not wanted |

## What is deliberately not here

No cloud speech service is in the primary path. `edge-tts` (Microsoft's
neural voices through an unofficial endpoint) was evaluated for a
fluent female Farsi voice and not adopted: it sends every reply off
the machine. No voice was cloned or trained; every voice above is a
published open model with its own speakers' consent recorded by its
publisher.
