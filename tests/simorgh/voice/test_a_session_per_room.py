"""Stage 13 item 1: a voice session per room.

The laptop's session and a satellite's run at the same time on one
Pipeline and one set of engines. What each keeps to itself is the room:
its speaker, its speech lock, what it last said. A question asked in the
kitchen is answered in the kitchen, is recorded as the kitchen's, and
does not make the study think Sim is talking.
"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import Pipeline, Room
from simorgh.voice.session import VoiceSession
from simorgh.voice.turns import LISTENING
from tests.simorgh.voice.test_session import _Bus, _Script, _config


class _Asked:
    """Sim, answering each ask with which room asked it."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    async def ask(self, text, *, session_id=None, device: str = "", **kw) -> str:
        self.asked.append((device, text))
        return f"answered in the {device or 'default'}"


def _two_rooms():
    bus = _Bus()
    config = _config()
    stt = FakeRecogniser("what time is it", 0.95)
    tts = FakeSynthesiser()
    laptop_mic, kitchen_mic = FakeMicrophone(silence(0.03)), FakeMicrophone(silence(0.03))
    laptop_spk, kitchen_spk = FakeSpeaker(), FakeSpeaker()
    laptop_script = _Script((True, 20), (False, 10_000))
    kitchen_script = _Script((True, 20), (False, 10_000))
    scripts = iter([laptop_script, kitchen_script])
    pipeline = Pipeline(bus=bus, clock=None, logger=None, ledger=None, config=config, microphone=laptop_mic,
                        speaker=laptop_spk, recogniser=stt, synthesiser=tts, detector_factory=lambda: next(scripts))
    sim = _Asked()
    pipeline.ask = sim.ask  # type: ignore[method-assign]
    laptop = VoiceSession(pipeline=pipeline, config=config, microphone=laptop_mic, speaker=laptop_spk,
                          recogniser=stt, synthesiser=tts, detector_factory=pipeline._detector_factory)
    kitchen = VoiceSession(pipeline=pipeline, config=replace(config, device="kitchen"), microphone=kitchen_mic,
                           speaker=kitchen_spk, recogniser=stt, synthesiser=tts,
                           detector_factory=pipeline._detector_factory, room=Room("kitchen"))
    return pipeline, bus, sim, (laptop, laptop_spk), (kitchen, kitchen_spk)


async def _run_both(laptop: VoiceSession, kitchen: VoiceSession, done, timeout: float = 10.0) -> None:
    stop = asyncio.Event()
    tasks = [asyncio.create_task(laptop.run(stop)), asyncio.create_task(kitchen.run(stop))]
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while not done():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"timed out: laptop {laptop.stats.turns} turns, kitchen {kitchen.stats.turns}")
            await asyncio.sleep(0.01)
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class TwoRoomsAtOnce(unittest.IsolatedAsyncioTestCase):
    async def test_each_room_is_answered_through_its_own_speaker_and_named_as_itself(self):
        pipeline, bus, sim, (laptop, laptop_spk), (kitchen, kitchen_spk) = _two_rooms()
        await _run_both(laptop, kitchen, lambda: laptop.stats.turns >= 1 and kitchen.stats.turns >= 1)
        self.assertEqual(sorted(d for d, _t in sim.asked), ["kitchen", "laptop"],
                         "the ask carries the room it came from")
        self.assertTrue(laptop_spk.played, "the laptop's answer played on the laptop")
        self.assertTrue(kitchen_spk.played, "the kitchen's answer played in the kitchen")
        spoken = {p["device"] for p in bus.of(topics.VOICE_SPOKEN)}
        self.assertEqual(spoken, {"laptop", "kitchen"}, "each reply is recorded under its own room")

    async def test_the_kitchen_speaking_does_not_make_the_laptop_think_sim_is_talking(self):
        pipeline, _bus, _sim, (laptop, _ls), (kitchen, _ks) = _two_rooms()
        kitchen._voice_room.speaking = True  # noqa: SLF001
        kitchen._voice_room.last_said = "the kitchen's own words"  # noqa: SLF001
        self.assertFalse(pipeline.speaking, "the laptop's room is the pipeline's, untouched")
        self.assertEqual(pipeline.last_said, "")
        self.assertFalse(laptop._voice_room.speech_lock.locked())  # noqa: SLF001
        async with kitchen._voice_room.speech_lock:  # noqa: SLF001
            self.assertFalse(pipeline.speech_lock.locked(), "one room speaking does not hold the other's floor")

    async def test_both_rooms_hear_that_a_slow_tool_started(self):
        """One slot for the handler would let the second session unhook
        the first; the rooms add theirs to a list instead."""
        pipeline, _bus, _sim, (laptop, _ls), (kitchen, _ks) = _two_rooms()
        heard: list[str] = []

        async def _laptop(tool, p95):
            heard.append(f"laptop:{tool}")

        async def _kitchen(tool, p95):
            heard.append(f"kitchen:{tool}")

        pipeline.on_tool_started = _laptop
        pipeline.tool_started_handlers.append(_kitchen)

        class _Message:
            payload = {"name": "web_fetch", "recent_p95_ms": 6000}

        await pipeline._on_tool_started(_Message())  # noqa: SLF001
        self.assertEqual(heard, ["laptop:web_fetch", "kitchen:web_fetch"])

    async def test_a_room_session_registers_and_leaves_without_touching_the_laptops_slot(self):
        pipeline, _bus, _sim, (laptop, _ls), (kitchen, _ks) = _two_rooms()
        stop = asyncio.Event()
        task = asyncio.create_task(kitchen.run(stop))
        for _ in range(100):
            if kitchen.state == LISTENING:
                break
            await asyncio.sleep(0.01)
        self.assertIsNone(pipeline.on_tool_started, "the laptop's slot is left alone")
        self.assertEqual(len(pipeline.tool_started_handlers), 1)
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(pipeline.tool_started_handlers, [], "a stopped room leaves nothing behind")


class TheServiceHoldsTheRooms(unittest.IsolatedAsyncioTestCase):
    async def _service(self):
        from simorgh.voice.config import Config
        from simorgh.voice.service import Service

        config = Config(stt="fake", tts="fake", microphone="fake", speaker="fake", speaker_id="off",
                        stt_partials=False, backchannel=False, enabled=False)
        service = Service(config, microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker(),
                          recogniser=FakeRecogniser(), synthesiser=FakeSynthesiser())

        class _Ctx:
            bus = _Bus()
            clock = None
            ledger = None
            config = {}

            class logger:
                @staticmethod
                def info(*a, **k): pass
                @staticmethod
                def warning(*a, **k): pass
                @staticmethod
                def error(*a, **k): pass
                @staticmethod
                def debug(*a, **k): pass

        service._ctx = _Ctx()
        return service

    async def test_a_room_is_added_under_its_own_name_and_refused_twice(self):
        service = await self._service()
        room = await service.add_room("kitchen", microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker())
        self.assertEqual(room._config.device, "kitchen")  # noqa: SLF001
        self.assertIsNot(room._voice_room, service._pipeline, "a room gets its own Room")  # noqa: SLF001
        with self.assertRaises(ValueError):
            await service.add_room("kitchen", microphone=FakeMicrophone(), speaker=FakeSpeaker())
        with self.assertRaises(ValueError):
            await service.add_room(service.config.device, microphone=FakeMicrophone(), speaker=FakeSpeaker())
        self.assertIn("kitchen", service._state()["rooms"])  # noqa: SLF001

    async def test_voice_on_starts_the_rooms_and_voice_off_stops_them(self):
        service = await self._service()
        await service.add_room("kitchen", microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker())
        self.assertFalse(service._state()["rooms"]["kitchen"]["running"], "nothing listens while voice is off")  # noqa: SLF001
        ok, why = await service._turn_on()  # noqa: SLF001
        self.assertTrue(ok, why)
        await asyncio.sleep(0.05)
        self.assertTrue(service._state()["rooms"]["kitchen"]["running"])  # noqa: SLF001
        await service._turn_off()  # noqa: SLF001
        self.assertFalse(service._state()["rooms"]["kitchen"]["running"], "`voice off` silences every room")  # noqa: SLF001
        await service.remove_room("kitchen")
        self.assertNotIn("rooms", service._state())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()


class MutingOneRoom(unittest.IsolatedAsyncioTestCase):
    """Live 2026-09-27: with the satellite beside the Mac both sessions
    answered, and `voice mute` -- the only mute there was -- silenced the
    satellite as well. `voice mute <room>` mutes that room alone."""

    async def test_muting_the_laptop_leaves_the_room_listening_and_back(self):
        service = await TheServiceHoldsTheRooms._service(self)
        room = await service.add_room("kitchen", microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker())
        ok, why = await service._turn_on()  # noqa: SLF001
        self.assertTrue(ok, why)
        self.addAsyncCleanup(service._turn_off)  # noqa: SLF001
        ok, detail = service._mute_one("laptop", True)  # noqa: SLF001
        self.assertTrue(ok, detail)
        self.assertTrue(service._session.muted)  # noqa: SLF001
        self.assertFalse(room.muted, "the kitchen still listens")
        self.assertIn("other rooms still listen", detail)
        ok, _d = service._mute_one("KITCHEN", True)  # noqa: SLF001
        self.assertTrue(ok and room.muted, "a room is named without caring about case")
        service._mute_one("laptop", False)  # noqa: SLF001
        self.assertFalse(service._session.muted)  # noqa: SLF001

    async def test_an_unknown_room_is_named_with_the_ones_there_are(self):
        service = await TheServiceHoldsTheRooms._service(self)
        await service.add_room("kitchen", microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker())
        ok, detail = service._mute_one("garage", True)  # noqa: SLF001
        self.assertFalse(ok)
        self.assertIn("kitchen", detail)


class OneQuestionOneAnswer(unittest.IsolatedAsyncioTestCase):
    """Live 2026-09-27: with the board beside the Mac, both the laptop and
    the room answered "what time is it". While a room's wake run is open,
    the laptop leaves that speech to the room."""

    async def test_the_laptop_defers_while_a_room_is_woken_and_answers_otherwise(self):
        pipeline, bus, sim, (laptop, _ls), (kitchen, _ks) = _two_rooms()
        woken = {"now": True}
        laptop.defer = lambda: woken["now"]
        await _run_both(laptop, kitchen, lambda: kitchen.stats.turns >= 1 and bus.of(topics.VOICE_SPOKEN), timeout=10.0)
        await asyncio.sleep(0.3)
        asked_by = [d for d, _t in sim.asked]
        self.assertNotIn("laptop", asked_by, "the laptop deferred to the woken room")
        self.assertIn("kitchen", asked_by)
        quiet = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("device") == "laptop" and p.get("quiet")]
        self.assertTrue(any("room satellite" in (p.get("reason") or "") for p in quiet), quiet)
