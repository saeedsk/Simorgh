"""StyleTTS 2 as a line server -- run by the engine in
voice/tts/styletts2.py with the Python of its own venv. Protocol in
voice/tts/subproc.py. Standalone: no simorgh imports.

`inference()` returns a numpy array of FLOATS and, given
`output_wav_file`, writes a float32 WAV. Sim's `Audio` is little-endian
int16, and a player handed float samples produces noise or silence while
reporting success -- the exact failure that cost the creator an evening
with MisoTTS. So the array is converted here, once, and written as
PCM_S16 with the stdlib.
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
import wave

RATE = 24_000


def _write_pcm16(path: str, samples, rate: int) -> float:
    """Float samples -> a 16-bit PCM WAV. Returns its length in seconds."""
    import numpy as np

    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    if data.size:
        peak = float(np.abs(data).max())
        if peak > 1.0:          # some voices come back a little hot
            data = data / peak
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return len(pcm) / float(rate or RATE)


def main() -> None:
    try:
        import torch
        from styletts2 import tts
    except ImportError as exc:      # the venv is missing a package: say which
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)
        return

    # The CPU side would otherwise take every core and the player process
    # beside it stutters (learnt with Chatterbox, 2026-09-13).
    try:
        import os

        torch.set_num_threads(max(2, int(os.environ.get("SIMORGH_TTS_THREADS", "4"))))
    except Exception:  # noqa: BLE001
        pass

    try:
        # The library prints on stdout -- "Cloning default target
        # voice...", the phoneme string, a token count -- and stdout is
        # this protocol's channel. Its chatter goes to stderr so only
        # JSON comes back down the pipe; a line of prose where a reply
        # belongs is a JSONDecodeError in the caller.
        with contextlib.redirect_stdout(sys.stderr):
            model = tts.StyleTTS2()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": f"could not load StyleTTS 2: {exc.__class__.__name__}: {exc}"}), flush=True)
        return

    print(json.dumps({"ready": True, "engine": "styletts2", "device": "cpu", "rate": RATE}), flush=True)

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
            reference = str(req.get("reference") or "") or None
            started = time.monotonic()
            with contextlib.redirect_stdout(sys.stderr):
                wav = model.inference(
                    str(req.get("text") or ""),
                    target_voice_path=reference,
                    output_sample_rate=RATE,
                    alpha=float(params.get("alpha", 0.3)),
                    beta=float(params.get("beta", 0.7)),
                    diffusion_steps=int(params.get("diffusion_steps", 5)),
                    embedding_scale=float(params.get("embedding_scale", 1.0)),
                )
            out = str(req.get("out") or f"/tmp/styletts2-{rid}.wav")
            seconds = _write_pcm16(out, wav, RATE)
            # An engine that returns no sound must say so, not succeed
            # quietly (voice/tts/subproc.py refuses empty audio too).
            if seconds <= 0.0:
                print(json.dumps({"id": rid, "error": "StyleTTS 2 returned no audio"}), flush=True)
                continue
            print(json.dumps({"id": rid, "path": out, "rate": RATE, "seconds": round(seconds, 3),
                              "took_s": round(time.monotonic() - started, 2)}), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": rid, "error": f"{exc.__class__.__name__}: {exc}"}), flush=True)


if __name__ == "__main__":
    main()
