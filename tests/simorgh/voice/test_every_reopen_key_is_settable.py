"""A key that reopens the engines but cannot be set is a dead branch.

`_ENGINE_KEYS` and `_SESSION_KEYS` say what `voice set <key>` must tear
down and rebuild.  `VOICE_SAFE_KEYS` decides what `voice set` ACCEPTS at
all -- a key missing from it is refused while it is being parsed, long
before either branch is consulted.

So a key in one and not the other is a wire with one end: found
2026-09-23 with `microphone` and `speaker`, which sat in `_ENGINE_KEYS`
from the day it was written and could never be reached, because neither
was ever a settable key.  Nothing failed; the reopen simply never ran,
the same shape as `expressive_lane` (`test_a_setting_that_rebuilds_the_engines.py`)
one layer up.

This holds the two tables against each other in the direction that can
go quiet: a rebuild rule for a key nobody can set.  The other direction
-- a settable key that decides how an engine is BUILT and does not
reopen -- is what the `expressive_lane` test guards.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.settings import VOICE_SAFE_KEYS
from simorgh.voice.service import _ENGINE_KEYS, _SESSION_KEYS


class EveryReopenKeyIsSettableTestCase(unittest.TestCase):
    def test_engine_keys_can_all_be_set(self):
        dead = sorted(k for k in _ENGINE_KEYS if k not in VOICE_SAFE_KEYS)
        self.assertEqual(dead, [], f"_ENGINE_KEYS entries no `voice set` can reach: {dead}")

    def test_session_keys_can_all_be_set(self):
        dead = sorted(k for k in _SESSION_KEYS if k not in VOICE_SAFE_KEYS)
        self.assertEqual(dead, [], f"_SESSION_KEYS entries no `voice set` can reach: {dead}")

    def test_the_control_verbs_set_a_real_key(self):
        """`voice barge on|off` and `voice barge aec on|off` go through
        `_set`, so the keys they name must be settable -- otherwise the
        verb reports success and writes nothing (the creator, 2026-09-23:
        "barge_in doesn't persist over sim restarts")."""
        for key in ("barge_in", "aec"):
            self.assertIn(key, VOICE_SAFE_KEYS)

    def test_the_guard_against_sim_interrupting_itself_can_be_turned_on(self):
        """The creator, 2026-09-23, with barge-in on: "sim voice gets
        interrupted even when I'm not talking at all". Sim was hearing its
        own reply -- it said "It's Wednesday, September 23rd, 2026." and
        transcribed "23rd, 2000." -- and the level gate cut it off
        (`voice.barge_in stop_s=0.0`, three times).

        `barge_in_known_voice` is the guard written for exactly that ("or
        any family voice ... like my voice basically"), and it was READ
        live and settable NOWHERE, so the one switch that answers the
        complaint could only be reached by hand-editing simorgh.toml.
        `aec` is not that switch: nothing on the live path reads it (V7).
        """
        self.assertIn("barge_in_known_voice", VOICE_SAFE_KEYS)
        # And it must NOT be an engine or session key: it is consulted per
        # interruption (`session._identify_barge`), so `_set`'s in-place
        # branch is what applies it -- tearing the engines down to change
        # it would put the microphone away mid-conversation for nothing.
        self.assertNotIn("barge_in_known_voice", _ENGINE_KEYS)
        self.assertNotIn("barge_in_known_voice", _SESSION_KEYS)

    def test_a_setting_shown_on_the_screen_is_a_setting_that_exists(self):
        from simorgh.voice.config import Config

        fields = set(Config.__dataclass_fields__)
        unknown = sorted(k for k in VOICE_SAFE_KEYS if k not in fields)
        self.assertEqual(unknown, [], f"settable keys with no config field: {unknown}")
