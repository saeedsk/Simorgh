"""`voice calibrate` in the live session, with fakes: each utterance is a
take of the line on screen (never a question for the model), a refused
take re-asks only that line with the reason, the session says nothing
aloud by default, "stop calibrating" pauses it, and a resumed session
starts at the first line it does not have."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import topics
from simorgh.voice.calibration import CalibrationRun, Levels, read_rows
from simorgh.voice.calibration_script import by_id
from simorgh.voice.speakers import SpeakerBook

from tests.simorgh.voice.test_session import _Script, _config, _run_until
from tests.simorgh.voice.test_speaker_session import _Embedder, _Replies, _session, _vec

GOOD = Levels(duration_s=3.0, speech_s=2.0, speech_dbfs=-25.0, noise_dbfs=-65.0, clipping=0.0, tail_dbfs=-65.0)


def _hear(session, *texts):
    """The recogniser says these, in order, one per turn."""
    heard = iter(texts)

    async def _transcribe(audio, *, language=""):
        from simorgh.voice.api import Utterance
        return Utterance(text=next(heard, "hello"), confidence=0.95, seconds=1.2, engine="fake", language=language)
    inner = getattr(session._stt, "_inner", None)  # noqa: SLF001
    inner.transcribe = _transcribe  # type: ignore[method-assign]


class CalibrationInTheSession(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.book = SpeakerBook(self.root / "speakers", threshold=0.5, margin=0.06, household=())
        self.book.enroll("Saeed", _vec(0.0))
        self.embedder = _Embedder()
        self.embedder.vector = _vec(0.05)            # Saeed's voice
        self.folder = self.root / "calibration"
        self.script = [by_id("en-009"), by_id("en-022")]

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **kw):
        return CalibrationRun("Saeed", self.folder, script=self.script, book=self.book, score_bar=0.5,
                              measure_fn=kw.pop("measure_fn", lambda pcm, rate: GOOD), **kw)

    async def test_takes_are_filed_a_misread_is_asked_again_and_nothing_goes_to_the_model(self):
        turns = _Script(*[(True, 60), (False, 110)] * 3, (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), turns, replies, self.embedder, self.book)
        _hear(session, "Sim, put the charts on the TV.", "what is for dinner tonight", "Turn off the kitchen lights.")
        run = self._run()
        self.assertEqual(session.calibrate(run), "")
        await _run_until(session, lambda: session._calibrating is None, timeout=10.0)  # noqa: SLF001
        self.assertEqual(replies.asked, [], "a take is never a question")
        self.assertEqual([r["line_id"] for r in read_rows(self.folder, "Saeed")], ["en-009", "en-022"])
        notices = [p["text"] for p in bus.of(topics.UI_NOTICE)]
        refused = [n for n in notices if n.startswith("not kept")]
        self.assertEqual(len(refused), 1)
        self.assertIn("what is for dinner tonight", refused[0], "the reason says what was heard")
        self.assertIn("Turn off the kitchen lights.", refused[0], "and shows the SAME line again")
        self.assertIn("complete", notices[-1])
        takes = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("enrolling") == "Saeed"]
        self.assertEqual([t["speaker_note"] for t in takes], ["", "not kept", ""])
        # (the synthesiser's warm-up word is synthesised at start and never played)
        self.assertEqual(bus.of(topics.VOICE_SPOKEN), [], "silent by default: Sim's own voice is never in a take")
        row = read_rows(self.folder, "Saeed")[0]
        self.assertGreater(row["speaker_score"], 0.9)
        self.assertEqual(row["stt_language"], "en", "the line's language was the recogniser's hint")

    async def test_another_voice_is_refused_by_the_book(self):
        self.embedder.vector = _vec(2.0)             # not Saeed
        turns = _Script((True, 60), (False, 110), (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), turns, replies, self.embedder, self.book)
        _hear(session, "Sim, put the charts on the TV.")
        session.calibrate(self._run())
        await _run_until(session, lambda: bus.of(topics.UI_NOTICE), timeout=6.0)
        self.assertIn("did not sound like Saeed", bus.of(topics.UI_NOTICE)[0]["text"])
        self.assertEqual(read_rows(self.folder, "Saeed"), [])

    async def test_a_silent_take_is_too_quiet_with_the_real_levels(self):
        turns = _Script((True, 60), (False, 110), (False, 10_000))
        session, bus, tts = _session(_config(), turns, _Replies(), self.embedder, self.book)
        _hear(session, "Sim, put the charts on the TV.")
        session.calibrate(CalibrationRun("Saeed", self.folder, script=self.script))      # the real `measure`
        await _run_until(session, lambda: bus.of(topics.UI_NOTICE), timeout=6.0)
        self.assertIn("too quiet", bus.of(topics.UI_NOTICE)[0]["text"])

    async def test_stop_then_resume_starts_at_the_first_line_it_does_not_have(self):
        turns = _Script(*[(True, 60), (False, 110)] * 2, (False, 10_000))
        replies = _Replies()
        session, bus, tts = _session(_config(), turns, replies, self.embedder, self.book)
        _hear(session, "Sim, put the charts on the TV.", "stop calibrating")
        session.calibrate(self._run())
        await _run_until(session, lambda: session._calibrating is None, timeout=10.0)  # noqa: SLF001
        self.assertIn("paused at 1/2", bus.of(topics.UI_NOTICE)[-1]["text"])
        self.assertEqual(replies.asked, [])
        again = self._run()
        self.assertEqual(again.current.id, "en-022", "the kept line is never asked for again")

    async def test_aloud_reads_the_line_only_when_asked(self):
        import asyncio

        session, bus, tts = _session(_config(), _Script((False, 10_000)), _Replies(), self.embedder, self.book)
        session.calibrate(self._run(aloud=True))
        asyncio.get_running_loop().create_task(session.say_calibration_line())
        await _run_until(session, lambda: any("put the charts on the TV" in s for s in tts.spoken), timeout=6.0)
        self.assertGreater(session._calib_said_at, 0.0, "a take that starts before this is Sim's own voice")  # noqa: SLF001

    async def test_enrolment_and_calibration_do_not_overlap(self):
        session, bus, tts = _session(_config(), _Script((False, 10)), _Replies(), self.embedder, self.book)
        session.calibrate(self._run())
        self.assertIn("calibration is in progress", session.enroll("Ira"))
        self.assertIn("paused", session.stop_calibration())
        self.assertEqual(session.stop_calibration(), "")


class TheServiceVerb(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, session=None):
        from simorgh.voice.config import Config
        from simorgh.voice.service import Service

        service = Service(Config(calibration_dir=str(self.root / "calibration"), speakers_dir=str(self.root / "sp")))
        service._session = session          # noqa: SLF001
        service._loop_task = object() if session is not None else None  # noqa: SLF001
        return service

    async def _ask(self, service, value, name=""):
        payload = {"action": "enroll", "key": "calibrate", "value": value, **({"name": name} if name else {})}
        with mock.patch("simorgh.voice.audio.input_device_name", return_value="Test Microphone"):
            return await service._people_action("enroll", payload)  # noqa: SLF001

    async def test_status_needs_no_microphone_and_names_the_owner(self):
        ok, said = await self._ask(self._service(), "status")
        self.assertTrue(ok)
        self.assertIn("Saeed: 0/67 lines", said)
        self.assertIn("English 0/51", said)
        self.assertIn("Farsi 0/16", said)
        self.assertIn("never pruned", said)

    async def test_start_needs_the_session_and_stop_needs_a_run(self):
        self.assertEqual(await self._ask(self._service(), "start"),
                         (False, "the microphone is not listening -- `voice on` first"))
        self.assertEqual(await self._ask(self._service(), "stop"), (False, "no calibration is running"))

    async def test_start_runs_in_the_session_with_the_options(self):
        book = SpeakerBook(self.root / "sp", household=())
        session, bus, tts = _session(_config(), _Script((False, 10)), _Replies(), _Embedder(), book)
        service = self._service(session)
        ok, said = await self._ask(service, "start short fa room=kitchen distance=1m", name="saeed")
        self.assertTrue(ok, said)
        self.assertIn("calibrating Saeed", said)
        self.assertIn("I stay silent", said)
        run = session._calibrating  # noqa: SLF001
        self.assertEqual(run.person, "Saeed", "the household spelling")
        self.assertTrue(all(line.language == "fa" and line.short for line in run.script))
        self.assertEqual((run.room, run.distance, run.microphone, run.aloud), ("kitchen", "1m", "Test Microphone", False))
        self.assertIn(run.current.text, said, "the first line is on screen")
        ok, said = await self._ask(service, "start")
        self.assertFalse(ok)
        self.assertIn("already calibrating", said)
        ok, said = await self._ask(service, "skip")
        self.assertTrue(ok)
        self.assertIn("skipped", said)
        ok, said = await self._ask(service, "stop")
        self.assertTrue(ok)
        self.assertIsNone(session._calibrating)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
