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


class NoProgressBarReachesTheTerminalTestCase(unittest.TestCase):
    """An engine loads a model, and the model libraries draw a bar:

        Loading weights: 100%|█████████| 103/103 [00:00<00:00, 28it/s]

    Reported live 2026-09-20. For a subprocess engine the damage is
    worse than noise -- stdout is this protocol's own channel -- and a
    bar in the stderr tail is what an engine's failure gets reported
    with. `evals/house/script.py::tui_is_sane` fails a scene that shows
    one.
    """

    def test_the_hub_and_tqdm_bars_are_off_in_the_child(self):
        env = engine_env()
        self.assertEqual(env.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
        self.assertEqual(env.get("TQDM_DISABLE"), "1")

    def test_an_empty_value_in_the_parent_counts_as_unset(self):
        """huggingface_hub reads "" as an explicit 0 and then warns, out
        loud, that it cannot turn the bars off."""
        with _Env(HF_HUB_DISABLE_PROGRESS_BARS=""):
            self.assertEqual(engine_env().get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")

    def test_a_deliberate_zero_is_left_alone(self):
        """Somebody debugging a download wants to see it."""
        with _Env(HF_HUB_DISABLE_PROGRESS_BARS="0"):
            self.assertEqual(engine_env().get("HF_HUB_DISABLE_PROGRESS_BARS"), "0")

    def test_the_parent_environment_is_not_touched(self):
        before = os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS")
        engine_env()
        self.assertEqual(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"), before)

    def test_an_engine_may_still_override_it(self):
        self.assertEqual(engine_env({"TQDM_DISABLE": "0"}).get("TQDM_DISABLE"), "0")


class ARecogniserLoadedInThisProcessIsQuietTooTestCase(unittest.TestCase):
    """faster-whisper pulls its model through the Hugging Face hub in
    Sim's OWN process -- there is no pipe to catch the download bar, so
    the flags have to be set before the import."""

    def test_the_flags_are_set_before_the_model_loads(self):
        from simorgh.voice.api import hush_model_progress

        env: dict[str, str] = {}
        hush_model_progress(env)
        self.assertEqual(env.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
        self.assertEqual(env.get("TQDM_DISABLE"), "1")

    def test_the_recogniser_calls_it_before_importing_its_package(self):
        """Read from the code, because the import is the thing being
        ordered: the call has to come first or the library samples the
        flags before they are set."""
        import inspect

        from simorgh.voice.stt.faster_whisper import FasterWhisperRecogniser

        source = inspect.getsource(FasterWhisperRecogniser.__init__)
        self.assertLess(source.index("hush_model_progress()"),
                        source.index("from faster_whisper import"))


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
