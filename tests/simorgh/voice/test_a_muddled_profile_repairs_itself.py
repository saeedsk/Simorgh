"""A voice profile with two voices in it repairs itself.

The creator, 2026-09-27, after `voice people` flagged Iris and Saeed and
`voice relearn Saeed` took his profile from 0.65 to 0.83: "I'd like sim
to auto relearn when this kind of issue happens (when it detects there
[are] two voices in the learning)". Voice checks every hour; a profile
under `MUDDLED_BELOW` is tidied, then relearnt, once a day per person,
and the console is told what happened.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest

from simorgh.voice.config import Config
from simorgh.voice.service import Service
from simorgh.voice.speakers import MUDDLED_BELOW, SpeakerBook, coherence


def _vec(*head: float) -> list[float]:
    return [*head] + [0.0] * (8 - len(head))


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    def new(self, topic, payload):
        return (topic, payload)

    async def publish(self, message):
        self.published.append(message)


class _Logger:
    def info(self, *a, **k):
        pass

    warning = info


class _Ctx:
    def __init__(self) -> None:
        self.bus, self.logger = _Bus(), _Logger()


class AMuddledProfileRepairsItself(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        book = SpeakerBook(self.dir)
        # Three enrolment takes of one voice, then learnt takes of another.
        takes = [_vec(1.0, 0.1), _vec(1.0, 0.0, 0.1), _vec(1.0, 0.05, 0.05)] + [_vec(0.0, 0.0, 0.0, 1.0)] * 4
        book.enroll("Iris", takes[0])
        person = book._people["iris"]                                   # noqa: SLF001
        person.embeddings = list(takes)
        book._save(person)                                               # noqa: SLF001
        self.assertLess(coherence(self._takes()), MUDDLED_BELOW)  # noqa: SLF001
        self.svc = Service(Config(speakers_dir=self.dir, audio_dir=self.dir + "/none"))
        self.svc._ctx = _Ctx()                                           # noqa: SLF001

    def _takes(self) -> list:
        return next(p.embeddings for p in SpeakerBook(self.dir).people() if p.name == "Iris")

    async def test_it_is_tidied_and_the_console_is_told(self):
        said = await self.svc.auto_repair(now=1_000_000.0)
        self.assertEqual(len(said), 1)
        self.assertIn("Iris's voice profile had more than one voice in it", said[0])
        self.assertRegex(said[0], r"dropped \d take\(s\)")
        self.assertGreaterEqual(coherence(self._takes()), MUDDLED_BELOW)  # noqa: SLF001
        topic, payload = self.svc._ctx.bus.published[0]                  # noqa: SLF001
        self.assertEqual((topic, payload["source"]), ("ui.notice", "voice relearn"))

    async def test_once_a_day_per_person_not_every_hour(self):
        self.svc._repaired_at["Iris"] = 1_000_000.0                      # noqa: SLF001
        self.assertEqual(await self.svc.auto_repair(now=1_000_000.0 + 3600), [])
        self.assertEqual(len(await self.svc.auto_repair(now=1_000_000.0 + 86400)), 1)

    async def test_not_while_a_calibration_is_being_recorded(self):
        class _Session:
            _calibrating = object()
            _speakers = None

        self.svc._session = _Session()                                   # noqa: SLF001
        self.assertEqual(await self.svc.auto_repair(now=1_000_000.0), [])

    async def test_a_healthy_house_is_left_alone(self):
        await self.svc.auto_repair(now=1_000_000.0)
        self.svc._ctx.bus.published.clear()                              # noqa: SLF001
        self.assertEqual(await self.svc.auto_repair(now=1_000_000.0 + 2 * 86400), [])
        self.assertEqual(self.svc._ctx.bus.published, [])                # noqa: SLF001

    async def test_a_typed_relearn_tidies_a_muddled_profile_first(self):
        _ok, said = await self.svc._people_action("relearn", {"name": "Iris"})   # noqa: SLF001
        # No kept recordings here, so the relearn half has nothing to add;
        # the tidy is what mends it.
        self.assertRegex(said, r"^first dropped \d take\(s\) pulling it apart")
        self.assertGreaterEqual(coherence(self._takes()), MUDDLED_BELOW)

    def test_the_setting_is_on_by_default(self):
        self.assertTrue(Config().auto_relearn)


class TheLaptopMutesWhenASatelliteConnects(unittest.IsolatedAsyncioTestCase):
    """The creator, 2026-09-27: "make `voice mute laptop` whenever satellite
    voice is being detected at startup". Once per start: a board that
    reconnects must not undo the person's `unmute`."""

    def _service(self, **config):
        class _Session:
            muted = False

        svc = Service(Config(**config))
        svc._ctx = _Ctx()                                                 # noqa: SLF001
        svc._session = _Session()                                         # noqa: SLF001
        return svc

    async def test_the_first_board_up_mutes_the_laptop_and_says_so(self):
        svc = self._service()
        await svc._satellite_connected("sim-room-1")                      # noqa: SLF001
        self.assertTrue(svc._session.muted)                               # noqa: SLF001
        topic, payload = svc._ctx.bus.published[0]                        # noqa: SLF001
        self.assertIn("laptop muted: sim-room-1 is listening", payload["text"])
        self.assertIn("`unmute`", payload["text"])

    async def test_a_reconnect_does_not_undo_an_unmute(self):
        svc = self._service()
        await svc._satellite_connected("sim-room-1")                      # noqa: SLF001
        svc._session.muted = False                                        # noqa: SLF001 -- the person typed `unmute`
        await svc._satellite_connected("sim-room-1")                      # noqa: SLF001
        self.assertFalse(svc._session.muted)                              # noqa: SLF001

    async def test_it_can_be_turned_off(self):
        svc = self._service(mute_laptop_with_satellite=False)
        await svc._satellite_connected("sim-room-1")                      # noqa: SLF001
        self.assertFalse(svc._session.muted)                              # noqa: SLF001
