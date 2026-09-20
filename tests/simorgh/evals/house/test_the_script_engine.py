"""Stage 11 item 4: a scenario, and what it may expect.

The expectations are pure functions of the record, so they are tested
against a record built by hand -- which is also the clearest statement
of what each one means. The two integration cases at the bottom prove
the two paths a beat can take: asking Sim, and making a sound in the
room and letting Sim decide.
"""

import unittest

import pytest

from simorgh.contracts.envelope import Message
from simorgh.evals.house.record import Record
from simorgh.evals.house.script import (
    Beat, Scenario, answered, asked_a_person, called, did_not_call, first_audio_under,
    identified_as, quiet, remembered, said_something_like, tui_is_sane, was_denied,
)


def _record(**parts) -> tuple[Record, float]:
    import time

    record, since = Record(), time.monotonic()
    for topic, payload in parts.pop("messages", []):
        record.saw(Message.new(topic, source="test", payload=payload))
    for text in parts.pop("said", []):
        record.sim_spoke(text)
    for text in parts.pop("printed", []):
        record.printed_line(text)
    return record, since


class WhatAHouseholdMemberWouldNotice(unittest.TestCase):
    def test_answered_and_quiet_are_opposites(self):
        spoke, since = _record(said=["Yes?"])
        silent, _ = _record()
        self.assertEqual(answered().check(spoke, since), "")
        self.assertNotEqual(answered().check(silent, since), "")
        self.assertEqual(quiet().check(silent, since), "")
        self.assertIn("Yes?", quiet().check(spoke, since))

    def test_identified_as_says_who_it_heard_instead(self):
        record, since = _record(messages=[("percept.text.received", {"speaker": "Devin", "text": "hi"})])
        self.assertEqual(identified_as("Devin").check(record, since), "")
        self.assertIn("Devin", identified_as("Mara").check(record, since))

    def test_nothing_heard_is_not_a_misidentification(self):
        record, since = _record()
        self.assertIn("nothing reached Sim", identified_as("Mara").check(record, since))

    def test_did_not_call_quotes_the_arguments_when_it_fails(self):
        record, since = _record(messages=[("action.proposed", {"tool": "home_call", "args": {"service": "lock.unlock"}})])
        self.assertEqual(did_not_call("notify").check(record, since), "")
        self.assertIn("lock.unlock", did_not_call("home_call").check(record, since))

    def test_called_lists_what_was_proposed_instead(self):
        record, since = _record(messages=[("action.proposed", {"tool": "notify"})])
        self.assertEqual(called("notify").check(record, since), "")
        self.assertIn("notify", called("speak").check(record, since))

    def test_asked_a_person_accepts_either_way_of_asking(self):
        for topic in ("action.needs_human", "ui.prompt"):
            record, since = _record(messages=[(topic, {"action_id": "a1"})])
            self.assertEqual(asked_a_person().check(record, since), "", topic)

    def test_was_denied_can_name_the_layer(self):
        record, since = _record(messages=[("action.denied", {"layer": "protected"})])
        self.assertEqual(was_denied().check(record, since), "")
        self.assertEqual(was_denied("protected").check(record, since), "")
        self.assertIn("protected", was_denied("tier").check(record, since))

    def test_a_budget_reports_what_it_actually_took(self):
        record, since = _record(said=["here you are"])
        self.assertEqual(first_audio_under(60.0).check(record, since), "")
        self.assertIn("budget", first_audio_under(0.0).check(record, since))

    def test_nothing_said_fails_a_budget_as_silence_not_as_slowness(self):
        record, since = _record()
        self.assertIn("nothing was said", first_audio_under(1.0).check(record, since))

    def test_remembered_reads_the_prompt_the_model_would_have_seen(self):
        record, since = _record(messages=[("cognition.think",
                                           {"messages": [{"role": "user", "content": "birthday is March 6th"}]})])
        self.assertEqual(remembered("March 6").check(record, since), "")
        self.assertIn("March 4", remembered("March 4").check(record, since))

    def test_said_something_like_is_a_rubric_not_a_transcript(self):
        record, since = _record(said=["It is a quarter past four, Mara."])
        self.assertEqual(said_something_like("quarter past").check(record, since), "")
        self.assertIn("never said", said_something_like("half past").check(record, since))

    def test_the_terminal_grammar_catches_what_must_never_show(self):
        for bad in ("Traceback (most recent call last):", "Loading weights: 100%|##| 103/103 [00:00<00:00, 28it/s]"):
            record, since = _record(printed=[bad])
            self.assertNotEqual(tui_is_sane().check(record, since), "", bad)
        good, since = _record(printed=["  🎤 listening...", "● Yes?"])
        self.assertEqual(tui_is_sane().check(good, since), "")

    def test_an_expectation_that_raises_is_skipped_not_failed(self):
        from simorgh.evals.house.script import Expectation

        def _broken(_record, _since):
            raise ValueError("bad expectation")

        outcome = Expectation("broken", _broken).judge(Record(), 0.0)
        self.assertEqual(outcome.status, "skipped")
        self.assertIn("the expectation itself raised", outcome.why)


class AScenarioReadsLikeAnEvening(unittest.TestCase):
    def test_a_beat_describes_itself_for_the_failure_message(self):
        self.assertEqual(Beat(who="Mara", says="hello").describe(), "Mara: hello")
        self.assertEqual(Beat(says="status").describe(), "the console: status")
        self.assertEqual(Beat(restart=True).describe(), "Sim is restarted")
        self.assertIn("the house", Beat(device={"key": "camera.x"}).describe())

    def test_the_case_count_is_every_expectation(self):
        scenario = Scenario(id="x", beats=(Beat(who="A", says="1", expect=(answered(), quiet())),
                                           Beat(who="B", says="2", expect=(answered(),))),
                            expect=(tui_is_sane(),))
        self.assertEqual(scenario.cases(), 4)


class TheLivePack(unittest.TestCase):
    """The evenings that actually went wrong."""

    def test_every_one_says_why_it_exists(self):
        from simorgh.evals.house.scenarios import all_scenarios

        for scenario in all_scenarios():
            self.assertTrue(scenario.because, f"{scenario.id} does not say what it is about")
            self.assertTrue(scenario.stage, f"{scenario.id} belongs to no stage")
            self.assertGreater(scenario.cases(), 0, f"{scenario.id} expects nothing")

    def test_every_live_failure_is_still_in_the_pack(self):
        """One per evening that went wrong, and the list only grows.

        A count rather than a list because the point is that nobody
        quietly drops one: a scenario written from a real failure is
        the only kind that is certainly worth keeping. Six since
        2026-09-20, when the simulator found the echo bar going to
        infinity in a quiet room (`live/a-whole-conversation`).
        """
        from simorgh.evals.house.scenarios import all_scenarios

        live = [s for s in all_scenarios() if s.id.startswith("live/")]
        self.assertGreaterEqual(len(live), 6, f"a live scenario went missing: {[s.id for s in live]}")


@pytest.mark.integration
class BothWaysOfSpeaking(unittest.IsolatedAsyncioTestCase):
    """`say` asks Sim; `into_the_room` makes a sound and lets Sim
    decide. The second is the only one that can test what Sim ignores,
    because the deciding happens in the listening loop."""

    async def asyncSetUp(self):
        from simorgh.evals.house import Director, Sandbox

        self.box = await Sandbox().start()
        self.director = Director(self.box)

    async def asyncTearDown(self):
        await self.box.stop()

    async def test_asking_sim_always_gets_an_answer(self):
        mark = await self.director.say("Mara", "Sim, are you there?")
        self.assertTrue(self.director.record.said_since(mark))

    async def _enrol(self):
        from simorgh.evals.house.people import enrol

        session = self.box.service("voice")._session  # noqa: SLF001
        if session is None or session._speakers is None or session._embedder is None:  # noqa: SLF001
            self.skipTest("no speaker book in this sandbox")
        await enrol(session._speakers, self.director._tts(), session._embedder)  # noqa: SLF001

    async def test_a_named_address_is_answered(self):
        await self._enrol()
        named = await self.director.into_the_room("Mara", "Sim, are you there?")
        self.assertTrue(self.director.record.said_since(named), "a named address went unanswered")

    async def test_an_aside_from_a_placed_voice_is_the_models_call(self):
        """Who decides an aside is not for Sim, and when.

        There are two gates and only one of them is deterministic. A
        voice Sim cannot place must NAME Sim (`session._unplaced`);
        a voice it can place goes to the model, which answers QUIET if
        the words were not for it (`backchannel.is_quiet`). So with the
        floor provider -- which answers everything -- a placed aside is
        answered, and that is Sim working as designed.

        This was worth finding: an earlier version of this test passed,
        and passed for the wrong reason. Identification was broken at
        the time (the 24 kHz microphone), every persona was unplaced,
        and the aside was refused by the gate for strangers rather than
        recognised as an aside. Fixing identification made the test
        fail, which is the test finally measuring what it claimed to.
        """
        await self._enrol()
        aside = await self.director.into_the_room("Mara", "Can you try a bit harder next time, honey.")
        percept = self.director.record.first("percept.text.received", since=aside)
        self.assertIsNotNone(percept, "the words never reached Sim")
        self.assertEqual(percept.payload.get("speaker"), "Mara",
                         "a placed voice is the case this test is about")

    async def test_a_voice_sim_cannot_place_must_name_it(self):
        """The deterministic half, which needs no model: a voice Sim
        cannot place, saying something that does not name it.

        The household is enrolled WITHOUT Priya on purpose. With an
        empty book the rule turns itself off -- "nobody is enrolled, so
        nobody can ever be placed: the rule would silence the whole
        house" -- and the first version of this test enrolled nobody
        and was therefore measuring nothing.
        """
        from simorgh.evals.house.people import by_name, enrol

        session = self.box.service("voice")._session  # noqa: SLF001
        if session is None or session._speakers is None or session._embedder is None:  # noqa: SLF001
            self.skipTest("no speaker book in this sandbox")
        known = tuple(p for p in (by_name("Mara"), by_name("Devin")) if p)
        await enrol(session._speakers, self.director._tts(), session._embedder, known)  # noqa: SLF001

        stranger = await self.director.into_the_room("Priya", "No, I told you it was on Tuesday.")
        self.assertFalse(self.director.record.said_since(stranger),
                         "an unplaced voice that did not name Sim was answered")


if __name__ == "__main__":
    unittest.main()


class TheSandboxDoesNotTouchTheHouse(unittest.TestCase):
    """What it must never do, pinned.

    The speaker book was the leak that got through: the sandbox is
    careful about `~/.simorgh` and the book lives under `workspace/`,
    so for a day the simulator read the creator's real voices and
    WROTE five synthetic personas among his family (2026-09-20). A
    scenario was then judged against voices no scenario enrolled.
    """

    def test_the_defaults_do_not_name_the_live_speaker_book(self):
        from simorgh.evals.house.sandbox import DEFAULT_CONFIG

        self.assertNotIn("speakers_dir", DEFAULT_CONFIG["voice"],
                         "the folder is per sandbox, set in start() from its own data dir")

    def test_a_started_sandbox_keeps_its_voices_inside_itself(self):
        import asyncio

        async def _check():
            from simorgh.evals.house import Sandbox

            async with Sandbox() as box:
                voice = box.service("voice")
                return str(voice.config.speakers_dir), str(box.data_dir)

        folder, data_dir = asyncio.run(_check())
        self.assertTrue(folder.startswith(data_dir),
                        f"the speaker book is at {folder}, outside the sandbox at {data_dir}")
        self.assertNotIn("workspace/voice/speakers", folder)
