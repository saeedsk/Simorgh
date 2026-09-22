"""tools/voice_replay.py judges the two things the family notices first:
is the voice placed as the person, and is a line that names Sim taken
as said to Sim. The replay itself needs whisper and a booted Sim; the
verdict is pure, and pinned here."""

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "voice_replay", Path(__file__).resolve().parents[2] / "tools" / "voice_replay.py")
voice_replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(voice_replay)


def _row(who="Saeed", addressed=True, tags=("sim-start",), language="en", wer=0.0, acted=()):
    return {"line": "en-001", "who": who, "addressed": addressed, "tags": list(tags), "language": language,
            "wer": wer, "acted": list(acted)}


class TheVerdict(unittest.TestCase):
    def test_placed_and_addressed_passes(self):
        ok, _ = voice_replay.verdict([_row() for _ in range(10)], "Saeed")
        self.assertTrue(ok)

    def test_a_voice_placed_as_somebody_else_too_often_fails(self):
        ok, lines = voice_replay.verdict([_row()] * 8 + [_row(who="Ira")] * 2, "Saeed")
        self.assertFalse(ok)
        self.assertIn("identified as Saeed: 8/10", lines[0])

    def test_a_line_naming_sim_left_unaddressed_too_often_fails(self):
        ok, _ = voice_replay.verdict([_row()] * 8 + [_row(addressed=False)] * 2, "Saeed")
        self.assertFalse(ok)

    def test_an_action_is_reported(self):
        _, lines = voice_replay.verdict([_row(acted=("cast_volume",))], "Saeed")
        self.assertTrue(any("cast_volume" in line for line in lines))


class TheSandboxTakesARealRecogniser(unittest.TestCase):
    def test_the_option_reaches_the_voice_service(self):
        from simorgh.evals.house import sandbox

        marker = object()
        box = sandbox.Sandbox(recogniser=marker)
        self.assertIs(box._recogniser, marker)  # noqa: SLF001
