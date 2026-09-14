"""media/tvmedia.py: a YouTube video as a file for the TV (2026-09-13)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simorgh.execution.media import tvmedia


class TvMediaTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_file_is_fetched_once_and_then_comes_from_the_cache(self):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"mp4" * 10)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        path, why = tvmedia.fetch("RqfZ3UTC14c", self.root, runner=runner, which=lambda n: "/usr/bin/yt-dlp")
        self.assertEqual((path, why), (self.root / "RqfZ3UTC14c.mp4", ""))
        self.assertTrue(path.is_file())
        cmd = calls[0]
        self.assertEqual(cmd[0], "/usr/bin/yt-dlp")
        self.assertIn("https://www.youtube.com/watch?v=RqfZ3UTC14c", cmd)
        self.assertIn("--no-playlist", cmd)
        self.assertIn("height<=1080", cmd[cmd.index("-f") + 1], "1080p H.264: what the TV plays with ease; 4K on YouTube is VP9 only")
        self.assertIn("+faststart", " ".join(cmd), "the index at the front, so it plays while it loads")
        again, _ = tvmedia.fetch("RqfZ3UTC14c", self.root, runner=runner, which=lambda n: "/usr/bin/yt-dlp")
        self.assertEqual(again, path)
        self.assertEqual(len(calls), 1, "the second ask is a cache hit")

    def test_what_is_said_when_it_cannot_be_fetched(self):
        path, why = tvmedia.fetch("RqfZ3UTC14c", self.root, which=lambda n: None)
        self.assertIsNone(path)
        self.assertIn("yt-dlp is not installed", why)
        self.assertIn("brew install yt-dlp", why)
        refused = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Sign in to confirm your age")  # noqa: E731
        path, why = tvmedia.fetch("RqfZ3UTC14c", self.root, runner=refused, which=lambda n: "yt-dlp")
        self.assertIsNone(path)
        self.assertIn("Sign in to confirm your age", why)
        self.assertFalse(list(self.root.glob("*")), "no half file left behind")

        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))

        path, why = tvmedia.fetch("RqfZ3UTC14c", self.root, runner=slow, which=lambda n: "yt-dlp", timeout_s=30)
        self.assertEqual((path, why), (None, "the download took more than 30s"))
        path, why = tvmedia.fetch("../etc", self.root, which=lambda n: "yt-dlp")
        self.assertIsNone(path)
        self.assertIn("not a YouTube video id", why)

    def test_the_cache_keeps_the_newest_files_under_the_cap(self):
        import os
        import time
        for i, name in enumerate(("old", "mid", "new")):
            p = self.root / f"{name}.mp4"
            p.write_bytes(b"x" * 100)
            os.utime(p, (time.time() - 100 + i * 10, time.time() - 100 + i * 10))
        gone = tvmedia.prune(self.root, cap_bytes=250)
        self.assertEqual(gone, 1)
        self.assertEqual(sorted(p.name for p in self.root.glob("*.mp4")), ["mid.mp4", "new.mp4"])
