"""The store keeps a wall clock, because it outlives the process.

Shipped broken on 2026-09-16, hours after the redesign, and caught only
by reading the live file rather than the test output.

`voice/session.py` passed `at=self._now()`, and `VoiceSession._now()` is
`time.monotonic()` -- uptime seconds, not epoch. So every line landed
with a stamp like 399417 while `recall()` measured `since_s` against
`time.time()`. The live store held 16 lines and

    recall(since_s=24h)  ->  0 of 16

`transcript()` rendered them as 07:56 for a session that started at
20:32. The feature recorded and could answer nothing -- the same failure
as its two predecessors, in a third costume.

Every test in `test_overheard.py` passed because each supplied its own
`at=1000.0` and compared it against its own `now=1000.0`. Consistent,
and never once the real clock. These are the tests that would have
caught it: they let the default clock run.
"""

from __future__ import annotations

import inspect
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.contracts import overheard


class TheDefaultClockTestCase(unittest.TestCase):
    """No explicit `at`, no explicit `now` -- the path the live system takes."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_a_line_recorded_now_is_found_now(self):
        overheard.record("something said in the room", speaker="Ira", folder=self.folder)
        found = overheard.recall(since_s=3600, folder=self.folder)
        self.assertEqual(len(found), 1, "recorded and then invisible: the 2026-09-16 shape")

    def test_the_stamp_is_a_wall_clock(self):
        overheard.record("x", speaker="Ira", folder=self.folder)
        at = overheard.recall(folder=self.folder)[0]["at"]
        self.assertGreater(at, overheard.EPOCH_FLOOR)
        self.assertLess(abs(at - time.time()), 60)

    def test_it_renders_as_the_time_of_day_it_actually_is(self):
        overheard.record("x", speaker="Ira", folder=self.folder)
        line = overheard.transcript(overheard.recall(folder=self.folder))
        self.assertTrue(line.startswith(time.strftime("%H:%M")), line[:20])


class AMonotonicStampIsCorrectedTestCase(unittest.TestCase):
    """The store is read by two subsystems; the next caller will make the
    same mistake, so it is corrected here rather than trusted."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_uptime_seconds_are_replaced_with_the_real_time(self):
        overheard.record("x", speaker="Ira", at=399417.0, folder=self.folder)
        at = overheard.recall(folder=self.folder)[0]["at"]
        self.assertGreater(at, overheard.EPOCH_FLOOR)

    def test_and_so_it_is_still_findable(self):
        overheard.record("x", speaker="Ira", at=399417.0, folder=self.folder)
        self.assertEqual(len(overheard.recall(since_s=3600, folder=self.folder)), 1)

    def test_a_real_epoch_stamp_is_left_alone(self):
        when = time.time() - 120
        overheard.record("x", speaker="Ira", at=when, folder=self.folder)
        self.assertAlmostEqual(overheard.recall(folder=self.folder)[0]["at"], when, places=3)

    def test_lines_already_written_with_the_bad_clock_are_purged(self):
        """The live file had 16 of them. They should go, not linger
        invisible: a store that holds what it can never return is worse
        than an empty one."""
        path = overheard.heard_path(self.folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"at": 399417.0, "speaker": "Ira", "text": "stale", "kind": "overheard"}\n',
                        encoding="utf-8")
        overheard.record("fresh", speaker="Ira", folder=self.folder)
        left = overheard.recall(folder=self.folder)
        self.assertEqual([x["text"] for x in left], ["fresh"])


class TheCallSiteTestCase(unittest.TestCase):
    """Asserted against the source because the bug was invisible to every
    behavioural test -- the same reason the cascade tests check that
    `_talking_with[speaker or "someone"]` is gone from the file."""

    def test_the_voice_session_does_not_pass_its_monotonic_clock(self):
        from simorgh.voice.session import VoiceSession

        src = inspect.getsource(VoiceSession._log_overheard)  # noqa: SLF001
        self.assertNotIn("at=self._now()", src,
                         "_now() is time.monotonic(); this store outlives the process")


if __name__ == "__main__":
    unittest.main()
