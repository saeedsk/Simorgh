"""Stage 11 item 2: five people the embedder can tell apart.

A persona is only useful if the speaker book hears it as a person. The
numbers here come from the real path -- Kokoro speaks, the sherpa
CAM++ model embeds, the real `SpeakerBook` enrols -- so a change to
any of them shows up here rather than hiding behind a fixture.

The live measurement is marked `integration` because it loads both
models; the rest is about the household itself and costs nothing.
"""

import unittest

import pytest

from simorgh.evals.house.people import HOUSEHOLD, Persona, by_name, by_role


class TheHousehold(unittest.TestCase):
    def test_it_is_not_the_creators_family(self):
        """Cloning a household member's voice needs that person to say
        so; the simulator proves mechanics instead."""
        real = {"saeed", "soodeh", "aran", "ira", "iris"}
        self.assertFalse({p.name.lower() for p in HOUSEHOLD} & real)

    def test_every_gate_has_somebody_to_exercise_it(self):
        roles = {p.role for p in HOUSEHOLD}
        self.assertEqual(roles, {"owner", "adult", "child", "guest"},
                         "a child who may never be checked in on and a guest who gets nothing "
                         "are the cases worth having")

    def test_two_children_so_one_is_not_a_special_case(self):
        self.assertEqual(len(by_role("child")), 2)

    def test_each_persona_has_its_own_voice(self):
        voices = [p.voice for p in HOUSEHOLD]
        self.assertEqual(len(set(voices)), len(voices))

    def test_lookup_by_name_is_forgiving_about_case(self):
        self.assertEqual(by_name("mara").role, "owner")
        self.assertIsNone(by_name("nobody"))

    def test_a_persona_can_name_sim_its_own_way(self):
        p = Persona(name="X", role="adult", voice="af_river", says_sim_as="Sam")
        self.assertEqual(p.addressing("what time is it"), "Sam, what time is it")


class TheEnrolmentReport(unittest.TestCase):
    def test_too_alike_names_the_pairs_worst_first(self):
        from simorgh.evals.house.people import Enrolment

        report = Enrolment(cross={("A", "B"): 0.77, ("A", "C"): 0.42, ("B", "C"): 0.10})
        self.assertEqual([pair for pair, _ in report.too_alike()], [("A", "B"), ("A", "C")])
        self.assertEqual(report.worst_cross, 0.77)

    def test_nothing_measured_is_not_a_perfect_score(self):
        from simorgh.evals.house.people import Enrolment

        self.assertEqual(Enrolment().worst_cross, 0.0)


@pytest.mark.integration
class TheVoicesAreSeparable(unittest.IsolatedAsyncioTestCase):
    """The acceptance case, run for real: Kokoro speaks, sherpa embeds,
    the book enrols, and the numbers have to hold.

    The first hand-picked set failed this -- `af_heart` and `af_bella`
    scored 0.77 against each other -- which is why the household's
    voices were chosen by `tools/house_voices.py` instead.
    """

    async def test_each_persona_is_recognised_and_none_are_confusable(self):
        import tempfile
        from pathlib import Path

        from simorgh.evals.house.people import enrol
        from simorgh.voice.config import Config
        from simorgh.voice.speakers import SherpaEmbedder, available
        from simorgh.voice.tts.kokoro import KokoroSynthesiser

        ok, why = available("workspace/voice/models")
        if not ok:
            self.skipTest(f"the speaker model is not here: {why}")
        with tempfile.TemporaryDirectory() as tmp:
            from simorgh.voice.speakers import SpeakerBook

            report = await enrol(SpeakerBook(Path(tmp)), KokoroSynthesiser(Config()),
                                 SherpaEmbedder("workspace/voice/models"))
        for name, score in report.scores.items():
            self.assertGreaterEqual(score, 0.7, f"{name} does not sound like themselves: {score:.2f}")
        for name, value in report.coherence.items():
            self.assertGreaterEqual(value, 0.8, f"{name}'s profile does not agree with itself: {value:.2f}")
        self.assertLess(report.worst_cross, 0.4,
                        f"two personas are too alike: {report.too_alike()[:1]}")
        self.assertEqual(report.problems, [])


if __name__ == "__main__":
    unittest.main()
