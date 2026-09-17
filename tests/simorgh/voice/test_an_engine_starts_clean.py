"""An engine subprocess starts with the environment it needs, and no more.

The creator, 2026-09-16: "fix the voice tts malloc issue". Every
shutdown printed this, twice -- once per engine subprocess:

    python3(26086) MallocStackLogging: can't turn off malloc stack
    logging because it was not enabled.

Engines were started with `{**os.environ, "PYTHONUNBUFFERED": "1"}`, so
every macOS debug allocator present in the parent's environment was
inherited by children that have no use for any of them. The message is
only the visible part: these allocators are ruinously slow if they ever
do engage, and an expressive engine is already the slowest thing in the
house.

The same seam carries what an engine genuinely does need.
`PYTORCH_ENABLE_MPS_FALLBACK=1` is the difference between MisoTTS making
sound and raising NotImplementedError on `aten::unfold_backward` -- so
it belongs to the engine that needs it, declared once, rather than
exported into Sim's own process where it would change every other
tensor operation in the system.
"""

from __future__ import annotations

import os
import unittest

from simorgh.voice.tts.subproc import engine_env


class _Env:
    """Set variables for one test and put the environment back."""

    def __init__(self, **values):
        self._values = values
        self._previous: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self._values.items():
            self._previous[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *_):
        for key, previous in self._previous.items():
            os.environ.pop(key, None)
            if previous is not None:
                os.environ[key] = previous


class TheDebugAllocatorsAreLeftBehindTestCase(unittest.TestCase):
    def test_malloc_stack_logging_does_not_reach_the_engine(self):
        with _Env(MallocStackLogging="1"):
            self.assertNotIn("MallocStackLogging", engine_env())

    def test_every_known_debug_allocator_is_dropped(self):
        noisy = {"MallocStackLogging": "1", "MallocScribble": "1", "MallocGuardEdges": "1",
                 "NSZombieEnabled": "YES", "DYLD_INSERT_LIBRARIES": "/tmp/x.dylib"}
        with _Env(**noisy):
            env = engine_env()
            for key in noisy:
                with self.subTest(variable=key):
                    self.assertNotIn(key, env)

    def test_the_parent_keeps_its_own(self):
        """Sim's environment is not altered -- only the child's."""
        with _Env(MallocStackLogging="1"):
            engine_env()
            self.assertEqual(os.environ.get("MallocStackLogging"), "1")


class WhatTheEngineStillNeedsTestCase(unittest.TestCase):
    def test_the_ordinary_environment_survives(self):
        env = engine_env()
        self.assertIn("PATH", env)
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))

    def test_output_is_unbuffered(self):
        """A handshake stuck in a pipe buffer is an engine that never
        came up."""
        self.assertEqual(engine_env().get("PYTHONUNBUFFERED"), "1")

    def test_an_engine_may_add_what_only_it_needs(self):
        env = engine_env({"PYTORCH_ENABLE_MPS_FALLBACK": "1"})
        self.assertEqual(env.get("PYTORCH_ENABLE_MPS_FALLBACK"), "1")

    def test_an_engine_addition_wins(self):
        with _Env(PYTORCH_ENABLE_MPS_FALLBACK="0"):
            self.assertEqual(engine_env({"PYTORCH_ENABLE_MPS_FALLBACK": "1"})
                             .get("PYTORCH_ENABLE_MPS_FALLBACK"), "1")

    def test_no_additions_is_fine(self):
        self.assertIn("PATH", engine_env(None))


class TheEngineThatNeedsItDeclaresItTestCase(unittest.TestCase):
    def test_miso_asks_for_the_mps_fallback(self):
        """Without it: NotImplementedError on aten::unfold_backward and
        no audio at all. With it: 2.32 s of speech in 103 s (measured
        2026-09-16)."""
        from simorgh.voice.tts.miso import MisoSynthesiser

        self.assertEqual(MisoSynthesiser.extra_env.get("PYTORCH_ENABLE_MPS_FALLBACK"), "1")

    def test_it_is_a_class_attribute_not_a_process_wide_export(self):
        """Exporting it from Sim's own process would change every tensor
        operation in the system, not just this engine's."""
        from simorgh.voice.tts.miso import MisoSynthesiser

        self.assertIn("extra_env", vars(MisoSynthesiser))
        self.assertIsNone(os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"))


if __name__ == "__main__":
    unittest.main()
