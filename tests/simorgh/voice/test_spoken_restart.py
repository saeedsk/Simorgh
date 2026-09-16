""""Restart" said aloud restarts Sim (the creator, by voice, 2026-09-15).

Only for a voice the house knows -- an advert saying it must not take Sim
down -- and never when nothing would bring Sim back up."""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.voice.commands import MUTE, OFF, RESTART, STOP, spoken_command


class TheWords(unittest.TestCase):
    def test_restart_is_a_command(self):
        for text in ("restart", "Restart.", "Sim, restart yourself", "hey sim reboot", "restart please"):
            self.assertEqual(spoken_command(text), RESTART, text)

    def test_ordinary_talk_is_not(self):
        for text in ("restart the router", "did you restart the dishwasher", "I restarted it"):
            self.assertIsNone(spoken_command(text), text)

    def test_the_other_commands_still_work(self):
        self.assertEqual(spoken_command("stop"), STOP)
        self.assertEqual(spoken_command("voice off"), OFF)
        self.assertEqual(spoken_command("mute"), MUTE)


class TheRestart(unittest.IsolatedAsyncioTestCase):
    def _session(self):
        from simorgh.voice.session import VoiceSession

        session = VoiceSession.__new__(VoiceSession)
        session._now = lambda: 100.0                                   # noqa: SLF001
        session._clocks = {}                                           # noqa: SLF001
        session._log = lambda *a, **k: None                            # noqa: SLF001
        session.published: list[tuple[str, dict]] = []                  # noqa: SLF001
        session.spoken: list[str] = []                                  # noqa: SLF001

        class _Pipeline:
            async def _publish(self_inner, topic, payload):             # noqa: N805
                session.published.append((topic, payload))
        session._pipeline = _Pipeline()                                # noqa: SLF001

        async def _speak(turn_id, reply, clock, context):
            session.spoken.append(reply)
        session._speak_reply = _speak                                  # noqa: SLF001
        return session

    async def test_a_known_voice_restarts_sim(self):
        session = self._session()
        with mock.patch.dict("os.environ", {"SIMORGH_LOADER_NOTES": "/tmp/notes"}):
            await session._restart(1, speaker="Saeed")                 # noqa: SLF001
        self.assertEqual(session.spoken, ["Restarting now."])
        self.assertEqual([t for t, _ in session.published], [topics.SYSTEM_RESTART])
        self.assertIn("Saeed", session.published[0][1]["reason"])
        self.assertTrue(session.published[0][1]["self_check_passed"])

    async def test_a_voice_sim_cannot_place_is_refused(self):
        session = self._session()
        with mock.patch.dict("os.environ", {"SIMORGH_LOADER_NOTES": "/tmp/notes"}):
            await session._restart(1, speaker="")                      # noqa: SLF001
        self.assertEqual(session.published, [])
        self.assertIn("only for a voice I know", session.spoken[0])

    async def test_nothing_would_bring_sim_back(self):
        session = self._session()
        with mock.patch.dict("os.environ", {}, clear=True):
            await session._restart(1, speaker="Saeed")                 # noqa: SLF001
        self.assertEqual(session.published, [])
        self.assertIn("sim.sh", session.spoken[0])


if __name__ == "__main__":
    unittest.main()
