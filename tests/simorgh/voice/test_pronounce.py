"""A name said the household's way (voice/pronounce.py, planner.pronounced):
IPA is kept for the engine that speaks it and respelled for one that
reads letters; the screen keeps the spelling; a name the model spells
out after itself is said once."""

from __future__ import annotations

import unittest

from simorgh.voice.planner import SpokenResponsePlanner, _drop_self_respelling
from simorgh.voice.pronounce import is_ipa, normalise, phonemes_for, respell, strip_marks


class PronounceTestCase(unittest.TestCase):
    def test_ipa_is_told_from_a_respelling_and_normalised(self):
        self.assertTrue(is_ipa("sæ'iːd")); self.assertTrue(is_ipa("/sæˈiːd/"))
        self.assertFalse(is_ipa("Ay-raa")); self.assertFalse(is_ipa("Soo deh"))
        self.assertEqual(normalise("/sæ'iːd/"), "sæˈiːd")
        self.assertEqual(normalise("Ay-raa"), "Ay-raa")

    def test_a_rough_respelling_comes_out_of_ipa(self):
        self.assertEqual(respell("sæˈiːd"), "sa-eed")
        self.assertEqual(respell("ˈaɪɹɪs"), "airis")
        self.assertEqual(respell("suːˈdɛ"), "soo-de")

    def test_marks_are_respelled_for_a_voice_and_named_for_the_screen(self):
        text = "Hello ⟦Saeed|sæˈiːd⟧, dinner is at six."
        self.assertEqual(strip_marks(text), "Hello sa-eed, dinner is at six.")
        self.assertEqual(strip_marks(text, for_voice=False), "Hello Saeed, dinner is at six.")
        self.assertEqual(strip_marks("no marks"), "no marks")

    def test_phonemes_splice_the_ipa_into_the_phonemized_rest(self):
        out = phonemes_for("Hello ⟦Saeed|sæˈiːd⟧, dinner.", lambda plain: f"<{plain.strip()}>")
        self.assertEqual(out, "<Hello> sæˈiːd<, dinner.>", "the word boundary before the name survives the phonemizer's trim")
        out = phonemes_for("⟦Aran|ɑːˈɹɑːn⟧ and ⟦Iris|ˈaɪɹɪs⟧ are here.", lambda plain: f"<{plain.strip()}>")
        self.assertEqual(out, "ɑːˈɹɑːn <and> ˈaɪɹɪs <are here.>")
        self.assertEqual(phonemes_for("⟦Saeed|sæˈiːd⟧", lambda p: "!"), "sæˈiːd")


class PlannerPronunciationTestCase(unittest.TestCase):
    def _planner(self, table):
        return SpokenResponsePlanner(pronunciations=lambda: table)

    def test_a_respelling_replaces_the_name_and_ipa_becomes_a_mark(self):
        planner = self._planner({"Ira": "Ay-raa", "Saeed": "sæˈiːd"})
        self.assertEqual(planner.pronounced("Ira and Saeed are here."), "Ay-raa and ⟦Saeed|sæˈiːd⟧ are here.")

    def test_the_models_own_respelling_after_the_name_is_dropped(self):
        for text in ("Saeed — Saa-eed.", "Saeed (SAH-eed).", "Saeed, pronounced Sah-eed.", "Saeed - Saeed."):
            self.assertEqual(_drop_self_respelling(text, "Saeed").rstrip("."), "Saeed", text)
        self.assertEqual(_drop_self_respelling("Saeed - the pool is warm.", "Saeed"), "Saeed - the pool is warm.",
                         "words that are not the name's sound stay")
        planner = self._planner({"Saeed": "Sah-eed"})
        self.assertEqual(planner.pronounced("Saeed — Saa-eed."), "Sah-eed.")

    def test_the_plan_keeps_the_mark_for_the_engine(self):
        planner = self._planner({"Saeed": "sæˈiːd"})
        plan = planner.plan("Hello Saeed, dinner is at six.")
        self.assertIn("⟦Saeed|sæˈiːd⟧", plan.text, "speakable() must not eat the mark as a link")
        self.assertEqual(strip_marks(plan.text, for_voice=False), "Hello Saeed, dinner is at six.")


class StrayTagTestCase(unittest.TestCase):
    def test_a_tag_the_model_opened_with_is_not_read_aloud(self):
        from simorgh.voice.planner import speakable
        self.assertEqual(speakable("[ciallo_05] Go ahead, you'd like me to what?")[0], "Go ahead, you'd like me to what?")
        self.assertEqual(speakable("[1] is a citation")[0].startswith("is a citation"), True)
        self.assertEqual(speakable("[warm bright] two words is not a tag")[0], "[warm bright] two words is not a tag")


class EnginesAndMarksTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_an_engine_that_reads_letters_gets_the_respelling(self):
        from simorgh.voice.api import TtsRequest
        from simorgh.voice.fakes import FakeSynthesiser
        from simorgh.voice.tts.streaming import StreamingSynthesiser

        fake = FakeSynthesiser()
        streaming = StreamingSynthesiser(fake)
        request = TtsRequest(request_id="r", pieces=(("Hello ⟦Saeed|sæˈiːd⟧.", 0),))
        _ = [c async for c in streaming.synthesise_stream(request)]
        self.assertEqual(fake.spoken, ["Hello sa-eed."])

    async def test_an_engine_that_speaks_ipa_gets_the_mark(self):
        from simorgh.voice.api import TtsRequest
        from simorgh.voice.fakes import FakeSynthesiser
        from simorgh.voice.tts.lanes import LaneSynthesiser
        from simorgh.voice.tts.streaming import StreamingSynthesiser
        from simorgh.voice.config import Config

        class _Ipa(FakeSynthesiser):
            speaks_ipa = True

        ipa, letters = _Ipa(), FakeSynthesiser()
        streaming = StreamingSynthesiser(LaneSynthesiser(ipa, letters, Config()))
        for lane in ("fast", "expressive"):
            request = TtsRequest(request_id=lane, pieces=(("Hi ⟦Saeed|sæˈiːd⟧.", 0),), lane=lane)
            _ = [c async for c in streaming.synthesise_stream(request)]
        self.assertEqual(ipa.spoken, ["Hi ⟦Saeed|sæˈiːd⟧."])
        self.assertEqual(letters.spoken, ["Hi sa-eed."])
