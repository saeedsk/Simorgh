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
    try:
        model = ChatterboxTTS.from_pretrained(device=device)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"could not load Chatterbox: {exc.__class__.__name__}: {exc}"}), flush=True)
        return
    print(json.dumps({"ready": True, "engine": "chatterbox", "device": device, "rate": int(model.sr)}), flush=True)
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
            if reference:
                kwargs["audio_prompt_path"] = reference
            started = time.monotonic()
            with torch.inference_mode():
                wav = model.generate(str(req.get("text") or ""), **kwargs)
            out = str(req.get("out") or f"/tmp/chatterbox-{rid}.wav")
            ta.save(out, wav.detach().cpu(), model.sr, encoding="PCM_S", bits_per_sample=16)
            print(json.dumps({"id": rid, "path": out, "rate": int(model.sr),
                              "seconds": round(wav.shape[-1] / model.sr, 3), "took_s": round(time.monotonic() - started, 2)}), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": rid, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
