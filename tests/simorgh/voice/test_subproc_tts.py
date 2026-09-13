"""The expressive lane's plumbing (voice/tts/subproc.py, chatterbox.py,
miso.py) against a fake server: the handshake, a reply's audio, the
tone table reaching the server, a restart after a crash, and honest
refusals when an environment is missing."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.config import Config
from simorgh.voice.tts import chatterbox, miso, open_synthesiser, subproc

FIXTURE = Path(__file__).parent / "fixtures" / "fakecbx_server.py"


def _fake_venv(root: Path, engine: str) -> Path:
    """An 'environment' whose python is this interpreter."""
    bin_dir = root / engine / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / "python"
    if not link.exists():
        link.symlink_to(sys.executable)
    return root


class _Fake(subproc.SubprocessSynthesiser):
    name = "fakecbx"
    module = "json"
    server = "fakecbx_server.py"

    def params_for(self, tone: str) -> dict:
        return chatterbox.TONES.get(tone or "neutral", chatterbox.TONES["neutral"])


class SubprocessEngineTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _fake_venv(self.root, "fakecbx")
        # the engine looks for its server beside the real ones; point it at the fixture
        self._servers, subproc.SERVERS_DIR = subproc.SERVERS_DIR, FIXTURE.parent

    def tearDown(self):
        subproc.SERVERS_DIR = self._servers
        self.tmp.cleanup()

    async def test_a_sentence_comes_back_as_16_bit_audio_with_the_tone_applied(self):
        eng = _Fake(Config(venv_dir=str(self.root)))
        try:
            plain = await eng.synthesise("Ten chars!", tone="neutral")     # 0.2 s + 0.45 exaggeration
            self.assertEqual(plain.sample_rate, 16000)
            self.assertAlmostEqual(plain.seconds, 0.65, places=2)
            lively = await eng.synthesise("Ten chars!", tone="playful")   # exaggeration 0.8
            self.assertAlmostEqual(lively.seconds, 1.0, places=2, msg="the tone table reached the server")
            self.assertGreaterEqual(eng.last_took_s, 0.0); self.assertAlmostEqual(eng.last_seconds, 1.0, places=2)
            self.assertEqual(eng.voices(), ["fakecbx"])
        finally:
            await eng.close()

    async def test_a_server_that_dies_is_restarted_once_and_the_reply_still_comes(self):
        eng = _Fake(Config(venv_dir=str(self.root)))
        try:
            await eng.synthesise("hello", tone="neutral")
            first = eng._proc  # noqa: SLF001
            with self.assertRaises(RuntimeError):
                await eng.synthesise("please CRASH now", tone="neutral")   # dies twice: the second attempt also crashes
            ok = await eng.synthesise("back again", tone="neutral")
            self.assertGreater(ok.seconds, 0.0)
            self.assertIsNot(eng._proc, first)  # noqa: SLF001
            self.assertTrue(any("restarted" in p for p in eng.problems))
        finally:
            await eng.close()

    def test_missing_environments_are_refused_by_name_and_the_engine_falls_back(self):
        empty = self.root / "none"
        ok, why = chatterbox.available(str(empty))
        self.assertFalse(ok); self.assertIn("voice models chatterbox", why)
        ok, why = miso.available(str(empty), repo=str(empty / "MisoTTS"))
        self.assertFalse(ok); self.assertIn("checkout", why)
        engine, problem = open_synthesiser(Config(tts="chatterbox", venv_dir=str(empty), tts_by_language=False, model_dir=str(empty)))
        # no venv, no kokoro model in this dir: the order falls through to `say` on a Mac, or reports every reason
        self.assertTrue(engine is not None or "chatterbox" in problem, problem)
        if engine is not None:
            self.assertNotEqual(getattr(engine, "name", ""), "chatterbox")

    def test_the_tone_tables_cover_every_tone(self):
        from simorgh.contracts.tone import TONES

        for tone in TONES:
            self.assertIn(tone, chatterbox.TONES)
            self.assertIn("exaggeration", chatterbox.TONES[tone])
        self.assertIn("temperature", miso.MisoSynthesiser.params_for(None, "bright"))   # the table needs no engine


class ChatterboxVoicesTestCase(unittest.IsolatedAsyncioTestCase):
    """Chatterbox has one voice and clones the rest: its list is
    `default`, the reference WAVs on disk, and Kokoro's voices, each
    rendered once into a reference clip on first use (the creator,
    2026-09-13: "I can't see the list of supported voices")."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _fake_venv(self.root, "chatterbox")
        self._servers, subproc.SERVERS_DIR = subproc.SERVERS_DIR, FIXTURE.parent
        # `engine_available` looks for `<engine>_server.py` beside the others
        alias = FIXTURE.parent / "chatterbox_server.py"
        if not alias.exists():
            alias.symlink_to(FIXTURE)
        self._alias = alias
        self._server, chatterbox.ChatterboxSynthesiser.server = chatterbox.ChatterboxSynthesiser.server, "fakecbx_server.py"
        self._module, chatterbox.ChatterboxSynthesiser.module = chatterbox.ChatterboxSynthesiser.module, "json"

    def tearDown(self):
        subproc.SERVERS_DIR = self._servers
        chatterbox.ChatterboxSynthesiser.server = self._server
        chatterbox.ChatterboxSynthesiser.module = self._module
        self._alias.unlink(missing_ok=True)
        self.tmp.cleanup()

    def _engine(self):
        from simorgh.voice.api import Audio

        class _Kokoro:
            calls: list[str] = []

            def voices(self):
                return ["af_jessica", "am_adam"]

            async def synthesise(self, text, *, voice="", speed=1.0, tone=""):
                self.calls.append(voice)
                return Audio(b"\x00\x10" * 2400, 24000)

        eng = chatterbox.ChatterboxSynthesiser(Config(venv_dir=str(self.root), references_dir=str(self.root / "refs")))
        eng._kokoro, eng._kokoro_tried = _Kokoro(), True
        return eng

    async def test_the_list_is_default_plus_references_plus_kokoros_voices(self):
        (self.root / "refs").mkdir()
        (self.root / "refs" / "grandma.wav").write_bytes(b"RIFF")
        eng = self._engine()
        try:
            self.assertEqual(eng.voices(), ["default", "grandma", "af_jessica", "am_adam"])
            self.assertEqual(await eng.reference_for("default"), "")
            self.assertEqual(await eng.reference_for("grandma"), str(self.root / "refs" / "grandma.wav"))
            self.assertEqual(await eng.reference_for("nobody"), "", "an unknown name is the default voice")
        finally:
            await eng.close()

    async def test_a_kokoro_voice_is_rendered_once_and_sent_as_the_reference(self):
        eng = self._engine()
        try:
            first = await eng.reference_for("af_jessica")
            again = await eng.reference_for("af_jessica")
            self.assertEqual(first, again)
            self.assertTrue(Path(first).is_file())
            self.assertEqual(eng._kokoro.calls, ["af_jessica"], "rendered once, then read from disk")
            audio = await eng.synthesise("Ten chars!", voice="af_jessica", tone="neutral")
            self.assertEqual(audio.sample_rate, 16000)
        finally:
            await eng.close()
