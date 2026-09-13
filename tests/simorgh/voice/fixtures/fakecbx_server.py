"""A stand-in for an expressive engine's server (voice/tts/subproc.py):
answers the protocol with 16-bit silence whose length encodes the
request -- 0.2 s per ten characters, plus exaggeration seconds -- and
dies on the word CRASH so the engine's restart can be tested."""

import json
import os
import struct
import sys
import wave

print(json.dumps({"ready": True, "engine": "fake", "device": "cpu", "rate": 16000}), flush=True)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    text = str(req.get("text") or "")
    if "CRASH" in text:
        os._exit(3)
    params = req.get("params") or {}
    seconds = 0.2 * (len(text) / 10.0) + float(params.get("exaggeration", 0.0))
    frames = int(seconds * 16000)
    out = req.get("out") or f"/tmp/fake-{req.get('id')}.wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(struct.pack("<h", 0) * frames)
    print(json.dumps({"id": req.get("id"), "path": out, "rate": 16000, "seconds": seconds, "tone": req.get("tone")}), flush=True)
