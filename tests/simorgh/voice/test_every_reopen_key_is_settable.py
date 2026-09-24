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

    def test_a_settable_key_the_session_is_BUILT_from_rebuilds_the_session(self):
        """The other direction, and the one that bites.

        `VoiceSession.__init__` hands some config values to objects it
        constructs -- `IncrementalRecogniser(partial_every_ms=...)`,
        `TurnManager(Policy(...))`, `EchoTracker(...)`. Those values are
        read ONCE. A settable key among them that is in neither
        `_ENGINE_KEYS` nor `_SESSION_KEYS` takes `_set`'s "applied in
        place" branch, and the object built from it survives with the old
        value: accepted, saved, shown on the settings screen, and inert.

        `expressive_lane` did this in 2026-09-16 and
        `test_a_setting_that_rebuilds_the_engines.py` was written for it,
        but that test inspects `open_synthesiser` only. So the same
        mistake was made again on 2026-09-23, by the commit that made
        `stt_partial_every_ms` settable, and the creator found it at the
        microphone: "did you leave the word-by-word feature half baked?"

        The guard is the source of `__init__`, not a list: any settable
        key it reads must be in one of the two sets.
        """
        import inspect
        import re

        from simorgh.voice.session import VoiceSession

        body = inspect.getsource(VoiceSession.__init__)
        rebuilt = _ENGINE_KEYS | _SESSION_KEYS
        stale = sorted({
            key for key in VOICE_SAFE_KEYS
            if key not in rebuilt and re.search(rf"\bconfig\.{re.escape(key)}\b", body)
        })
        # A ratchet, not a clean sheet: these seven were already in this
        # state on 2026-09-23, and the audit of each is recorded here
        # rather than in a doc nobody opens.
        #   auto_listen         -- APPLIED: `_set` has an explicit
        #                          `session.turns.auto_listen = ...` handler.
        #   barge_in_speech_ms  -- APPLIED for the decision that matters:
        #                          `_identify_barge` reads it off `_config`
        #                          per interruption. The `Policy` copy is
        #                          stale, which only shifts when the turn
        #                          manager first calls something an
        #                          interruption.
        #   speaker_threshold   -- APPLIED: two live reads off `_config`.
        #   barge_in_calibrate_ms, speaker_margin, speaker_lean, speaker_id
        #                       -- GENUINELY STALE: no live read, no
        #                          handler, not in either set. Changing one
        #                          is accepted, saved, shown, and does
        #                          nothing until the session is rebuilt for
        #                          some other reason. Not fixed here: each
        #                          would start restarting the listen loop on
        #                          change, which wants its own verifying.
        KNOWN_STALE = ["auto_listen", "barge_in_calibrate_ms", "barge_in_speech_ms", "speaker_id",
                       "speaker_lean", "speaker_margin", "speaker_threshold"]
        self.assertEqual(stale, KNOWN_STALE,
                         "a settable key the session is BUILT from, that no `voice set` rebuilds it "
                         "for. Either add it to _SESSION_KEYS, apply it explicitly in `_set`, read it "
                         "live off `_config`, or -- having checked which -- add it to KNOWN_STALE "
                         f"with the reason. Got: {stale}")

    def test_a_setting_shown_on_the_screen_is_a_setting_that_exists(self):
        from simorgh.voice.config import Config

        fields = set(Config.__dataclass_fields__)
        unknown = sorted(k for k in VOICE_SAFE_KEYS if k not in fields)
        self.assertEqual(unknown, [], f"settable keys with no config field: {unknown}")
