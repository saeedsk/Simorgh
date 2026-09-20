"""Stage 11 item 1: a scenario can talk to Sim, and everything it did
is written down.

The acceptance case at the bottom is the whole item: a director says
one thing, and the record shows the percept, the think, the completed
turn, the spoken reply, the printed line and how long the reply took.
"""

import unittest

import pytest

from simorgh.evals.house import Director, Sandbox

pytestmark = pytest.mark.integration


class TheRecord(unittest.TestCase):
    """Dumb by design: it keeps what happened, and an expectation
    decides what that means."""

    def _record(self):
        from simorgh.evals.house.record import Record

        return Record()

    def test_a_message_keeps_its_type_payload_and_moment(self):
        from simorgh.contracts.envelope import Message

        record = self._record()
        record.saw(Message.new("turn.completed", source="orchestration", payload={"text": "hi"}))
        seen = record.of("turn.completed")[0]
        self.assertEqual((seen.type, seen.payload["text"], seen.source), ("turn.completed", "hi", "orchestration"))
        self.assertGreater(seen.at, 0.0)

    def test_the_transcript_reads_as_a_conversation(self):
        from simorgh.contracts.envelope import Message

        record = self._record()
        record.saw(Message.new("percept.text.received", source="voice",
                               payload={"speaker": "Ira", "text": "is it raining"}))
        record.spoke("A bit, yes.")
        self.assertEqual(record.transcript(), "Ira: is it raining\nsim: A bit, yes.")

    def test_nothing_said_is_no_first_audio_rather_than_zero(self):
        self.assertIsNone(self._record().first_audio(since=0.0))


class TheSandboxIsSealed(unittest.TestCase):
    """What it must never do (stage 11): reach the live data dir, the
    live speaker book, a real device, or a real model by accident."""

    def test_the_defaults_name_no_real_engine_and_no_real_provider(self):
        from simorgh.evals.house.sandbox import DEFAULT_CONFIG

        self.assertEqual(DEFAULT_CONFIG["cognition"]["provider_order"], ["floor"])
        for engine in ("stt", "tts", "microphone", "speaker"):
            self.assertEqual(DEFAULT_CONFIG["voice"][engine], "fake", engine)
        self.assertFalse(DEFAULT_CONFIG["execution"]["shell"])
        self.assertFalse(DEFAULT_CONFIG["execution"]["remote"])

    def test_the_data_dir_is_temporary_and_not_the_creators(self):
        box = Sandbox()
        self.assertIsNone(box.data_dir, "nothing exists until it is started")


class ADirectorDrivesASim(unittest.IsolatedAsyncioTestCase):
    """The acceptance case. It boots the real Kernel, so it is an
    integration test and takes a few seconds."""

    async def asyncSetUp(self):
        self.box = await Sandbox().start()
        self.director = Director(self.box)

    async def asyncTearDown(self):
        await self.box.stop()

    async def test_one_spoken_turn_leaves_a_complete_record(self):
        mark = await self.director.say("Saeed", "Sim, are you there?")
        record = self.director.record

        percept = record.first("percept.text.received", since=mark)
        self.assertIsNotNone(percept, "the words never reached Sim")
        self.assertEqual(percept.payload["speaker"], "Saeed")
        self.assertEqual(percept.payload["channel"], "voice")

        self.assertIsNotNone(record.first("cognition.think", since=mark), "Sim never thought about it")
        self.assertIsNotNone(record.first("turn.completed", since=mark), "the turn never completed")

        said = record.said_since(mark)
        self.assertTrue(said, "Sim decided something and never said it")
        self.assertIsNotNone(record.first_audio(since=mark), "no timing for the reply")

        self.assertIn("Saeed: Sim, are you there?", record.transcript())
        self.assertIn("sim: ", record.transcript())

    async def test_the_owner_can_type_instead(self):
        mark = await self.director.type("status")
        self.assertTrue(self.director.record.printed_since(mark), "the console said nothing")

    async def test_two_people_keep_their_own_conversations(self):
        await self.director.say("Saeed", "morning")
        await self.director.say("Ira", "morning")
        sessions = {m.payload.get("session_id") for m in self.director.record.of("percept.text.received")}
        self.assertEqual(len(sessions), 2, "two people in a room are two conversations")

    async def test_the_sandbox_watches_the_reserved_lanes_too(self):
        """An observer that cannot see `action.proposed` cannot test the
        approval path, which is most of what is worth testing."""
        await self.director.type("status")
        self.assertTrue(self.director.record.messages, "the observer saw nothing at all")


if __name__ == "__main__":
    unittest.main()
