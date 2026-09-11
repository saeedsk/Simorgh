"""macOS `say`: the synthesiser every Mac already has.

Not state of the art -- the design's Kokoro is -- but it is present, it
is local, and a voice pipeline that can speak today beats one that can
speak after a 300 MB download. `voices()` lists the installed voices.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..api import SAMPLE_RATE, Audio
from ..audio import read_wav


class SaySynthesiser:
    name = "say"

    def __init__(self, config) -> None:
        self._bin = shutil.which("say") if sys.platform == "darwin" else None
        if not self._bin:
            raise ImportError("`say` is macOS only")
        self._voice = "" if config.tts_voice in ("", "af_heart") else config.tts_voice  # af_heart is Kokoro's
        self._speed = config.tts_speed

    def voices(self) -> list[str]:
        done = subprocess.run([self._bin, "-v", "?"], capture_output=True, text=True, timeout=20)
        names = []
        for line in done.stdout.splitlines():
            head = line.split("#", 1)[0].strip()
            if head:
                names.append(head.rsplit(None, 1)[0].strip())
        return names

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        rate = int(175 * (speed or self._speed))
        with tempfile.TemporaryDirectory(prefix="simorgh-tts-") as raw:
            out = Path(raw) / "say.wav"
            args = [self._bin, "-o", str(out), f"--data-format=LEI16@{SAMPLE_RATE}", "-r", str(rate)]
            v = voice or self._voice
            if v:
                args += ["-v", v]
            args.append(text)
            done = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True, timeout=120,
                                           stdin=subprocess.DEVNULL)
            if done.returncode != 0 or not out.is_file():
                raise RuntimeError(f"say failed: {(done.stderr or done.stdout).strip()[:200]}")
            return read_wav(out)
