"""A setting that changes how the engines are BUILT must reopen them.

The creator, 2026-09-16: "what hapens i stil hear kokoro model not miso
:(" -- after `voice set expressive_lane always` had been accepted, saved
to simorgh.toml, and reported back to him.

It was saved and it had no effect. `expressive_lane` does not merely
pick a lane at speak time: `tts/__init__.py::open_synthesiser` wraps the
expressive engine in a `LaneSynthesiser` *only when it is not "always"*.
So the setting decides the SHAPE of the synthesiser that gets built --
and `expressive_lane` was in neither `_ENGINE_KEYS` nor `_SESSION_KEYS`,
so `voice set` took the "applied in place" branch and nothing was
rebuilt. The stale pair object survived and went on routing every turn
to Kokoro. It only took effect when an unrelated `voice set tts miso`
forced a reopen, minutes later.

Everything downstream reported honestly and none of it helped: the value
was saved, the file was right, the settings screen said `always`. The
one thing that was wrong was invisible.

So the guard here is not "expressive_lane is in the set" -- that fixes
tonight and nothing else. It is: every config key `open_synthesiser`
reads is a key that reopens the engines. The next setting that changes
how the synthesiser is constructed cannot go stale the same way without
failing this test.
"""

from __future__ import annotations

import inspect
import re
import unittest

from simorgh.voice.service import _ENGINE_KEYS, _spoken_by


class TheEnginesAreRebuiltTestCase(unittest.TestCase):
    def test_expressive_lane_reopens_the_engines(self):
        self.assertIn("expressive_lane", _ENGINE_KEYS)

    def test_every_key_open_synthesiser_reads_reopens_the_engines(self):
        """The general form. A key that shapes construction and does not
        reopen is a setting that reports success and does nothing."""
        from simorgh.voice.tts import open_synthesiser

        source = inspect.getsource(open_synthesiser)
        read = set(re.findall(r'getattr\(config,\s*"([a-z_]+)"', source))
        read |= set(re.findall(r"config\.([a-z_]+)", source))
        # Keys that name the engine itself are already covered, and
        # `tts_by_language` only picks the Polyglot wrapper, which is
        # rebuilt with the engines whenever any of these change.
        exempt = {"tts", "tts_by_language"}
        missing = sorted(k for k in read - exempt if k not in _ENGINE_KEYS)
        self.assertEqual(missing, [],
                         f"these shape the synthesiser but do not reopen it: {missing}")

    def test_a_speak_time_key_does_not_need_a_rebuild(self):
        """The counterweight: `expressive_min_chars` is read per turn by
        `_lane_for`, so tearing the stack down for it would be the old
        bug -- Sim going dead for seconds after every `voice set`."""
        self.assertNotIn("expressive_min_chars", _ENGINE_KEYS)


class TheEngineThatSpokeTestCase(unittest.TestCase):
    """`voice test` printed the PAIR -- `kokoro+miso` -- whichever engine
    made the sound, so no output could answer "which am I hearing?"."""

    def test_it_looks_through_a_wrapper(self):
        class _Lane:
            last_engine = "miso"

        class _Polyglot:
            last_engine = ""
            _primary = _Lane()

        self.assertEqual(_spoken_by(_Polyglot(), "kokoro+miso"), "miso")

    def test_a_plain_engine_falls_back_to_its_name(self):
        self.assertEqual(_spoken_by(object(), "miso"), "miso")

    def test_none_falls_back_rather_than_raising(self):
        self.assertEqual(_spoken_by(None, "kokoro"), "kokoro")

    def test_it_does_not_loop_forever_on_a_cycle(self):
        class _Loop:
            last_engine = ""

        a = _Loop()
        a._primary = a
        self.assertEqual(_spoken_by(a, "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
