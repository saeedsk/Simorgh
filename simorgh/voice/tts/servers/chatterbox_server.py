"""Chatterbox (Resemble AI, MIT) as a line server -- run by the engine in
voice/tts/chatterbox.py with the Python of its own venv. Protocol in
voice/tts/subproc.py. Standalone: no simorgh imports."""

from __future__ import annotations

import json
import sys
import time


def main() -> None:
    try:
        import perth  # noqa: F401 -- Chatterbox's watermarker; its model failed to import in one venv
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            perth.PerthImplicitWatermarker = perth.DummyWatermarker
        import torch
        import torchaudio as ta
        from chatterbox.tts import ChatterboxTTS
    except ImportError as exc:   # the venv is missing a package: say which
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    # The CPU side of generation would otherwise take every core, and
    # the player process beside it stutters (the creator, 2026-09-13).
    try:
        import os

        torch.set_num_threads(max(2, int(os.environ.get("SIMORGH_TTS_THREADS", "4"))))
    except Exception:  # noqa: BLE001
        pass
    try:
        model = ChatterboxTTS.from_pretrained(device=device)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"could not load Chatterbox: {exc.__class__.__name__}: {exc}"}), flush=True)
        return
    print(json.dumps({"ready": True, "engine": "chatterbox", "device": device, "rate": int(model.sr)}), flush=True)
    conditioned_on = None   # the reference whose conditioning `model` holds
    default_conds = model.conds   # its own voice, to return to
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
            kwargs = {"exaggeration": float(params.get("exaggeration", 0.5)), "cfg_weight": float(params.get("cfg_weight", 0.5))}
            if params.get("temperature") is not None:
                kwargs["temperature"] = float(params["temperature"])
            reference = str(req.get("reference") or "")
            started = time.monotonic()
            with torch.inference_mode():
                if reference and reference != conditioned_on:
                    # Once per reference, not once per sentence (0.3 s each).
                    model.prepare_conditionals(reference, exaggeration=kwargs["exaggeration"])
                    conditioned_on = reference
                elif not reference and conditioned_on is not None:
                    model.conds = default_conds
                    conditioned_on = None
                wav = model.generate(str(req.get("text") or ""), **kwargs)
            out = str(req.get("out") or f"/tmp/chatterbox-{rid}.wav")
            ta.save(out, wav.detach().cpu(), model.sr, encoding="PCM_S", bits_per_sample=16)
            print(json.dumps({"id": rid, "path": out, "rate": int(model.sr),
                              "seconds": round(wav.shape[-1] / model.sr, 3), "took_s": round(time.monotonic() - started, 2)}), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": rid, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
