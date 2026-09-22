"""A kept recording that does not say whose voice it is teaches nothing.

The creator, 2026-09-21: "I don't want to bother my kids again and
again with re-enrollment."

Sim had 745 kept turns on his machine -- 142 MB of his family's
voices -- and every sidecar said what was heard and not by whom:

    at, confidence, engine, language, seconds, text, turn

So a profile could never be rebuilt from audio Sim already had, and
repairing one meant asking a child to read sentences again.

`_note_score` had been recording the name, the score, the runner-up
and whether it was a lean since 2026-09-17. `_keep_turn` merges
`_scored` -- and runs on the FINAL TRANSCRIPT, which is before the
speaker book has been asked. The two were one ordering apart.
"""

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.session import VoiceSession


class _Session:
    """Just enough of a session to drive the two methods."""

    def __init__(self, folder: Path):
        self._kept_json = {}
        self._scored = {}
        self.folder = folder
        self.warnings = []

    def _log(self, _level, event, **kw):
        self.warnings.append((event, kw))

    _name_the_kept_turn = VoiceSession._name_the_kept_turn


class ASidecarLearnsWhoSpoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "1790000000000-7.json"
        self.path.write_text(json.dumps({"at": 1.0, "turn": 7, "text": "hello",
                                         "confidence": 0.9, "engine": "whisper"}), encoding="utf-8")
        self.session = _Session(self.folder)
        self.session._kept_json[7] = self.path

    def _named(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_the_name_is_added(self):
        self.session._name_the_kept_turn(7, {"speaker_named": "Ira", "speaker_score": 0.82})
        self.assertEqual(self._named()["speaker_named"], "Ira")

    def test_what_was_already_there_survives(self):
        """The transcript is why the file is worth keeping at all."""
        self.session._name_the_kept_turn(7, {"speaker_named": "Ira"})
        self.assertEqual(self._named()["text"], "hello")

    def test_the_score_and_the_doubt_travel_too(self):
        """A relearn has to be able to pick only the takes Sim was
        sure about -- a lean is how a profile collects two people."""
        self.session._name_the_kept_turn(7, {
            "speaker_named": "Ira", "speaker_score": 0.55, "speaker_probable": True,
            "speaker_runner_up": "Iris", "speaker_runner_up_score": 0.54})
        kept = self._named()
        self.assertTrue(kept["speaker_probable"])
        self.assertEqual(kept["speaker_runner_up"], "Iris")

    def test_a_turn_that_was_never_kept_is_not_an_error(self):
        """`keep_audio` is off by default, so most turns have no
        sidecar at all."""
        self.session._name_the_kept_turn(999, {"speaker_named": "Ira"})
        self.assertEqual(self.session.warnings, [])

    def test_a_sidecar_that_vanished_is_a_warning_not_a_crash(self):
        self.path.unlink()
        self.session._name_the_kept_turn(7, {"speaker_named": "Ira"})
        self.assertEqual(self.session.warnings[0][0], "voice.kept_turn_not_named")

    def test_the_map_does_not_grow_without_bound(self):
        for turn in range(200):
            self.session._kept_json[turn] = self.folder / f"missing-{turn}.json"
        self.session._kept_json[7] = self.path
        self.session._name_the_kept_turn(7, {"speaker_named": "Ira"})
        self.assertLessEqual(len(self.session._kept_json), 64)


class TheWriterRemembersWhereItWrote(unittest.TestCase):
    def test_keep_turn_records_the_path(self):
        """Without this the sidecar cannot be found again, which is
        why the name never reached it."""
        from pathlib import Path as _P

        source = (_P(__file__).resolve().parents[3] / "simorgh" / "voice" / "session.py").read_text()
        self.assertIn('self._kept_json[turn_id] = folder / f"{stamp}.json"', source)
        self.assertIn("self._name_the_kept_turn(turn_id, note)", source)


if __name__ == "__main__":
    unittest.main()
