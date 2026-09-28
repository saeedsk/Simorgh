"""Pocket-TTS Farsi v2 as a line server -- run by the engine in
voice/tts/pocket.py with the Python of its own venv. Protocol in
voice/tts/subproc.py. Standalone: no simorgh imports.

Two models, loaded once and kept warm:

  the G2P   `mehdi-hf/Homo-GE2PE-Persian-HF`, a small T5 that turns
            Persian script into the romanised phonemes this model reads
            -- it does not take Persian letters at all
  the TTS   `mehdi-hf/pocket-tts-farsi-v2`, 109M parameters, 24 kHz,
            whose voice is CLONED from a reference clip of five seconds

Measured on the M3 Pro, 2026-09-22: phonemes in 0.3 s, then 5.9 s of
speech in 0.8 s -- seven times real time, fast enough for a spoken
reply, which the ONNX card's "roughly real time" number had suggested
it would not be.
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave

MODEL_CONFIG = os.environ.get("POCKET_MODEL") or "hf://mehdi-hf/pocket-tts-farsi-v2/model.yaml"
G2P_MODEL = os.environ.get("POCKET_G2P") or "mehdi-hf/Homo-GE2PE-Persian-HF"
#: The model's own phoneme spelling, from its model card.
TO_PHONEMES = str.maketrans({"/": "a", "a": "A", "@": "?", "$": "S", "c": "C"})
RATE = 24000


#: What is not part of a word when a word is looked up in the lexicon.
_PUNCT = "،؛.!?؟:\"'«»()[]-—–"


def with_lexicon(words: str, sounds: str, lexicon: dict) -> str:
    """The G2P's `sounds` with every word the house gave its own sounds
    for (`[voice] tts_farsi_lexicon`) replaced. The G2P writes one
    sound-word per word, so the two line up by position; when they do
    not (it merged or split one), nothing is replaced rather than the
    wrong word. The G2P reads سعید as s/@id, the ع a glottal stop -- the
    Arabic sound the creator did not want in his name (2026-09-27)."""
    if not lexicon:
        return sounds
    said, heard = words.split(), sounds.split()
    if len(said) != len(heard):
        return sounds
    for i, word in enumerate(said):
        own = lexicon.get(word.strip(_PUNCT))
        if own:
            heard[i] = own
    return " ".join(heard)


def main() -> None:                                     # noqa: C901 -- one protocol loop, read top to bottom
    try:
        import numpy as np
        import torch
        from transformers import AutoTokenizer, T5ForConditionalGeneration

        from pocket_tts import TTSModel
    except ImportError as exc:
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    try:
        # The model's own normaliser, fetched at install time into
        # `workspace/voice/engines/pocket/` -- outside this package,
        # because it is somebody else's code.
        sys.path.insert(0, os.environ.get("POCKET_ENGINE_DIR") or "workspace/voice/engines/pocket")
        from normalize_fa import normalize_for_model
    except ImportError:
        def normalize_for_model(text: str) -> str:              # noqa: D103 -- the model's own normaliser is preferred
            return text

    try:
        torch.set_num_threads(max(2, int(os.environ.get("SIMORGH_TTS_THREADS", "4"))))
    except Exception:  # noqa: BLE001
        pass

    try:
        g2p_tok = AutoTokenizer.from_pretrained(G2P_MODEL)
        g2p = T5ForConditionalGeneration.from_pretrained(G2P_MODEL).eval()
        model = TTSModel.load_model(config=MODEL_CONFIG)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False,
                          "error": f"could not load Pocket-TTS: {exc.__class__.__name__}: {exc}"}), flush=True)
        return

    def phonemise(text: str, lexicon: dict | None = None) -> str:
        cleaned = normalize_for_model(text).replace("؟", "").replace("?", "")
        enc = g2p_tok([cleaned], add_special_tokens=False, return_tensors="pt")
        with torch.no_grad():
            out = g2p.generate(**enc, num_beams=5, max_length=512, early_stopping=True)
        sounds = g2p_tok.batch_decode(out, skip_special_tokens=True)[0].strip()
        return with_lexicon(cleaned, sounds, lexicon or {}).translate(TO_PHONEMES)

    print(json.dumps({"ready": True, "engine": "pocket", "device": "cpu", "rate": RATE}), flush=True)

    states: dict[str, object] = {}      # reference path -> its voice state, built once
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = str(req.get("id", ""))
        try:
            text = str(req.get("text") or "").strip()
            reference = str(req.get("reference") or "")
            if not reference:
                raise ValueError("Pocket-TTS speaks in a voice cloned from a reference clip, "
                                 "and none is configured ([voice] tts_farsi_reference)")
            started = time.monotonic()
            if reference not in states:
                # Five seconds is the model card's recommendation, and
                # `truncate` enforces it rather than failing on a longer
                # clip somebody points at.
                states[reference] = model.get_state_for_audio_prompt(reference, truncate=True)
            params = req.get("params") if isinstance(req.get("params"), dict) else {}
            lexicon = params.get("lexicon") if isinstance(params.get("lexicon"), dict) else {}
            phonemes = phonemise(text, lexicon)
            with torch.no_grad():
                audio = model.generate_audio(states[reference], phonemes, max_tokens=int(req.get("max_tokens") or 700))
            wave_f32 = audio.squeeze().to(torch.float32).cpu().numpy()
            pcm = (np.clip(wave_f32, -1.0, 1.0) * 32767.0).astype("<i2")
            path = os.path.join(os.environ.get("SIMORGH_TTS_TMP") or "/tmp", f"pocket-{rid or int(started)}.wav")
            with wave.open(path, "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(RATE)
                out.writeframes(pcm.tobytes())
            print(json.dumps({"id": rid, "path": path, "rate": RATE,
                              "seconds": round(len(wave_f32) / RATE, 3),
                              "took": round(time.monotonic() - started, 3)}), flush=True)
        except Exception as exc:  # noqa: BLE001 -- one bad reply must not end the server
            print(json.dumps({"id": rid, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
