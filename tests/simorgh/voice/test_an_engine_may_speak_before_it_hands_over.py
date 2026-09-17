"""A progress line before the handshake is not a dead engine.

MisoTTS prints, on stdout, before its server ever says anything:

    ckpt path or config path does not exist! Downloading the model from
    the Hugging Face Hub...

`SubprocessSynthesiser._start` read exactly ONE line and `json.loads`'d
it. So that note WAS the handshake, parsed to nothing, `self._ready`
became `{}`, and the engine was declared "failed to load" while it was
in fact loading perfectly well -- on a first run, for as long as the
download took.

Found on 2026-09-16 the hard way: a probe of mine made the identical
mistake against the identical line, and sat deadlocked until it was
killed. Two independent things reading one line and calling the first
one the answer.

What is under test is the distinction: noise is stepped over, the
handshake is waited for, and a server that dies without ever handing
over reports WHAT IT SAID on the way down -- because "it printed
nothing" was the old message, and it was never true.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.tts import subproc


def _engine(server_dir: Path, name: str = "fake_server.py", timeout: float = 30.0):
    """A synthesiser with only the pieces `_start` touches."""
    engine = object.__new__(subproc.SubprocessSynthesiser)
    engine._proc = None                 # noqa: SLF001
    engine._python = Path(sys.executable)   # noqa: SLF001
    engine._ready = {}                  # noqa: SLF001
    engine.name = "fake"
    engine.server = name
    engine.load_timeout_s = timeout
    return engine


class TheHandshakeTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        previous = subproc.SERVERS_DIR
        subproc.SERVERS_DIR = self.dir
        self.addCleanup(lambda: setattr(subproc, "SERVERS_DIR", previous))

    def _server(self, body: str) -> None:
        (self.dir / "fake_server.py").write_text(
            "import sys, time\n" + body + "\nsys.stdout.flush()\n"
            "\ntry:\n    sys.stdin.readline()\nexcept Exception:\n    pass\n")

    async def test_noise_before_the_handshake_is_stepped_over(self):
        """The exact shape MisoTTS has."""
        self._server(
            'print("ckpt path or config path does not exist! Downloading the model...", flush=True)\n'
            'print(\'{"ready": true, "engine": "fake", "rate": 24000}\', flush=True)')
        engine = _engine(self.dir)
        await engine._start()  # noqa: SLF001
        self.assertTrue(engine._ready.get("ready"))  # noqa: SLF001
        self.assertEqual(engine._ready.get("rate"), 24000)  # noqa: SLF001
        await engine._stop()  # noqa: SLF001

    async def test_several_noisy_lines_are_all_stepped_over(self):
        self._server(
            "\n".join(f'print("loading shard {i} of 4", flush=True)' for i in range(4)) +
            '\nprint(\'{"ready": true, "engine": "fake"}\', flush=True)')
        engine = _engine(self.dir)
        await engine._start()  # noqa: SLF001
        self.assertTrue(engine._ready.get("ready"))  # noqa: SLF001
        await engine._stop()  # noqa: SLF001

    async def test_a_refusal_is_still_a_refusal(self):
        """`{"ready": false}` means no, and its reason is carried."""
        self._server('print(\'{"ready": false, "error": "no weights"}\', flush=True)')
        engine = _engine(self.dir)
        with self.assertRaises(RuntimeError) as caught:
            await engine._start()  # noqa: SLF001
        self.assertIn("no weights", str(caught.exception))

    async def test_a_server_that_dies_reports_what_it_said(self):
        """The old message was "it printed nothing", which was never
        true -- the engine's own words were thrown away."""
        self._server('print("Traceback: GatedRepoError 403 forbidden", flush=True)\nraise SystemExit(1)')
        engine = _engine(self.dir)
        with self.assertRaises(RuntimeError) as caught:
            await engine._start()  # noqa: SLF001
        message = str(caught.exception)
        self.assertIn("GatedRepoError", message)
        self.assertNotIn("it printed nothing", message)

    async def test_a_silent_death_says_so_plainly(self):
        self._server("raise SystemExit(1)")
        engine = _engine(self.dir)
        with self.assertRaises(RuntimeError) as caught:
            await engine._start()  # noqa: SLF001
        self.assertIn("printed nothing", str(caught.exception))

    async def test_an_engine_that_never_hands_over_times_out(self):
        """Noise forever must not mean waiting forever."""
        self._server('import itertools\nfor i in itertools.count():\n    print("still here", flush=True)\n    time.sleep(0.05)')
        engine = _engine(self.dir, timeout=1.5)
        with self.assertRaises(RuntimeError) as caught:
            await engine._start()  # noqa: SLF001
        self.assertIn("did not come up", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
