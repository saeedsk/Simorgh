"""Chatterbox Persian as a line server -- run by the engine in
voice/tts/chatterbox_fa.py with the Python of the Chatterbox venv.
Protocol in voice/tts/subproc.py. Standalone: no simorgh imports.

Chatterbox's multilingual model with its text-to-speech half (T3) swapped
for Thomcles/Chatterbox-TTS-Persian-Farsi (CC-BY-NC-4.0), the way the
fine-tune's own notebook loads it: no language tag (the vocabulary has no
[fa]), temperature 0.7, cfg_weight 0.5, top_p 0.5, exaggeration 0.6. Chosen
by the creator over Pocket by ear, 2026-09-29.
"""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> None:
    try:
        import torch

        # The multilingual checkpoint was saved on CUDA; this Mac has none.
        _load = torch.load
        torch.load = lambda *a, **k: _load(*a, **{**k, "map_location": "cpu"})
        import perth  # noqa: F401 -- Chatterbox's watermarker; its model fails to import here
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            perth.PerthImplicitWatermarker = perth.DummyWatermarker
        import torchaudio as ta
        from safetensors.torch import load_file

        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except ImportError as exc:   # the venv is missing a package: say which
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    weights = os.environ.get("CHATTERBOX_FA_WEIGHTS") or ""
    if not os.path.isfile(weights):
        print(json.dumps({"ready": False, "error": f"no Persian weights at {weights!r} "
                          "(`voice models chatterbox-fa`, or set [voice] tts_farsi_chatterbox_weights)"}), flush=True)
        return
    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    try:
        torch.set_num_threads(max(2, int(os.environ.get("SIMORGH_TTS_THREADS", "4"))))
    except Exception:  # noqa: BLE001
        pass
    try:
        model = ChatterboxMultilingualTTS.from_pretrained(device=torch.device(device))
        missing, unexpected = model.t3.load_state_dict(load_file(weights), strict=False)
        if missing or unexpected:
            raise RuntimeError(f"the Persian weights do not fit: {len(missing)} missing, {len(unexpected)} unexpected")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"could not load Chatterbox Persian: {exc.__class__.__name__}: {exc}"}),
              flush=True)
        return
    print(json.dumps({"ready": True, "engine": "chatterbox_fa", "device": device, "rate": int(model.sr)}), flush=True)
    conditioned_on = None
    default_conds = model.conds
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
            kwargs = {
                "temperature": float(params.get("temperature", 0.7)),
                "cfg_weight": float(params.get("cfg_weight", 0.5)),
                "top_p": float(params.get("top_p", 0.5)),
                "exaggeration": float(params.get("exaggeration", 0.6)),
            }
            reference = str(req.get("reference") or "")
            started = time.monotonic()
            with torch.inference_mode():
                if reference and reference != conditioned_on:
                    # Once per reference, not once per sentence.
                    model.prepare_conditionals(reference, exaggeration=kwargs["exaggeration"])
                    conditioned_on = reference
                elif not reference and conditioned_on is not None:
                    model.conds = default_conds
                    conditioned_on = None
                wav = model.generate(str(req.get("text") or ""), language_id=None, **kwargs)
            out = str(req.get("out") or f"/tmp/chatterbox-fa-{rid}.wav")
            ta.save(out, wav.detach().cpu(), model.sr, encoding="PCM_S", bits_per_sample=16)
            print(json.dumps({"id": rid, "path": out, "rate": int(model.sr),
                              "seconds": round(wav.shape[-1] / model.sr, 3),
                              "took_s": round(time.monotonic() - started, 2)}), flush=True)
        except Exception as exc:  # noqa: BLE001 -- one bad reply must not end the server
            print(json.dumps({"id": rid, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
