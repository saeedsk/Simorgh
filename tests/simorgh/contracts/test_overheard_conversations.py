"""Everything said in the room, grouped into conversations.

The creator, 2026-09-16, after asking three times for a summary and
being told there was none: "sim should keep track of voice conversation,
and their summary" -- and then "keep track of overheard, and separate
them to different groups of overheard conversation that are relevant to
each other."

Two gaps behind those three refusals.

Only asides were recorded. Every `_log_overheard` call sat on a
not-for-Sim path, so a turn addressed to Sim went to `voice:turns` --
a stream owned by Voice, which Execution's tool may not read -- and the
store the tool CAN read never saw it. The words existed and were
unreachable, the same split as the two failures this store replaced.

And what was recorded was a flat list. "What did they talk about" means
the separate exchanges, not one undifferentiated stream.

Threads come from the silence between lines, not from the words. That is
crude on purpose: three minutes of quiet splits an exchange, and two
unrelated conversations three minutes apart merge. It is predictable,
which a cleverer rule that is wrong in unpredictable ways would not be.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from simorgh.contracts import overheard

BASE = 1_700_000_000.0


class ThreadingTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def _say(self, text, *, speaker="Ira", at=BASE, kind="overheard"):
        overheard.record(text, speaker=speaker, kind=kind, at=at, folder=self.folder)

    def _all(self):
        return overheard.recall(since_s=None, limit=999, now=BASE + 10_000, folder=self.folder)

    def test_lines_close_together_are_one_conversation(self):
        self._say("pizza is not fair", at=BASE)
        self._say("you always get it", speaker="Iris", at=BASE + 5)
        convs = overheard.conversations(self._all())
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["speakers"], ["Ira", "Iris"])

    def test_a_long_silence_starts_a_new_one(self):
        self._say("pizza is not fair", at=BASE)
        self._say("what is for dinner", at=BASE + overheard.THREAD_GAP_S + 1)
        self.assertEqual(len(overheard.conversations(self._all())), 2)

    def test_a_pause_shorter_than_the_gap_does_not_split(self):
        """Somebody crossing the room is not a new conversation."""
        self._say("pizza is not fair", at=BASE)
        self._say("still thinking about it", at=BASE + overheard.THREAD_GAP_S - 1)
        self.assertEqual(len(overheard.conversations(self._all())), 1)

    def test_a_conversation_knows_who_was_in_it_and_when_it_ran(self):
        self._say("one", speaker="Ira", at=BASE)
        self._say("two", speaker="Iris", at=BASE + 30)
        c = overheard.conversations(self._all())[0]
        self.assertEqual(c["speakers"], ["Ira", "Iris"])
        self.assertEqual(c["started"], BASE)
        self.assertEqual(c["ended"], BASE + 30)
        self.assertEqual([l["text"] for l in c["lines"]], ["one", "two"])

    def test_lines_written_before_threading_existed_still_group(self):
        """The live store held twelve of these. They must not crash the
        grouping, and one old conversation is the honest answer."""
        old = [{"at": BASE, "speaker": "Ira", "text": "before threads", "kind": "overheard"}]
        self.assertEqual(len(overheard.conversations(old)), 1)


class WhatWasSaidToSimTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_a_turn_addressed_to_sim_is_kept_too(self):
        """The three refusals: the words were in `voice:turns`, which the
        tool cannot read."""
        overheard.record("what time is dinner", speaker="Saeed", kind="said",
                         at=BASE, folder=self.folder)
        got = overheard.recall(kind="said", now=BASE, folder=self.folder)
        self.assertEqual([g["text"] for g in got], ["what time is dinner"])

    def test_a_summary_of_one_person_spans_both_kinds(self):
        """"Summarize what Iris said" means everything she said, whether
        it was aimed at Sim or not."""
        overheard.record("aside", speaker="Iris", kind="overheard", at=BASE, folder=self.folder)
        overheard.record("to sim", speaker="Iris", kind="said", at=BASE + 10, folder=self.folder)
        got = overheard.recall(speaker="iris", now=BASE + 10, folder=self.folder)
        self.assertEqual([g["text"] for g in got], ["aside", "to sim"])

    def test_memos_stay_a_thing_of_their_own(self):
        overheard.record("chatter", speaker="Ira", at=BASE, folder=self.folder)
        overheard.record("gate code 4417", kind="memo", at=BASE + 1, folder=self.folder)
        memos = overheard.recall(kind="memo", now=BASE + 1, folder=self.folder)
        self.assertEqual([m["text"] for m in memos], ["gate code 4417"])

    def test_said_is_a_known_kind_and_not_silently_downgraded(self):
        """`record` rewrites an unknown kind to "overheard"; a typo in the
        caller would have been invisible."""
        self.assertIn("said", overheard.KINDS)
        overheard.record("x", kind="said", at=BASE, folder=self.folder)
        self.assertEqual(overheard.recall(now=BASE, folder=self.folder)[0]["kind"], "said")


class ItStaysCheapTestCase(unittest.TestCase):
    """`record` reads the store on every write to decide the thread, and
    it runs once per utterance on the voice path."""

    def test_recording_into_a_full_store_is_still_fast(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        for n in range(500):
            overheard.record(f"line {n}", speaker="Ira", at=BASE + n, folder=folder)
        start = time.perf_counter()
        overheard.record("one more", speaker="Iris", at=BASE + 600, folder=folder)
        self.assertLess(time.perf_counter() - start, 0.25, "a spoken turn must not wait on this")


if __name__ == "__main__":
    unittest.main()
