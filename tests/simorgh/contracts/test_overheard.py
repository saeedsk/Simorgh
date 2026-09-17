"""What Sim heard that was not said to it (contracts/overheard.py).

The creator, 2026-09-16: "for the voices that you don't recognize, or
you recognize but you understand this is not directed to you -- can you
keep track of them for one day, two days, and when I ask you, summarize
or replay them, and then after one or two days purge them." And: "you
will have a voice memo capability. Sometimes I directly tell you to
capture my voice."

Built twice that afternoon and reachable neither time. `voice/
overheard.py` recorded and could not be asked anything -- summarize,
replay and wipe appear nowhere in `commands.py` or `session.py`.
`voice/overhear.py` had every query and was imported by nothing, 313
lines of unreachable code. Both lived in Voice; the asking happens in
Execution; no subsystem may import another. The store had to move here
before either half could meet the other.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import overheard


class OverheardStoreTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def _recall(self, **kw):
        return overheard.recall(folder=self.folder, **kw)

    def test_a_line_is_kept_and_comes_back(self):
        self.assertTrue(overheard.record("it isn't fair you get pizza", speaker="Ira",
                                         at=1000.0, folder=self.folder))
        got = self._recall(now=1000.0)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["speaker"], "Ira")
        self.assertEqual(got[0]["kind"], "overheard")

    def test_a_blank_line_is_not_kept(self):
        self.assertFalse(overheard.record("   ", speaker="Ira", folder=self.folder))
        self.assertEqual(self._recall(), [])

    def test_a_voice_with_no_name_is_someone(self):
        overheard.record("mumble", at=1000.0, folder=self.folder)
        self.assertEqual(self._recall(now=1000.0)[0]["speaker"], "someone")

    def test_two_days_later_it_is_gone(self):
        """"after one or two days purge them" -- and on write, so
        nothing has to remember to run it."""
        overheard.record("old news", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("new news", speaker="Ira", at=1000.0 + 49 * 3600, folder=self.folder)
        kept = self._recall(now=1000.0 + 49 * 3600)
        self.assertEqual([k["text"] for k in kept], ["new news"])

    def test_it_can_be_asked_for_the_last_hour(self):
        overheard.record("ages ago", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("just now", speaker="Ira", at=1000.0 + 7000, folder=self.folder)
        got = self._recall(since_s=3600, now=1000.0 + 7000)
        self.assertEqual([g["text"] for g in got], ["just now"])

    def test_it_can_be_asked_about_one_person(self):
        overheard.record("hers", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("his", speaker="Aran", at=1000.0, folder=self.folder)
        self.assertEqual([g["text"] for g in self._recall(speaker="ira", now=1000.0)], ["hers"])

    def test_a_memo_is_a_different_kind_in_the_same_store(self):
        """"what did I say this morning?" should find both; "play back
        my memos" should find only one."""
        overheard.record("overheard thing", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("the gate code is 4417", kind="memo", at=1000.0, folder=self.folder)
        self.assertEqual(len(self._recall(now=1000.0)), 2)
        memos = self._recall(kind="memo", now=1000.0)
        self.assertEqual([m["text"] for m in memos], ["the gate code is 4417"])

    def test_the_transcript_reads_like_a_transcript(self):
        overheard.record("hello there", speaker="Iris", at=1000.0, folder=self.folder)
        line = overheard.transcript(self._recall(now=1000.0))
        self.assertIn("Iris: hello there", line)

    def test_who_spoke_is_counted(self):
        for _ in range(3):
            overheard.record("x", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("y", speaker="Aran", at=1000.0, folder=self.folder)
        self.assertEqual(overheard.speakers(self._recall(now=1000.0)), {"Ira": 3, "Aran": 1})

    def test_wipe_with_no_argument_empties_it(self):
        """Someone who says "forget what you heard" means all of it."""
        overheard.record("a", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("b", speaker="Aran", at=1000.0, folder=self.folder)
        self.assertEqual(overheard.wipe(folder=self.folder), 2)
        self.assertEqual(self._recall(), [])

    def test_wipe_can_be_one_person(self):
        overheard.record("a", speaker="Ira", at=1000.0, folder=self.folder)
        overheard.record("b", speaker="Aran", at=1000.0, folder=self.folder)
        self.assertEqual(overheard.wipe(speaker="Ira", folder=self.folder), 1)
        self.assertEqual([g["speaker"] for g in self._recall(now=1000.0)], ["Aran"])

    def test_wiping_nothing_is_zero_not_a_crash(self):
        self.assertEqual(overheard.wipe(folder=self.folder), 0)

    def test_recording_never_raises_into_the_voice_loop(self):
        """This is called for every line the room says. A log that could
        break listening would be worse than one that forgets."""
        with mock.patch.object(Path, "open", side_effect=OSError("read-only fs")):
            self.assertFalse(overheard.record("x", speaker="Ira", folder=self.folder))

    def test_a_corrupt_line_does_not_poison_the_rest(self):
        overheard.record("good", speaker="Ira", at=1000.0, folder=self.folder)
        path = overheard.heard_path(self.folder)
        path.write_text(path.read_text() + "{not json\n", encoding="utf-8")
        self.assertEqual([g["text"] for g in self._recall(now=1000.0)], ["good"])


if __name__ == "__main__":
    unittest.main()
