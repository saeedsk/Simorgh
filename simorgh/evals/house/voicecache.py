"""Synthesised speech, kept between runs (stage 11 item 11).

Every scenario runs in its own process and most of them enrol the
household first -- twenty sentences through Kokoro -- so the same
audio was being made from scratch a dozen times a run. It is
deterministic: the same voice and the same words give the same
samples, and a cache is therefore free correctness as well as free
time.

Under the scratch directory rather than the repository: it is
derived, it is large, and nothing should ever be tempted to commit
it. A corrupt or missing entry simply synthesises again.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from simorgh.voice.api import Audio

#: Where the audio lives. `workspace/` is Sim's own scratch and is
#: already ignored by git.
CACHE = Path("workspace/house/voices")
#: The rate the cache holds, so an entry made for one pipeline is not
#: silently handed to another.
RATE = 16000


def _path(voice: str, text: str) -> Path:
    key = hashlib.sha256(f"{voice}\x00{RATE}\x00{text}".encode("utf-8")).hexdigest()[:32]
    return CACHE / f"{key}.pcm"


async def cached_speech(voice: str, text: str, make, *, transform=None) -> Audio:
    """`text` in `voice`, from the cache or freshly made."""
    path = _path(voice, text)
    try:
        return Audio(path.read_bytes(), RATE)
    except OSError:
        pass
    audio = await make()
    if transform is not None:
        audio = transform(audio)
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio.pcm)
        tmp.replace(path)
    except OSError:
        pass        # a cache that cannot be written is still a working run
    return audio


__all__ = ["CACHE", "RATE", "cached_speech"]
