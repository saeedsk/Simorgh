"""`voice calibrate`: a set recorded once and reused (voice/calibration.py).

The creator, 2026-09-22: "I don't want to repeat this again if you find
a bug. Record my voice, make the necessary metadata, and later if the
model needs retraining use that recording instead of asking me again."

So: a take is judged the moment it is heard and re-asked at once with
the reason; an accepted take is a WAV and a manifest row that `load()`
reads back as float samples; a resumed session never asks for a line
it already has; kept-audio retention cannot reach the folder; and
`voice relearn` prefers these takes to ordinary kept turns.
"""

from __future__ import annotations

import array
import json
import math
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.voice import calibration
from simorgh.voice.calibration import (CalibrationRun, Levels, control_word, level_problems, load, measure,
                                       normalise, read_rows, wer)
from simorgh.voice.calibration_script import ENGLISH, FARSI, LINES, SCRIPT_VERSION, by_id, lines


def _speech(seconds: float = 2.0, *, amplitude: int = 6000, noise: int = 20, tail_s: float = 0.6,
            lead_s: float = 0.0) -> bytes:
    """A voiced tone with a quiet room under it, then a trailing silence:
    what a take looks like to the level checks."""
    rate = 16000
    out = array.array("h")
    for i in range(int(lead_s * rate)):
        out.append((i * 7919 % (2 * noise + 1)) - noise)
    for i in range(int(seconds * rate)):
        value = int(amplitude * math.sin(2 * math.pi * 180 * i / rate)) + (i * 7919 % (2 * noise + 1)) - noise
        out.append(max(-32768, min(32767, value)))
    for i in range(int(tail_s * rate)):
        out.append((i * 7919 % (2 * noise + 1)) - noise)
    return out.tobytes()


GOOD = Levels(duration_s=3.0, speech_s=2.0, speech_dbfs=-25.0, noise_dbfs=-65.0, clipping=0.0, tail_dbfs=-65.0)


class _Person:
    def __init__(self, name, embeddings):
        self.name, self.embeddings = name, embeddings


class _Book:
    threshold = 0.5

    def __init__(self, embeddings):
        self.person = _Person("Saeed", embeddings)

    def get(self, name):
        return self.person if name.lower() == "saeed" else None

    @staticmethod
    def score(vector, person):
        return max(sum(a * b for a, b in zip(vector, e)) for e in person.embeddings)


class TheScript(unittest.TestCase):
    def test_ids_are_unique_and_the_set_is_the_size_asked_for(self):
        self.assertEqual(len({line.id for line in LINES}), len(LINES))
        self.assertGreaterEqual(len(ENGLISH), 45)
        self.assertGreaterEqual(len(FARSI), 12)
        self.assertGreaterEqual(SCRIPT_VERSION, 1)

    def test_the_family_the_tv_and_the_name_are_in_it(self):
        english = " ".join(line.text for line in ENGLISH)
        for word in ("Soodeh", "Aran", "Ira", "Iris", "TV", "camera", "lights", "timer", "weather", "remind"):
            self.assertIn(word.lower(), english.lower())
        tags = {tag for line in LINES for tag in line.tags}
        for tag in ("sim-start", "sim-middle", "sim-end", "sim-absent", "pause", "numbers", "long", "short-command"):
            self.assertIn(tag, tags)

    def test_farsi_is_persian_script_with_a_romanisation(self):
        for line in FARSI:
            with self.subTest(line=line.id):
                self.assertTrue(line.romanisation)
                self.assertTrue(any("؀" <= ch <= "ۿ" for ch in line.text))
                self.assertFalse(set("يكة") & set(line.text), "Persian ی and ک, not the Arabic letters")

    def test_no_line_is_a_spoken_command(self):
        """A line that IS "stop" would end the session it is read in."""
        from simorgh.voice.commands import spoken_command

        self.assertEqual([line.id for line in LINES if spoken_command(line.text)], [])

    def test_the_short_set_and_one_language(self):
        self.assertTrue(0 < len(lines(short=True)) < len(LINES) / 2)
        self.assertTrue(all(line.language == "fa" for line in lines(language="fa")))


class WordErrorRate(unittest.TestCase):
    def test_case_and_punctuation_do_not_count(self):
        self.assertEqual(wer("Sim, put the charts on the TV.", "sim put the charts on the tv"), 0.0)

    def test_it_is_word_level_levenshtein(self):
        self.assertAlmostEqual(wer("a b c d", "a x c"), 0.5)        # one substitution, one deletion
        self.assertEqual(wer("hello there", ""), 1.0)
        self.assertEqual(wer("", ""), 0.0)
        self.assertEqual(wer("", "noise"), 1.0)

    def test_numbers_read_as_words_or_digits_are_the_same(self):
        self.assertEqual(wer("Remind Soodeh at nine thirty", "remind soodeh at 9:30"), 0.0)
        self.assertEqual(wer("What is twenty-seven times forty-three?", "What is 27 times 43?"), 0.0)
        self.assertEqual(wer("three hundred and fifty grams", "350 grams"), 0.0)
        self.assertEqual(wer("Monday the fourteenth at eight fifteen", "Monday the 14th at 8.15"), 0.0)
        self.assertEqual(wer("the code is four eight one five", "the code is 4 8 1 5"), 0.0)
        self.assertEqual(wer("thirty percent", "30%"), 0.0)

    def test_persian_letter_variants_zwnj_and_digits(self):
        self.assertEqual(wer("چارت‌ها رو بذار روی تلویزیون", "چارتها رو بذار روي تلويزيون"), 0.0, "ZWNJ, ي/ی")
        self.assertEqual(wer("کجان", "كجان"), 0.0, "ك/ک")
        self.assertEqual(wer("می‌خواهم", "می خواهم"), 0.0, "the detached prefix is the same word")
        self.assertEqual(wer("بیست و پنج به علاوه‌ی هفده", "۲۵ به علاوه ی ۱۷"), 0.0, "Persian digits and words")
        self.assertEqual(wer("ساعت ۶", "ساعت 6"), 0.0)
        self.assertEqual(normalise("سیم، ساعت چنده؟"), ["سیم", "ساعت", "چنده"], "Persian punctuation")

    def test_a_different_sentence_is_far(self):
        self.assertGreater(wer("Turn off the kitchen lights.", "what is the weather tomorrow"), 0.5)


class Levels_(unittest.TestCase):
    def test_a_good_take_passes(self):
        levels = measure(_speech())
        self.assertEqual(level_problems(levels, words=6), [], levels)
        self.assertGreater(levels.speech_s, 1.5)
        self.assertLess(levels.noise_dbfs, -50)

    def test_each_problem_is_named(self):
        self.assertIn("too quiet", " ".join(level_problems(measure(_speech(amplitude=150)), words=4)))
        self.assertIn("too short", " ".join(level_problems(measure(_speech(0.2)), words=8)))
        self.assertIn("clipping", " ".join(level_problems(measure(_speech(amplitude=40000)), words=4)))
        noisy = measure(_speech(noise=3000))
        self.assertTrue(any("noisy" in p or "over the room" in p for p in level_problems(noisy, words=4)))
        cut = measure(_speech(2.0, tail_s=0.0, lead_s=0.6))
        self.assertIn("cut off", " ".join(level_problems(cut, words=4)))
        self.assertIn("length limit", " ".join(level_problems(GOOD, words=4, max_utterance_s=3.0)))


class ControlWords(unittest.TestCase):
    def test_the_few_things_said_to_the_calibration(self):
        self.assertEqual(control_word("Keep it."), "keep")
        self.assertEqual(control_word("That was right"), "accept")
        self.assertEqual(control_word("Sim, skip this one."), "skip")
        self.assertEqual(control_word("stop"), "stop")
        self.assertEqual(control_word("stop calibrating"), "stop")
        self.assertEqual(control_word("Next song."), "")


class ARun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "calibration"
        self.script = [by_id("en-009"), by_id("en-022"), by_id("fa-001")]
        self.clock = iter(range(1_000_000, 2_000_000, 7)).__next__

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **kw):
        kw.setdefault("measure_fn", lambda pcm, rate: GOOD)
        return CalibrationRun("Saeed", self.folder, script=self.script, clock=lambda: float(self.clock()),
                              device="laptop", microphone="MacBook Pro Microphone", room="kitchen", **kw)

    def test_a_good_take_is_filed_with_everything_a_measurement_needs(self):
        run = self._run()
        verdict = run.consider(_speech(), transcript="Sim, put the charts on the TV.", engine="whisper_server",
                               heard_language="en", confidence=0.93)
        self.assertEqual(verdict.kind, "accepted", verdict.message)
        self.assertIn("2/3, English", verdict.message, "the next line and where we are")
        self.assertIn("Turn off the kitchen lights.", verdict.message)
        row = read_rows(self.folder, "Saeed")[0]
        for key in ("line_id", "script_version", "reference", "romanisation", "language", "person", "recorded_at",
                    "device", "microphone", "sample_rate", "duration_s", "speech_s", "speech_dbfs", "noise_dbfs",
                    "clipping", "speaker_score", "profile_coherence", "stt_engine", "stt_transcript", "wer", "room",
                    "distance", "file"):
            self.assertIn(key, row)
        self.assertEqual((row["line_id"], row["language"], row["stt_engine"], row["wer"]),
                         ("en-009", "en", "whisper_server", 0.0))
        self.assertTrue((self.folder / "Saeed" / row["file"]).is_file())

    def test_a_bad_take_is_refused_with_the_reason_and_the_same_line_asked_again(self):
        run = self._run(measure_fn=lambda pcm, rate: Levels(3.0, 2.0, -55.0, -70.0, 0.0, -70.0))
        verdict = run.consider(b"\0\0" * 100, transcript="Sim, put the charts on the TV.")
        self.assertEqual(verdict.kind, "rejected")
        self.assertIn("too quiet", verdict.message)
        self.assertEqual(run.current.id, "en-009", "only that line, again")
        self.assertIn("Sim, put the charts on the TV.", verdict.message)
        self.assertEqual(read_rows(self.folder, "Saeed"), [], "nothing filed")

    def test_a_loud_ending_is_not_cut_off_when_the_last_word_was_heard(self):
        """Live, 2026-09-22: en-007 ends "...with Aran." -- the held /n/
        is still loud when the take ends, and the tail test refused a
        clean read twice. A take really cut mid-word loses its last word."""
        loud_tail = Levels(duration_s=3.0, speech_s=2.0, speech_dbfs=-25.0, noise_dbfs=-65.0,
                           clipping=0.0, tail_dbfs=-27.0)
        run = self._run(measure_fn=lambda pcm, rate: loud_tail)
        heard_all = run.consider(_speech(), transcript="Sim, put the charts on the TV.")
        self.assertEqual(heard_all.kind, "accepted", heard_all.message)
        run = self._run(measure_fn=lambda pcm, rate: loud_tail)
        run.consider(_speech(), transcript="Turn off the kitchen lights.")   # en-022 is next; move past en-009
        cut = self._run(measure_fn=lambda pcm, rate: loud_tail)
        missing_end = cut.consider(_speech(), transcript="Turn off the kitchen")
        self.assertEqual(missing_end.kind, "rejected")
        self.assertIn("cut off", missing_end.message)

    def test_a_voice_that_is_not_the_person_is_refused(self):
        book = _Book([[1.0, 0.0]])
        run = self._run(book=book)
        verdict = run.consider(_speech(), transcript="Sim, put the charts on the TV.", vector=[0.0, 1.0])
        self.assertEqual(verdict.kind, "rejected")
        self.assertIn("did not sound like Saeed", verdict.message)
        verdict = run.consider(_speech(), transcript="Sim, put the charts on the TV.", vector=[0.9, 0.1])
        self.assertEqual(verdict.kind, "accepted")
        row = read_rows(self.folder, "Saeed")[0]
        self.assertAlmostEqual(row["speaker_score"], 0.9)
        self.assertEqual(row["profile_coherence"], 1.0)

    def test_a_misread_can_be_kept_as_said_or_as_written(self):
        run = self._run()
        verdict = run.consider(_speech(), transcript="Sim, what is on the telly tonight, please?")
        self.assertEqual(verdict.kind, "rejected")
        self.assertIn("keep it", verdict.message)
        verdict = run.consider(_speech(), transcript="Keep it.")
        self.assertEqual(verdict.kind, "accepted")
        row = read_rows(self.folder, "Saeed")[0]
        self.assertEqual(row["reference"], "Sim, what is on the telly tonight, please?", "their words are the reference")
        self.assertEqual(row["reference_from"], "speaker")
        self.assertEqual(row["script_text"], "Sim, put the charts on the TV.")
        # ... and "that was right": the recogniser was wrong, the script stands.
        run.consider(_speech(), transcript="what is for dinner")
        run.consider(_speech(), transcript="That was right.")
        row = read_rows(self.folder, "Saeed")[1]
        self.assertEqual(row["reference"], "Turn off the kitchen lights.")
        self.assertTrue(row["misread_overridden"])

    def test_keep_does_nothing_without_a_refused_misread(self):
        run = self._run()
        self.assertEqual(run.consider(_speech(), transcript="keep it").kind, "ignored")
        self.assertEqual(read_rows(self.folder, "Saeed"), [])

    def test_resume_never_asks_for_a_line_it_has(self):
        run = self._run()
        run.consider(_speech(), transcript="Sim, put the charts on the TV.")
        again = self._run()
        self.assertEqual(again.current.id, "en-022")
        self.assertEqual(again.done_before, 1)
        self.assertIn("2/3", again.prompt())

    def test_a_changed_line_is_asked_again_rather_than_mislabelled(self):
        calibration.append_row(self.folder, "Saeed", {"line_id": "en-009", "script_text": "some older words"})
        self.assertEqual(self._run().current.id, "en-009")

    def test_skip_and_stop(self):
        run = self._run()
        verdict = run.consider(_speech(), transcript="skip")
        self.assertEqual(verdict.kind, "skipped")
        self.assertEqual(run.current.id, "en-022")
        verdict = run.consider(_speech(), transcript="stop calibrating")
        self.assertEqual(verdict.kind, "stopped")
        self.assertIn("carries on from here", verdict.message)
        self.assertEqual(self._run().current.id, "en-009", "a skipped line is asked again next time")

    def test_finishing_says_so(self):
        run = self._run()
        run.consider(_speech(), transcript="Sim, put the charts on the TV.")
        run.consider(_speech(), transcript="Turn off the kitchen lights.")
        verdict = run.consider(_speech(), transcript="سیم ساعت چنده")
        self.assertEqual(verdict.kind, "finished")
        self.assertTrue(run.finished)
        self.assertIn("3/3", calibration.summary(self.folder, "Saeed", self.script))


class TheSetIsReused(unittest.TestCase):
    def test_load_round_trips_float_samples_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            run = CalibrationRun("Saeed", folder, script=[by_id("en-009"), by_id("fa-001")],
                                 measure_fn=lambda pcm, rate: GOOD)
            pcm = _speech(1.0)
            run.consider(pcm, transcript="Sim, put the charts on the TV.")
            run.consider(pcm, transcript="سیم، ساعت چنده؟")
            takes = load(folder=folder)
            self.assertEqual([t.line_id for t in takes], ["en-009", "fa-001"])
            farsi = load("Saeed", "fa", folder=folder)
            self.assertEqual(len(farsi), 1)
            self.assertEqual(farsi[0].romanisation, "Sim, sā'at chande?")
            take = takes[0]
            self.assertIsInstance(take.samples[100], float)
            self.assertLess(max(abs(x) for x in take.samples), 1.0)
            self.assertEqual(take.sample_rate, 16000)
            self.assertEqual(take.pcm, pcm, "back to the same bytes")
            self.assertEqual(take.meta["reference"], "Sim, put the charts on the TV.")

    def test_a_missing_wav_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            calibration.append_row(tmp, "Saeed", {"line_id": "en-001", "file": "gone.wav"})
            (Path(tmp) / "Saeed" / "manifest.jsonl").open("a").write("not json\n")
            self.assertEqual(load(folder=tmp), [])


class RetentionNeverReachesIt(unittest.TestCase):
    def _old(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * 1000)
        t = time.time() - 400 * 86400
        import os

        os.utime(path, (t, t))

    def test_the_default_folders_are_apart(self):
        from simorgh.voice.config import Config

        c = Config()
        self.assertFalse(Path(c.calibration_dir).resolve().is_relative_to(Path(c.audio_dir).resolve()))

    def test_even_inside_audio_dir_the_takes_survive(self):
        from simorgh.voice.session import prune_kept_audio

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            self._old(audio / "123-1.wav")                                  # an ordinary kept turn
            self._old(audio / "calibration" / "Saeed" / "en-001-1.wav")     # a take, one level down
            calibration.append_row(audio / "calibration", "Saeed", {"line_id": "en-001"})
            self.assertEqual(prune_kept_audio(audio, days=1, max_mb=0.0001, now=time.time()), 1)
            self.assertTrue((audio / "calibration" / "Saeed" / "en-001-1.wav").exists())
            # ... and a person's own folder handed to it by mistake
            self.assertEqual(prune_kept_audio(audio / "calibration" / "Saeed", days=1, max_mb=0.0001,
                                              now=time.time()), 0)
            self.assertTrue((audio / "calibration" / "Saeed" / "en-001-1.wav").exists())


class RelearnPrefersCalibration(unittest.TestCase):
    """`voice relearn` reads the calibration takes before the kept turns."""

    def _service(self, tmp: Path):
        from simorgh.voice.config import Config
        from simorgh.voice.service import Service

        class _Embedder:
            seen: list = []

            def embed(self, samples, rate):
                assert isinstance(samples[0], float), "float samples, never raw bytes"
                self.seen.append(len(samples))
                return [1.0, 0.0]

        service = Service(Config(audio_dir=str(tmp / "audio"), calibration_dir=str(tmp / "cal")))
        service._session = type("S", (), {"_embedder": _Embedder()})()  # noqa: SLF001
        return service

    class _Book:
        def __init__(self):
            self.candidates = None

        def relearn(self, name, vectors):
            self.candidates = list(vectors)
            return len(vectors), 0, len(vectors), 0.6, 0.8

    def test_calibration_takes_come_first_and_the_kept_turns_are_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            run = CalibrationRun("Saeed", tmp / "cal", script=[by_id("en-009")], measure_fn=lambda p, r: GOOD)
            run.consider(_speech(1.0), transcript="Sim, put the charts on the TV.")
            self._old_turn(tmp / "audio")
            service, book = self._service(tmp), self._Book()
            ok, said = service._relearn_from_kept(book, "Saeed")  # noqa: SLF001
            self.assertTrue(ok, said)
            self.assertIn("calibration recording", said)
            self.assertEqual(len(book.candidates), 1, "the one calibration take, not the kept turn")

    def test_without_calibration_takes_the_kept_turns_are_used_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._old_turn(tmp / "audio")
            service, book = self._service(tmp), self._Book()
            ok, said = service._relearn_from_kept(book, "Saeed")  # noqa: SLF001
            self.assertTrue(ok, said)
            self.assertIn("kept recording", said)

    @staticmethod
    def _old_turn(folder: Path) -> None:
        from simorgh.voice.api import Audio
        from simorgh.voice.audio import write_wav

        write_wav(folder / "1-1.wav", Audio(_speech(1.0)))
        (folder / "1-1.json").write_text(json.dumps({"text": "hello"}))


if __name__ == "__main__":
    unittest.main()



class NumbersAreTheirDigits(unittest.TestCase):
    """Live, en-033 (2026-09-22): "four eight one five" read correctly,
    written "4815" by the recogniser, scored 0.4."""

    def test_a_spelled_out_code_matches_its_digits(self):
        from simorgh.voice.calibration import wer

        self.assertEqual(wer("The code is four eight one five, then press enter.",
                             "The code is 4815 then press enter."), 0.0)
        self.assertEqual(wer("What is twenty seven times forty three?", "What is 27 times 43?"), 0.0)
        self.assertGreater(wer("The code is four eight one five.", "The code is 4816."), 0.0)
