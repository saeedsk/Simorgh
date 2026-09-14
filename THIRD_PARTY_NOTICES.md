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
| NVIDIA NeMo TitaNet-small | `nemo_en_titanet_small.onnx` (40 MB) | NVIDIA NeMo, ONNX export via k2-fsa/sherpa-onnx releases | CC-BY-4.0 (model), Apache-2.0 (NeMo) | speaker embeddings: who is speaking (voice/speakers.py); replaced CAM++ on 2026-09-13 after it failed to separate voices |
| WeSpeaker CAM++ (VoxCeleb, large-margin) | `wespeaker_en_voxceleb_CAM++_LM.onnx` (29 MB) | wenet-e2e/wespeaker, ONNX export via k2-fsa/sherpa-onnx releases | Apache-2.0 | former speaker model, still on disk; not used |

## Packages

| package | version | licence | note |
|---|---|---|---|
| kokoro-onnx | 0.6.1 | MIT | runs Kokoro through onnxruntime; brings `onnxruntime` (MIT) and `numpy` (BSD-3) |
| piper-tts | 1.8.0 | **GPL-3.0** | the maintained Piper (OHF-Voice/piper1-gpl); the original rhasspy/piper is archived. It bundles espeak-ng (GPL-3.0) for phonemisation. Used as an optional, separately installed engine; nothing in this repository links against it, and a machine without it simply has no Farsi voice. Anyone redistributing a bundle that includes it must honour the GPL. |
| silero-vad | 6.2.1 | MIT | brings `torch` |
| sherpa-onnx | 1.13.8 | Apache-2.0 | runs the speaker-embedding model through onnxruntime; optional, refused by name when missing |
| chatterbox-tts (Resemble AI) | 0.1.7, in its own venv under `workspace/voice/venvs/chatterbox` (torch 2.6.0) | MIT; the model weights download from Hugging Face (ResembleAI/chatterbox) on first use; output is watermarked by the library (Perth) | the expressive engine (`[voice] tts = "chatterbox"`): feeling by `exaggeration`, voice cloning from a reference WAV |
| MisoTTS 8B (Miso Labs) | checkout under `workspace/voice/engines/MisoTTS`, venv `venvs/miso` (Python 3.10) | open weights (MisoLabs/MisoTTS, ~16 GB bf16); no licence text found in the repository as of 2026-09-13 -- check before any use beyond experiment | the second expressive engine, built as an option; its dependency set did not resolve cleanly here (datasets/pyarrow/numpy) and it wants a 24 GB GPU |
| sounddevice | 0.5.6 | MIT | PortAudio binding (PortAudio: MIT-style) |
| soundfile | 0.14.0 | BSD-3 | libsndfile (LGPL-2.1) |
| whisper.cpp (`whisper-cli`) | 1.9.1, Homebrew | MIT | recognition on Apple Silicon with Metal |
| ffmpeg | system, Homebrew | LGPL-2.1+ / GPL-2+ depending on build | capture fallback and decoding; not linked, invoked |
| faster-whisper | optional | MIT | CTranslate2 Whisper, when whisper.cpp is not wanted |
| pychromecast | 14.0.10 | MIT | Sim on the TV over the Cast protocol (`execution/media/cast.py`); optional, refused by name when missing. Its YouTube controller (casttube 0.2.1, MIT) is broken against YouTube as of 2026-09-13 and is no longer the path for YouTube |
| yt-dlp | system (2026.08.19) | Unlicense | fetches a YouTube video as a file for the TV's own player (`execution/media/tvmedia.py`); invoked, not linked. YouTube's terms frown on downloading; the file is for the TV in this house, kept under `workspace/tv/media`, newest 3 GB |
| androidtvremote2 | 0.3.2 | Apache-2.0 | the Android TV remote protocol (`execution/media/androidtv.py`): pair once with the code the TV shows, then open the TV's own apps by deep link (YouTube at 4K) and press keys; optional, refused by name when missing |

## What is deliberately not here

No cloud speech service is in the primary path. `edge-tts` (Microsoft's
neural voices through an unofficial endpoint) was evaluated for a
fluent female Farsi voice and not adopted: it sends every reply off
the machine. No voice was cloned or trained; every voice above is a
published open model with its own speakers' consent recorded by its
publisher.
