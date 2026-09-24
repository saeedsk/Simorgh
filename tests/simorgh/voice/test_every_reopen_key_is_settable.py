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

    def test_a_setting_shown_on_the_screen_is_a_setting_that_exists(self):
        from simorgh.voice.config import Config

        fields = set(Config.__dataclass_fields__)
        unknown = sorted(k for k in VOICE_SAFE_KEYS if k not in fields)
        self.assertEqual(unknown, [], f"settable keys with no config field: {unknown}")
