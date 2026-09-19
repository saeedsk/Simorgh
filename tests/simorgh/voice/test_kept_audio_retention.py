"""Kept recordings of the family's voices have a retention bound
(2026-09-18 evaluation, V11: 6.4 GB with no pruning)."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.voice.session import prune_kept_audio


def _turn(folder: Path, name: str, *, age_days: float, size: int, now: float) -> None:
    wav, meta = folder / f"{name}.wav", folder / f"{name}.json"
    wav.write_bytes(b"\0" * size)
    meta.write_text("{}")
    t = now - age_days * 86400
    os.utime(wav, (t, t))
    os.utime(meta, (t, t))


class KeptAudioIsBounded(unittest.TestCase):
    def test_old_turns_go_first_and_then_the_oldest_until_under_the_size(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _turn(folder, "a", age_days=10, size=1000, now=now)       # too old
            _turn(folder, "b", age_days=3, size=600_000, now=now)     # oldest of the rest
            _turn(folder, "c", age_days=2, size=600_000, now=now)
            _turn(folder, "d", age_days=1, size=600_000, now=now)
            removed = prune_kept_audio(folder, days=7, max_mb=1.2, now=now)
            names = sorted(p.stem for p in folder.glob("*.wav"))
            self.assertEqual(removed, 2)
            self.assertEqual(names, ["c", "d"])
            self.assertFalse((folder / "a.json").exists(), "the transcript goes with its audio")

    def test_zero_disables_a_bound(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _turn(folder, "a", age_days=400, size=10, now=now)
            self.assertEqual(prune_kept_audio(folder, days=0, max_mb=0, now=now), 0)
