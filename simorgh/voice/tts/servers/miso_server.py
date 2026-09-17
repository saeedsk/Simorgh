"""MisoTTS 8B (Miso Labs, open weights) as a line server -- run by the
engine in voice/tts/miso.py with the Python 3.10 of its own venv. The
model's code is the MisoTTS checkout (`generator.load_miso_8b`), found
through the MISO_REPO environment variable. Protocol in voice/tts/subproc.py."""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> None:
    repo = os.environ.get("MISO_REPO", "")
    if repo:
        sys.path.insert(0, repo)
    try:
        import torch
        import torchaudio as ta
        from generator import load_miso_8b
    except ImportError as exc:   # the venv is missing a package: say which
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc} (MISO_REPO={repo!r})"}), flush=True)
        return
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    device = os.environ.get("MISO_DEVICE") or ("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
    try:
        generator = load_miso_8b(device=device, model_path_or_repo_id=os.environ.get("MISO_MODEL", "MisoLabs/MisoTTS"))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"could not load MisoTTS on {device}: {exc.__class__.__name__}: {exc}"}), flush=True)
        return
    rate = int(getattr(generator, "sample_rate", 24000))
    print(json.dumps({"ready": True, "engine": "miso", "device": device, "rate": rate}), flush=True)
    context_cache: dict[str, list] = {}   # reference path -> cached segments
    _CACHE_MAX = 8                        # drop oldest-inserted refs beyond this

    def _evict_context_cache() -> None:
        # dict preserves insertion order, so the first key is the oldest.
        # A hit re-inserts the key, making this a true LRU.
        while len(context_cache) > _CACHE_MAX:
            oldest = next(iter(context_cache))
            del context_cache[oldest]

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
            params = dict(req.get("params") or {})
            text = str(req.get("text") or "")
            reference = str(req.get("reference") or "")
            context = []
            if reference:
                context = context_cache.get(reference)
                if context is not None:
                    context_cache[reference] = context_cache.pop(reference)  # touch: move to newest
                if context is None:
                    try:
                        from generator import Segment
                    except ImportError:
                        Segment = None  # noqa: N806
                    if Segment is None:
                        raise RuntimeError("MisoTTS's Segment is not importable; is MISO_REPO right?")
                    audio, sr = ta.load(reference)
                    audio = ta.functional.resample(audio.squeeze(0), orig_freq=sr, new_freq=rate)
                    context = [Segment(text=str(params.get("reference_text") or ""), speaker=0, audio=audio)]
                    context_cache[reference] = context
                    _evict_context_cache()
            started = time.monotonic()
            with torch.inference_mode():
                wav = generator.generate(text=text, speaker=int(params.get("speaker", 0)), context=context,
                                         max_audio_length_ms=int(params.get("max_audio_length_ms", 20_000)),
                                         **({"temperature": float(params["temperature"])} if params.get("temperature") is not None else {}))
            out = str(req.get("out") or f"/tmp/miso-{rid}.wav")
            ta.save(out, wav.unsqueeze(0).detach().cpu(), rate, encoding="PCM_S", bits_per_sample=16)
            print(json.dumps({"id": rid, "path": out, "rate": rate, "seconds": round(wav.shape[-1] / rate, 3),
                              "took_s": round(time.monotonic() - started, 2)}), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": rid, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
