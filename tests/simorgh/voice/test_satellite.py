"""Stage 13 item 2: an ESPHome satellite as a microphone and a speaker,
against a fake API client -- no board on the network.

Every rule here was measured on the creator's reSpeaker XVF3800
(2026-09-25/26): the run-end race, one client per board, FLAC-by-URL
replies, and playback state that lags the audio.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest import mock

from simorgh.voice import satellite as sat
from simorgh.voice.api import Audio
from simorgh.voice.fakes import silence
from simorgh.voice.remote import FRAME_BYTES


class _Names:
    """`aioesphomeapi`'s enums, as the names the link asks for."""

    def __getattr__(self, name: str) -> str:
        return name


class _Api:
    VoiceAssistantEventType = _Names()

    class MediaPlayerCommand:
        STOP = "STOP"


class MediaPlayerInfo:
    key = 7


class _Client:
    def __init__(self, *, refuse: str = "") -> None:
        self.events: list[tuple[str, dict | None, float]] = []
        self.media: list[dict] = []
        self.handlers: dict = {}
        self.refuse = refuse
        self.on_stop = None
        self.disconnected = 0

    async def connect(self, *, on_stop=None, login=True) -> None:
        if self.refuse:
            raise ConnectionError(self.refuse)
        self.on_stop = on_stop

    async def list_entities_services(self):
        return [MediaPlayerInfo()], []

    def subscribe_voice_assistant(self, **handlers):
        self.handlers = handlers
        return lambda: None

    def send_voice_assistant_event(self, kind, data) -> None:
        self.events.append((kind, data, asyncio.get_running_loop().time()))

    def media_player_command(self, key, **kw) -> None:
        self.media.append(dict(kw, key=key))

    async def disconnect(self) -> None:
        self.disconnected += 1

    async def send_voice_assistant_announcement_await_response(self, media_id, timeout, text="",
                                                                preannounce_media_id="", start_conversation=False):
        self.announcements = getattr(self, "announcements", [])
        self.announcements.append((media_id, start_conversation))

    def kinds(self) -> list[str]:
        return [k for k, _d, _t in self.events]


def _link(client: _Client | None = None, *, accepting=lambda: True, volume=None):
    client = client or _Client()
    published: list[Audio] = []

    async def publish(audio: Audio) -> str:
        published.append(audio)
        return f"http://sim.local:8765/api/room/speech?ref=r{len(published)}"

    link = sat.SatelliteLink("kitchen", "sim-room-1.local", "key", publish=publish, volume=volume,
                             client_factory=lambda host, port, key: (client, _Api()), accepting=accepting)
    return link, client, published


async def _connected(link: sat.SatelliteLink, client: _Client):
    stop = asyncio.Event()
    task = asyncio.create_task(link.run(stop))
    for _ in range(200):
        if link.connected:
            break
        await asyncio.sleep(0.005)
    assert link.connected, link.status
    return stop, task


async def _close(stop: asyncio.Event, task: asyncio.Task) -> None:
    stop.set()
    await asyncio.wait_for(task, 2)


class TheRunEndRace(unittest.IsolatedAsyncioTestCase):
    """RUN_END sent while the board is still stopping its microphone is
    ignored, and the board then turns every later wake word into a STOP
    (measured 2026-09-25). The link waits the gap out."""

    async def test_run_end_waits_the_gap_after_speech_ended_even_when_the_session_is_already_listening(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.2):
            await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
            link.microphone.on_state("thinking")
            link.microphone.on_state("listening")          # at once: nothing to say
            await asyncio.sleep(0.35)
        kinds = client.kinds()
        self.assertIn("VOICE_ASSISTANT_RUN_END", kinds)
        vad_end = next(t for k, _d, t in client.events if k == "VOICE_ASSISTANT_STT_VAD_END")
        run_end = next(t for k, _d, t in client.events if k == "VOICE_ASSISTANT_RUN_END")
        self.assertGreaterEqual(run_end - vad_end, 0.19, "never inside the gap the board needs")
        await _close(stop, task)

    async def test_five_wakes_in_a_row_each_start_and_end_a_run(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.01):
            for _ in range(5):
                port = await client.handlers["handle_start"]("c", 1, None, "okay_nabu")
                self.assertEqual(port, 0, "0: stream over this connection")
                link.microphone.on_state("thinking")
                link.microphone.on_state("listening")
                await asyncio.sleep(0.05)
        self.assertEqual(client.kinds().count("VOICE_ASSISTANT_RUN_START"), 5)
        self.assertEqual(client.kinds().count("VOICE_ASSISTANT_RUN_END"), 5)
        self.assertIsNone(link._run, "no run left open")  # noqa: SLF001
        await _close(stop, task)


class AReply(unittest.IsolatedAsyncioTestCase):
    async def test_the_first_piece_is_the_runs_answer_and_the_rest_are_announcements(self):
        link, client, published = _link()
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        link.microphone.on_state("thinking")
        with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            await link.speaker.play(silence(0.05))
            await link.speaker.play(silence(0.05))
        tts_end = [d for k, d, _t in client.events if k == "VOICE_ASSISTANT_TTS_END"]
        self.assertEqual(tts_end, [{"url": "http://sim.local:8765/api/room/speech?ref=r1"}])
        self.assertEqual([m.get("media_url") for m in client.media],
                         ["http://sim.local:8765/api/room/speech?ref=r2"])
        self.assertTrue(all(m.get("announcement") for m in client.media if "media_url" in m))
        await _close(stop, task)

    async def test_the_reply_lasts_as_long_as_its_audio_not_as_the_boards_state(self):
        """PLAYING/IDLE lag real playback by up to ~10 s on this board."""
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        loop = asyncio.get_running_loop()
        began = loop.time()
        with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            await link.speaker.play(silence(0.3))
        self.assertAlmostEqual(loop.time() - began, 0.3, delta=0.1)
        await _close(stop, task)

    async def test_the_board_stopping_the_reply_stops_the_time_being_kept(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        loop = asyncio.get_running_loop()
        began = loop.time()
        playing = asyncio.create_task(link.speaker.play(silence(5.0)))
        await asyncio.sleep(0.05)
        await client.handlers["handle_stop"](True)            # the wake word, mid-reply
        await asyncio.wait_for(playing, 1)
        self.assertLess(loop.time() - began, 1.0)
        await _close(stop, task)

    async def test_stopping_sim_stops_the_boards_player(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        await link.speaker.stop()
        self.assertIn({"command": "STOP", "key": 7}, client.media)
        await _close(stop, task)


class WhoMayHoldTheBoard(unittest.IsolatedAsyncioTestCase):
    async def test_a_wake_word_while_sim_is_not_listening_puts_the_board_back_to_idle(self):
        link, client, _p = _link(accepting=lambda: False)
        stop, task = await _connected(link, client)
        port = await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        self.assertIsNone(port)
        self.assertEqual(client.kinds(), ["VOICE_ASSISTANT_ERROR"])
        await _close(stop, task)

    async def test_a_second_client_on_the_board_is_named_not_fought(self):
        client = _Client(refuse="Multiple API Clients attempting to connect to Voice Assistant")
        link, _c, _p = _link(client)
        stop = asyncio.Event()
        task = asyncio.create_task(link.run(stop))
        await asyncio.sleep(0.05)
        self.assertIn("another client holds this satellite", link.status)
        self.assertFalse(link.connected)
        await _close(stop, task)

    async def test_without_the_package_the_refusal_names_it_and_stops_trying(self):
        with mock.patch.dict(sys.modules, {"aioesphomeapi": None}):
            with self.assertRaises(sat.SatelliteUnavailable) as caught:
                sat._default_client("h", 6053, "k")  # noqa: SLF001
        self.assertIn("pip install aioesphomeapi", str(caught.exception))

        def _missing(host, port, key):
            raise sat.SatelliteUnavailable(str(caught.exception))

        link = sat.SatelliteLink("kitchen", "h", "k", publish=None, client_factory=_missing)
        await asyncio.wait_for(link.run(asyncio.Event()), 1)   # returns: retrying cannot install a package
        self.assertIn("pip install aioesphomeapi", link.status)

    async def test_the_volume_is_set_on_connect(self):
        link, client, _p = _link(volume=1.0)
        stop, task = await _connected(link, client)
        self.assertIn({"volume": 1.0, "key": 7}, client.media)
        await _close(stop, task)

    async def test_connecting_tells_the_service(self):
        """The hook the laptop's auto-mute hangs on (2026-09-27)."""
        link, client, _p = _link()
        told: list[str] = []

        async def _up(name):
            told.append(name)

        link.on_connected = _up
        stop, task = await _connected(link, client)
        self.assertEqual(told, ["kitchen"])
        await _close(stop, task)


class TheMicrophone(unittest.IsolatedAsyncioTestCase):
    async def test_any_chunk_size_comes_out_as_whole_frames(self):
        mic = sat.SatelliteMicrophone("kitchen")
        mic.feed(b"\x01\x00" * 700)                             # 1400 bytes: one frame and a bit
        mic.feed(b"\x01\x00" * 300)                             # the bit completes a second
        stream = mic.stream()
        self.assertEqual(await stream.__anext__(), b"\x01\x00" * (FRAME_BYTES // 2))
        self.assertEqual(await stream.__anext__(), b"\x01\x00" * (FRAME_BYTES // 2))
        self.assertEqual(await stream.__anext__(), b"\x00" * FRAME_BYTES, "then a quiet room")

    async def test_audio_is_only_taken_during_a_run_before_speech_ends(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        await client.handlers["handle_audio"](b"\x01" * FRAME_BYTES)
        self.assertTrue(link.microphone._queue.empty(), "no run, no audio")  # noqa: SLF001
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        await client.handlers["handle_audio"](b"\x01" * FRAME_BYTES)
        self.assertEqual(link.microphone._queue.qsize(), 1)  # noqa: SLF001
        link.microphone.on_state("thinking")
        await client.handlers["handle_audio"](b"\x01" * FRAME_BYTES)
        self.assertEqual(link.microphone._queue.qsize(), 1, "nothing after Sim decided the turn was over")  # noqa: SLF001
        await _close(stop, task)


class ThroughTheRealSession(unittest.IsolatedAsyncioTestCase):
    """The satellite behind `VoiceSession`, as `Service.add_room` will put
    it: a wake, a turn, a reply, the run closed."""

    async def test_a_spoken_turn_on_a_satellite_is_answered_on_it(self):
        from dataclasses import replace

        from simorgh.voice.fakes import FakeRecogniser, FakeSynthesiser
        from simorgh.voice.pipeline import Pipeline, Room
        from simorgh.voice.session import VoiceSession
        from tests.simorgh.voice.test_session import _Bus, _config, _Replies, _Script

        link, client, published = _link()
        stop_link, link_task = await _connected(link, client)
        config = replace(_config(), device="kitchen")
        script = _Script((True, 20), (False, 10_000))
        stt, tts = FakeRecogniser("what time is it", 0.95), FakeSynthesiser()
        pipeline = Pipeline(bus=_Bus(), clock=None, logger=None, ledger=None, config=config,
                            microphone=link.microphone, speaker=link.speaker, recogniser=stt, synthesiser=tts,
                            detector_factory=lambda: script)
        pipeline.ask = _Replies(["It is three."]).ask  # type: ignore[method-assign]
        session = VoiceSession(pipeline=pipeline, config=config, microphone=link.microphone, speaker=link.speaker,
                               recogniser=stt, synthesiser=tts, detector_factory=lambda: script, room=Room("kitchen"))
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        stop = asyncio.Event()
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.05), mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            running = asyncio.create_task(session.run(stop))
            for _ in range(500):
                if "VOICE_ASSISTANT_RUN_END" in client.kinds():
                    break
                await asyncio.sleep(0.01)
            stop.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        kinds = client.kinds()
        for kind in ("VOICE_ASSISTANT_RUN_START", "VOICE_ASSISTANT_STT_VAD_END", "VOICE_ASSISTANT_TTS_END",
                     "VOICE_ASSISTANT_RUN_END"):
            self.assertIn(kind, kinds)
        self.assertLess(kinds.index("VOICE_ASSISTANT_STT_VAD_END"), kinds.index("VOICE_ASSISTANT_TTS_END"))
        self.assertLess(kinds.index("VOICE_ASSISTANT_TTS_END"), kinds.index("VOICE_ASSISTANT_RUN_END"))
        self.assertTrue(published, "the reply was published for the board to fetch")
        await _close(stop_link, link_task)


if __name__ == "__main__":
    unittest.main()


class ConfiguredSatellites(unittest.IsolatedAsyncioTestCase):
    """Stage 13 item 4: `[[voice.satellites]]` -> a connected board and a
    room session, the key from secrets, the reply published for
    Interface."""

    def test_the_tables_parse(self):
        from simorgh.voice.config import Config

        config = Config.from_mapping({"satellites": [{"name": "kitchen", "host": "sim-room-1.local",
                                                      "key_env": "SIM_SATELLITE_KITCHEN_KEY", "volume": 1.0}]})
        self.assertEqual(config.satellites[0]["name"], "kitchen")
        self.assertEqual(Config().satellites, (), "none by default, and nothing imported")

    async def _service(self, *, secrets, reply_url="http://192.168.50.33:8765", **extra):
        from simorgh.voice.config import Config
        from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser
        from simorgh.voice.service import Service
        from tests.simorgh.voice.test_session import _Bus

        client = _Client()
        config = Config(stt="fake", tts="fake", microphone="fake", speaker="fake", speaker_id="off",
                        stt_partials=False, backchannel=False, enabled=False, satellite_reply_url=reply_url,
                        satellites=({"name": "kitchen", "host": "sim-room-1.local",
                                     "key_env": "SIM_SATELLITE_KITCHEN_KEY", "volume": 1.0},), **extra)
        service = Service(config, microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker(),
                          recogniser=FakeRecogniser(), synthesiser=FakeSynthesiser(),
                          satellite_client=lambda host, port, key: (client, _Api()))

        class _Ledger:
            blobs: dict = {}

            async def put_blob(self, data, content_type=""):
                ref = f"blob:{len(self.blobs) + 1}"
                self.blobs[ref] = (data, content_type)
                return ref

        class _Ctx:
            bus = _Bus()
            clock = None
            ledger = _Ledger()
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

        _Ctx.secrets = secrets
        service._ctx = _Ctx()
        self.addAsyncCleanup(service.stop)
        return service, client, _Ctx

    async def test_a_satellite_without_its_key_is_named_and_the_room_is_not_made(self):
        service, _client, _ctx = await self._service(secrets={})
        await service._start_satellites()  # noqa: SLF001
        self.assertEqual(service._rooms, {})  # noqa: SLF001
        self.assertTrue(any("SIM_SATELLITE_KITCHEN_KEY" in p and "[voice] secrets" in p
                            for p in service._problems), service._problems)  # noqa: SLF001

    async def test_a_satellite_with_its_key_connects_and_gets_a_room(self):
        service, client, _ctx = await self._service(secrets={"SIM_SATELLITE_KITCHEN_KEY": "k"})
        await service._start_satellites()  # noqa: SLF001
        for _ in range(200):
            if service._satellites["kitchen"].connected:  # noqa: SLF001
                break
            await asyncio.sleep(0.005)
        state = service._state()  # noqa: SLF001
        self.assertTrue(state["satellites"]["kitchen"]["connected"], state["satellites"])
        self.assertIn("kitchen", [r["name"] for r in state["rooms"]])
        self.assertIn({"volume": 1.0, "key": 7}, client.media, "the configured volume is set")
        port = await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        self.assertIsNone(port, "voice is off, so the wake word is turned away, not left hanging")

    async def test_a_reply_piece_is_flac_in_the_ledger_announced_for_interface(self):
        import shutil

        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not installed here")
        from simorgh.contracts import topics

        service, _client, ctx = await self._service(secrets={"SIM_SATELLITE_KITCHEN_KEY": "k"})
        url = await service._publish_room_speech("kitchen", "sim-room-1.local", silence(0.2))  # noqa: SLF001
        self.assertEqual(url, "http://192.168.50.33:8765/api/room/speech?ref=blob%3A1")
        data, kind = ctx.ledger.blobs["blob:1"]
        self.assertTrue(data.startswith(b"fLaC"), "FLAC: the board plays nothing else")
        self.assertEqual(kind, "audio/flac")
        announced = ctx.bus.of(topics.VOICE_ROOM_SPEECH)
        self.assertEqual(announced[0]["ref"], "blob:1")
        self.assertEqual(announced[0]["device"], "kitchen")


class AWakeWordIsTheAddress(unittest.IsolatedAsyncioTestCase):
    """Live 2026-09-27: "What time is it?" through the board came back from
    whisper labelled `ic`, and the room dropped it as noise -- the rule
    that keeps the laptop from answering the TV. On a satellite the wake
    word already said a person is talking to Sim."""

    async def test_a_turn_after_the_wake_word_is_answered_whatever_language_whisper_guessed(self):
        from dataclasses import replace

        from simorgh.voice.api import Utterance
        from simorgh.voice.fakes import FakeRecogniser, FakeSynthesiser
        from simorgh.voice.pipeline import Pipeline, Room
        from simorgh.voice.session import VoiceSession
        from tests.simorgh.voice.test_session import _Bus, _config, _Replies, _Script

        class Icelandic(FakeRecogniser):
            async def transcribe(self, audio, *, language: str = ""):
                return Utterance(text="What time is it?", confidence=0.95, seconds=audio.seconds,
                                 engine="fake", language="icelandic")

        link, client, published = _link()
        stop_link, link_task = await _connected(link, client)
        config = replace(_config(), device="kitchen", stt_languages="en,fa")
        script = _Script((True, 20), (False, 10_000))
        stt, tts = Icelandic(), FakeSynthesiser()
        pipeline = Pipeline(bus=_Bus(), clock=None, logger=None, ledger=None, config=config,
                            microphone=link.microphone, speaker=link.speaker, recogniser=stt, synthesiser=tts,
                            detector_factory=lambda: script)
        replies = _Replies(["It is eleven."])
        pipeline.ask = replies.ask  # type: ignore[method-assign]
        session = VoiceSession(pipeline=pipeline, config=config, microphone=link.microphone, speaker=link.speaker,
                               recogniser=stt, synthesiser=tts, detector_factory=lambda: script, room=Room("kitchen"))
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        stop = asyncio.Event()
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.05), mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            running = asyncio.create_task(session.run(stop))
            for _ in range(500):
                if replies.asked:
                    break
                await asyncio.sleep(0.01)
            stop.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        self.assertEqual(replies.asked, ["Okay Nabu, what time is it?"],
                         "heard and asked -- with the wake word put back -- not dropped as noise")
        await _close(stop_link, link_task)

    async def test_a_quiet_verdict_after_the_wake_word_is_said_not_left_silent(self):
        """Live 2026-09-27: "play jazz in the kitchen" over music came back
        garbled, the model said QUIET, and the board said nothing at all."""
        from dataclasses import replace

        from simorgh.voice.fakes import FakeRecogniser, FakeSynthesiser
        from simorgh.voice.pipeline import Pipeline, Room
        from simorgh.voice.session import VoiceSession
        from tests.simorgh.voice.test_session import _Bus, _config, _Replies, _Script

        link, client, published = _link()
        stop_link, link_task = await _connected(link, client)
        config = replace(_config(), device="kitchen")
        script = _Script((True, 20), (False, 10_000))
        stt, tts = FakeRecogniser("klai jaz in the kitchen", 0.95), FakeSynthesiser()
        pipeline = Pipeline(bus=_Bus(), clock=None, logger=None, ledger=None, config=config,
                            microphone=link.microphone, speaker=link.speaker, recogniser=stt, synthesiser=tts,
                            detector_factory=lambda: script)
        pipeline.ask = _Replies(["QUIET"]).ask  # type: ignore[method-assign]
        session = VoiceSession(pipeline=pipeline, config=config, microphone=link.microphone, speaker=link.speaker,
                               recogniser=stt, synthesiser=tts, detector_factory=lambda: script, room=Room("kitchen"))
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        stop = asyncio.Event()
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.05), mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            running = asyncio.create_task(session.run(stop))
            for _ in range(500):
                if any("catch" in t for t in tts.spoken) and published:
                    break                     # synthesised AND handed to the board: they are not the same moment
                await asyncio.sleep(0.01)
            stop.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        self.assertTrue(any("didn't catch that" in t for t in tts.spoken), tts.spoken)
        self.assertTrue(published, "and it was played on the board")
        await _close(stop_link, link_task)

    async def test_a_quiet_verdict_in_a_follow_up_run_stays_quiet(self):
        """Live 2026-09-27: a how-to video in the room reached a Follow Up
        Mode run, the model rightly said QUIET, and Sim said "Sorry, I
        didn't catch that." -- nobody had said the wake word."""
        from dataclasses import replace

        from simorgh.voice.fakes import FakeRecogniser, FakeSynthesiser
        from simorgh.voice.pipeline import Pipeline, Room
        from simorgh.voice.session import VoiceSession
        from tests.simorgh.voice.test_session import _Bus, _config, _Replies, _Script

        link, client, published = _link()
        stop_link, link_task = await _connected(link, client)
        config = replace(_config(), device="kitchen")
        script = _Script((True, 20), (False, 10_000))
        stt, tts = FakeRecogniser("right now it's set for 240 volts", 0.95), FakeSynthesiser()
        pipeline = Pipeline(bus=_Bus(), clock=None, logger=None, ledger=None, config=config,
                            microphone=link.microphone, speaker=link.speaker, recogniser=stt, synthesiser=tts,
                            detector_factory=lambda: script)
        replies = _Replies(["QUIET"])
        pipeline.ask = replies.ask  # type: ignore[method-assign]
        session = VoiceSession(pipeline=pipeline, config=config, microphone=link.microphone, speaker=link.speaker,
                               recogniser=stt, synthesiser=tts, detector_factory=lambda: script, room=Room("kitchen"))
        await client.handlers["handle_start"]("c1", 1, None, None)      # no wake word: a follow-up run
        self.assertTrue(link.microphone.follow_up)
        stop = asyncio.Event()
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.05), mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            running = asyncio.create_task(session.run(stop))
            for _ in range(300):
                if replies.asked:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.3)
            stop.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        self.assertTrue(replies.asked, "the model was asked")
        self.assertFalse(any("catch" in t for t in tts.spoken), tts.spoken)
        await _close(stop_link, link_task)

    def test_the_laptop_microphone_never_claims_a_wake(self):
        from simorgh.voice.fakes import FakeMicrophone

        self.assertFalse(getattr(FakeMicrophone(), "woken", False))
        self.assertFalse(sat.SatelliteMicrophone("kitchen").woken, "and a satellite only inside a run")


class PlayingInTheRoom(unittest.IsolatedAsyncioTestCase):
    """Stage 13 item 8: music asked for in a room plays in that room."""

    async def _connected_service(self):
        helper = ConfiguredSatellites()
        service, client, ctx = await helper._service(secrets={"SIM_SATELLITE_KITCHEN_KEY": "k"})
        self.addAsyncCleanup(service.stop)
        await service._start_satellites()  # noqa: SLF001
        for _ in range(200):
            if service._satellites["kitchen"].connected:  # noqa: SLF001
                break
            await asyncio.sleep(0.005)
        replies: list[dict] = []

        async def _reply(message, topic, payload):
            replies.append(payload)
        service._reply = _reply  # type: ignore[method-assign]
        return service, client, replies

    class _Msg:
        def __init__(self, payload):
            self.payload = payload

    async def test_play_with_no_room_goes_to_the_board_you_just_spoke_to_as_music(self):
        import time

        service, client, replies = await self._connected_service()
        service._satellites["kitchen"].last_wake_at = time.time()  # noqa: SLF001
        await service._on_room_play(self._Msg({"action": "play", "url": "https://radio/jazz.mp3", "title": "Jazz"}))  # noqa: SLF001
        self.assertTrue(replies[-1]["ok"], replies)
        self.assertEqual(replies[-1]["room"], "kitchen")
        played = [m for m in client.media if m.get("media_url")]
        self.assertEqual(played[-1]["media_url"], "https://radio/jazz.mp3")
        self.assertFalse(played[-1]["announcement"], "music, not an announcement: a wake word ducks it")

    async def test_stop_and_volume(self):
        service, client, replies = await self._connected_service()
        await service._on_room_play(self._Msg({"action": "stop", "room": "Kitchen"}))  # noqa: SLF001
        self.assertIn({"command": "STOP", "key": 7}, client.media)
        await service._on_room_play(self._Msg({"action": "volume", "volume": 0.4, "room": "kitchen"}))  # noqa: SLF001
        self.assertIn({"volume": 0.4, "key": 7}, client.media)
        self.assertEqual(replies[-1]["detail"], "volume 40% in kitchen")

    async def test_an_unknown_room_is_refused_by_name(self):
        service, _client, replies = await self._connected_service()
        await service._on_room_play(self._Msg({"action": "play", "url": "u", "room": "garage"}))  # noqa: SLF001
        self.assertFalse(replies[-1]["ok"])
        self.assertIn("kitchen", replies[-1]["detail"])


class AQuestionIsFollowedUp(unittest.IsolatedAsyncioTestCase):
    """Stage 13 item 5: a reply that asks something opens the board's mic
    again with no wake word; one that does not, does not; and a follow-up
    nobody answers closes by itself."""

    async def _replied_run(self, link, client, *, question: bool):
        link.follow_up = lambda: question
        await client.handlers["handle_start"]("c1", 1, None, "okay_nabu")
        link.microphone.on_state("thinking")
        with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            await link.speaker.play(silence(0.02))
        link.microphone.on_state("listening")

    async def test_a_question_opens_the_mic_again_after_the_run(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.01):
            await self._replied_run(link, client, question=True)
            await asyncio.sleep(0.6)
        self.assertEqual(len(getattr(client, "announcements", [])), 1)
        self.assertTrue(client.announcements[0][1], "start_conversation: listen after it")
        kinds = client.kinds()
        self.assertIn("VOICE_ASSISTANT_RUN_END", kinds, "sent after the run ended, not inside it")
        await _close(stop, task)

    async def test_a_statement_does_not(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.01):
            await self._replied_run(link, client, question=False)
            await asyncio.sleep(0.6)
        self.assertEqual(getattr(client, "announcements", []), [])
        await _close(stop, task)

    async def test_a_follow_up_nobody_answers_closes_and_one_answered_is_addressed(self):
        link, client, _p = _link()
        link._follow_up_s = 0.1  # noqa: SLF001
        stop, task = await _connected(link, client)
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.01):
            await client.handlers["handle_start"]("c2", 1, None, None)      # no wake word: a follow-up
            self.assertTrue(link.microphone.woken, "a follow-up is addressed to Sim")
            await asyncio.sleep(0.3)
        self.assertIn("VOICE_ASSISTANT_RUN_END", client.kinds(), "nobody spoke: closed by itself")
        self.assertIsNone(link._run)  # noqa: SLF001
        await _close(stop, task)


class OneWakeWordAConversation(unittest.IsolatedAsyncioTestCase):
    """The creator, 2026-09-27: "every time I have to say the wake word ...
    I only need to say it once at the beginning of the conversation."
    `satellite_follow_up = "always"` listens after every reply -- but not
    while the board plays music, which would be taken as the next turn."""

    async def _link_for(self, mode: str):
        helper = ConfiguredSatellites()
        service, _client, _ctx = await helper._service(secrets={"SIM_SATELLITE_KITCHEN_KEY": "k"},
                                                      satellite_follow_up=mode)
        self.addAsyncCleanup(service.stop)
        await service._start_satellites()  # noqa: SLF001
        return service, service._satellites["kitchen"]  # noqa: SLF001

    async def test_always_follows_a_statement_up(self):
        service, link = await self._link_for("always")
        service._rooms["kitchen"]._voice_room.last_said = "It's four o'clock."  # noqa: SLF001
        self.assertTrue(link.follow_up())

    async def test_but_not_while_the_board_plays_music(self):
        _service, link = await self._link_for("always")
        link.playing_media = True
        self.assertFalse(link.follow_up())
        await link.stop_playback()
        self.assertFalse(link.playing_media, "stopping the music opens conversations again")
        self.assertTrue(link.follow_up())

    async def test_question_mode_still_follows_only_a_question(self):
        service, link = await self._link_for("question")
        service._rooms["kitchen"]._voice_room.last_said = "It's four o'clock."  # noqa: SLF001
        self.assertFalse(link.follow_up())
        service._rooms["kitchen"]._voice_room.last_said = "Want the forecast too?"  # noqa: SLF001
        self.assertTrue(link.follow_up())


class AConversationStaysOpenForMinutes(unittest.IsolatedAsyncioTestCase):
    """The creator, 2026-09-27: "after I say 'hey sim' I'd like sim to stay
    and monitor for interactive conversation for longer ... like 2 to 5
    minutes". A follow-up nobody speaks into is followed by another while
    the conversation lasts; once it has passed quietly, the board stops."""

    async def test_a_quiet_follow_up_is_followed_by_another_inside_the_window(self):
        link, client, _p = _link()
        link._follow_up_s = 0.05  # noqa: SLF001
        link.follow_up = lambda: True
        link.conversation_s = 1.0
        stop, task = await _connected(link, client)
        # One run lasts at most MAX_RUN_S; each quiet follow-up closes 5 s
        # before that, so 5.2 makes each wait 0.2 s inside a 1 s window.
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.01), mock.patch.object(sat, "MAX_RUN_S", 5.2):
            await client.handlers["handle_start"]("c1", 1, None, "hey_sim")
            link.microphone.on_state("thinking")
            with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
                await link.speaker.play(silence(0.02))       # Sim replied: the conversation is open
            link.microphone.on_state("listening")
            await asyncio.sleep(0.4)
            self.assertEqual(len(client.announcements), 1, "listening again after the reply")
            await client.handlers["handle_start"]("c2", 1, None, None)   # the board opens that follow-up
            self.assertTrue(link.in_conversation())
            await asyncio.sleep(0.6)                          # it closes quietly; the window is still open
            self.assertGreaterEqual(len(client.announcements), 2, "a quiet follow-up inside the window: another")
            await asyncio.sleep(0.4)
        self.assertFalse(link.in_conversation(), "then the window passed")
        await _close(stop, task)

    async def test_speech_sim_does_not_answer_does_not_keep_it_open(self):
        link, client, _p = _link()
        link.conversation_s = 100.0
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c2", 1, None, None)      # a follow-up
        link.microphone.on_state("user_speaking")                        # the TV, say
        self.assertFalse(link.in_conversation(), "only a reply opens the conversation")
        await _close(stop, task)

    async def test_zero_is_one_follow_up_as_before(self):
        link, client, _p = _link()
        link._follow_up_s = 0.05  # noqa: SLF001
        link.follow_up = lambda: True
        link.conversation_s = 0.0
        stop, task = await _connected(link, client)
        with mock.patch.object(sat, "RUN_END_GAP_S", 0.01):
            await client.handlers["handle_start"]("c2", 1, None, None)   # a follow-up nobody answers
            await asyncio.sleep(0.4)
        self.assertEqual(getattr(client, "announcements", []), [], "no conversation: no second follow-up")
        await _close(stop, task)

    async def test_it_is_a_setting_you_can_change_at_the_prompt(self):
        from simorgh.contracts.settings import VOICE_SAFE_KEYS
        from simorgh.voice.config import Config

        for key in ("satellite_conversation_s", "satellite_follow_up", "follow_up_window_s", "satellite_volume"):
            self.assertIn(key, VOICE_SAFE_KEYS, key)
        self.assertEqual(Config().satellite_conversation_s, 180.0)


class FollowUpModeIsPerBoard(unittest.IsolatedAsyncioTestCase):
    """The creator, 2026-09-27: "let's call the feature ... Follow Up Mode
    and change the cli commands to reflect that (user can enable Follow Up
    Mode per satellite device)"."""

    async def _board(self, **voice):
        return await OneWakeWordAConversation._link_for(self, voice.pop("mode", "question"))

    async def test_on_off_and_question_per_board(self):
        service, link = await self._board()
        service._rooms["kitchen"]._voice_room.last_said = "It's four o'clock."  # noqa: SLF001
        self.assertFalse(link.follow_up(), "the house default: after a question only")
        ok, said = await service._followup("kitchen", "on", "")  # noqa: SLF001
        self.assertTrue(ok)
        self.assertIn("kitchen: on", said)
        self.assertTrue(link.follow_up())
        await service._followup("", "off", "")  # noqa: SLF001 -- no board named: every board
        self.assertFalse(link.follow_up())

    async def test_its_length_per_board_in_minutes_or_seconds(self):
        service, link = await self._board()
        await service._followup("kitchen", "time", "5m")  # noqa: SLF001
        self.assertEqual(link._seconds(link.conversation_s), 300.0)  # noqa: SLF001
        await service._followup("kitchen", "time", "90")  # noqa: SLF001
        self.assertEqual(link._seconds(link.conversation_s), 90.0)  # noqa: SLF001
        ok, said = await service._followup("kitchen", "time", "forever")  # noqa: SLF001
        self.assertFalse(ok)
        self.assertIn("followup time 5m", said)

    async def test_an_unknown_board_is_refused_by_name(self):
        service, _link = await self._board()
        ok, said = await service._followup("garage", "on", "")  # noqa: SLF001
        self.assertFalse(ok)
        self.assertIn("kitchen", said)

    async def test_a_board_entry_in_the_config_is_its_own_mode(self):
        service, link = await self._board(mode="off")
        service._board_prefs["kitchen"] = {"follow_up": "on", "follow_up_s": 120}  # noqa: SLF001
        self.assertTrue(link.follow_up())
        self.assertEqual(link._seconds(link.conversation_s), 120.0)  # noqa: SLF001
        self.assertEqual(service._rooms_state()[-1]["follow_up"], "on")  # noqa: SLF001

    async def test_the_status_reply_passes_its_contract_with_a_room_running(self):
        """Live, 2026-09-27: `mute` and `unmute` raised ContractError on every
        call once a satellite room existed -- a per-device dict was written
        over the declared `rooms` list."""
        from simorgh.contracts import topics as t
        from simorgh.contracts.registry import all_specs
        from simorgh.contracts.validation import validate

        service, _link = await self._board()
        self.assertIn("kitchen", service._rooms)  # noqa: SLF001
        payload = {"ok": True, "detail": "laptop muted", **service._state()}  # noqa: SLF001
        self.assertIsInstance(payload["rooms"], list)
        schema = all_specs()[t.VOICE_CONTROL_REPLY].schema
        self.assertEqual(validate(payload, schema), [])
        self.assertIn("running", payload["rooms"][-1])

    async def test_calibrating_on_a_board_records_through_its_room(self):
        """"let's calibrate satellite sim in noisy room" (2026-09-27): the
        takes come from that board's session, tagged with its device and
        the noisy condition."""
        import tempfile
        from dataclasses import replace

        service, _link = await self._board()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service.config = replace(service.config, calibration_dir=tmp.name)
        started = []
        room = service._rooms["kitchen"]  # noqa: SLF001
        room.calibrate = lambda run: started.append(run) or ""
        service._room_tasks["kitchen"] = asyncio.get_running_loop().create_future()  # noqa: SLF001 -- "running"
        self.addCleanup(service._room_tasks["kitchen"].cancel)  # noqa: SLF001
        ok, said = await service._calibrate({"name": "Saeed", "value": "start room=kitchen noisy"}, book=None)  # noqa: SLF001
        self.assertTrue(ok, said)
        self.assertEqual((started[0].device, started[0].condition), ("kitchen", "noisy"))
        self.assertIn("Recording through kitchen", said)

    def test_it_is_saved_in_that_boards_entry(self):
        import tempfile
        import tomllib
        from pathlib import Path

        from simorgh.contracts.settings import persist_satellite

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            path.write_text('[voice]\ntts = "auto"\n\n[[voice.satellites]]\nname = "kitchen"\nhost = "k.local"\n'
                            '\n[[voice.satellites]]\nname = "hall"\nhost = "h.local"\n')
            self.assertTrue(persist_satellite(path, "kitchen", "follow_up", "on"))
            self.assertFalse(persist_satellite(path, "garage", "follow_up", "on"))
            boards = tomllib.loads(path.read_text())["voice"]["satellites"]
        self.assertEqual([b.get("follow_up") for b in boards], ["on", None])
        self.assertEqual(boards[1]["host"], "h.local")


class MusicFollowsTheBoard(unittest.IsolatedAsyncioTestCase):
    """Live, 2026-09-27: radio a previous Sim had started kept playing
    after a restart, the new Sim thought nothing was playing and opened
    follow-up after follow-up over it, and each follow-up's announcement
    made the board resume the stream -- "the third time it resumed on its
    own". The board's own media state now decides."""

    class _State:
        def __init__(self, key, name):
            import enum

            self.key = key
            self.state = enum.Enum("S", [name.upper()])[name.upper()]

    async def test_music_the_board_reports_shuts_the_follow_ups(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        self.assertFalse(link.playing_media, "a fresh Sim knows of no music")
        link._on_entity_state(self._State(7, "playing"))  # noqa: SLF001
        self.assertTrue(link.playing_media)
        link._on_entity_state(self._State(7, "announcing"))  # noqa: SLF001
        self.assertTrue(link.playing_media, "an announcement says nothing about the music under it")
        link._on_entity_state(self._State(7, "idle"))  # noqa: SLF001
        self.assertFalse(link.playing_media)
        link._on_entity_state(self._State(99, "playing"))  # noqa: SLF001 -- another entity
        self.assertFalse(link.playing_media)
        await _close(stop, task)

    async def test_music_that_comes_back_after_a_stop_is_stopped_again(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        await link.play_media("http://radio")
        await link.stop_media()
        stops = sum(1 for c in client.media if c.get("command") == "STOP")
        link._on_entity_state(self._State(7, "playing"))  # noqa: SLF001 -- the board resumed it
        self.assertEqual(sum(1 for c in client.media if c.get("command") == "STOP"), stops + 1)
        self.assertFalse(link.playing_media)
        await link.play_media("http://jazz")                 # wanted again: not stopped
        link._on_entity_state(self._State(7, "playing"))  # noqa: SLF001
        self.assertTrue(link.playing_media)
        await _close(stop, task)


class TheWakeWordListensHarderOverMusic(unittest.IsolatedAsyncioTestCase):
    """Live, 2026-09-27: after the radio started, four minutes passed with
    not one "Hey Sim" heard over the music. While the board plays music its
    wake-word sensitivity goes up; when the music stops it goes back."""

    class _SensitiveClient(_Client):
        async def list_entities_services(self):
            class SelectInfo:
                key = 42
                name = "Wake word sensitivity"
            return [MediaPlayerInfo(), SelectInfo()], []

        def select_command(self, key, state, device_id=0):
            self.selected = getattr(self, "selected", []) + [(key, state)]

    async def test_raised_while_music_plays_and_put_back_after(self):
        link, client, _p = _link(self._SensitiveClient())
        link.music_sensitivity = lambda: "Very sensitive"
        stop, task = await _connected(link, client)
        link._on_entity_state(types.SimpleNamespace(key=42, state="Moderately sensitive"))  # noqa: SLF001 -- the person's choice
        link._on_entity_state(MusicFollowsTheBoard._State(7, "playing"))  # noqa: SLF001
        link._on_entity_state(MusicFollowsTheBoard._State(7, "playing"))  # noqa: SLF001 -- said once, not twice
        link._on_entity_state(MusicFollowsTheBoard._State(7, "idle"))  # noqa: SLF001
        self.assertEqual(client.selected, [(42, "Very sensitive"), (42, "Moderately sensitive")])
        await _close(stop, task)

    async def test_sims_own_reply_is_not_music(self):
        """The board reports Sim's reply as media playing; sensitivity was
        raised and put back on every reply (live, 2026-09-27)."""
        link, client, _p = _link(self._SensitiveClient())
        link.music_sensitivity = lambda: "Very sensitive"
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c1", 1, None, "hey_sim")     # a run is open: Sim will answer
        link._on_entity_state(MusicFollowsTheBoard._State(7, "playing"))  # noqa: SLF001
        self.assertFalse(link.playing_media)
        self.assertEqual(getattr(client, "selected", []), [])
        await _close(stop, task)

    async def test_a_report_just_after_sims_reply_is_still_the_reply(self):
        link, client, _p = _link(self._SensitiveClient())
        link.music_sensitivity = lambda: "Very sensitive"
        stop, task = await _connected(link, client)
        link.speaker._last_end = sat.time.monotonic() - 2.0          # noqa: SLF001 -- a reply ended 2 s ago
        link._on_entity_state(MusicFollowsTheBoard._State(7, "playing"))  # noqa: SLF001
        self.assertEqual(getattr(client, "selected", []), [])
        link.speaker._last_end = sat.time.monotonic() - sat.BOARD_STATE_LAG_S - 1  # noqa: SLF001
        link._on_entity_state(MusicFollowsTheBoard._State(7, "playing"))  # noqa: SLF001
        self.assertEqual(client.selected, [(42, "Very sensitive")], "real music, later")
        await _close(stop, task)

    async def test_music_sim_starts_raises_it_at_once_and_stopping_puts_it_back(self):
        """The board reports PLAYING once, inside the window after Sim's
        reply, so the Persian radio played at the everyday cutoff (live,
        2026-09-27)."""
        link, client, _p = _link(self._SensitiveClient())
        link.music_sensitivity = lambda: "Very sensitive"
        stop, task = await _connected(link, client)
        link._on_entity_state(types.SimpleNamespace(key=42, state="Moderately sensitive"))  # noqa: SLF001
        link.speaker._last_end = sat.time.monotonic()          # noqa: SLF001 -- Sim just spoke
        await link.play_media("http://radio")
        await link.stop_media()
        self.assertEqual(client.selected, [(42, "Very sensitive"), (42, "Moderately sensitive")])
        await _close(stop, task)

    async def test_empty_leaves_it_alone(self):
        link, client, _p = _link(self._SensitiveClient())
        link.music_sensitivity = ""
        stop, task = await _connected(link, client)
        link._on_entity_state(MusicFollowsTheBoard._State(7, "playing"))  # noqa: SLF001
        self.assertEqual(getattr(client, "selected", []), [])
        await _close(stop, task)


class TheFirstWordsAreNotClipped(unittest.IsolatedAsyncioTestCase):
    """The creator, 2026-09-27: "when sim replies on satellite the first few
    characters of its reply are chopped out". The board's output -- and an
    Echo Dot on its jack -- wakes late; a reply after a quiet spell starts
    with `satellite_lead_in_ms` of silence, the pieces after it do not."""

    async def test_silence_leads_a_reply_after_a_quiet_spell_only(self):
        published: list[Audio] = []

        class _Link:
            def holding_reply(self):
                return False

            async def play_url(self, url):
                pass

            async def stop_playback(self):
                pass

        async def publish(audio):
            published.append(audio)
            return "u"

        speaker = sat.SatelliteSpeaker("kitchen", _Link(), publish)
        speaker.lead_in_s = lambda: 0.5
        piece = Audio(b"\x01\x00" * 1600, 16000)                 # 0.1 s of sound
        with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            await speaker.play(piece)
            await speaker.play(piece)                            # right after: the speaker is awake
            speaker._last_end -= sat.IDLE_BEFORE_LEAD_S + 1      # noqa: SLF001 -- a quiet spell
            await speaker.play(piece)
        self.assertAlmostEqual(published[0].seconds, 0.6, places=3)
        lead = memoryview(published[0].pcm[:16000]).cast("h")
        self.assertTrue(any(lead), "not digital silence: that leaves the speaker asleep")
        self.assertLessEqual(max(abs(x) for x in lead), sat.WAKE_TONE_AMPLITUDE)
        self.assertEqual((lead[0], lead[-1]), (0, 0), "faded in and out: no click")
        crossings = sum(1 for a, b in zip(lead, lead[1:]) if (a < 0) != (b < 0))
        self.assertLessEqual(crossings, 2 * 20 * 0.5 + 2, "a 20 Hz tone, not hiss: below hearing")
        self.assertEqual(published[0].pcm[16000:], piece.pcm, "then the reply, untouched")
        self.assertAlmostEqual(published[1].seconds, 0.1, places=3)
        self.assertAlmostEqual(published[2].seconds, 0.6, places=3)

    def test_the_boards_log_keeps_wake_lines_and_warnings_only(self):
        """No wake word reached Sim for three minutes and nothing could say
        whether the board heard one (2026-09-27)."""
        logged = []

        class _Logger:
            def info(self, event, **fields):
                logged.append(fields.get("line"))

        link = sat.SatelliteLink("kitchen", "h", "k", publish=None, logger=_Logger())
        for line in (b"\x1b[0;33m[W][voice_assistant:806]: No text in STT_END event\x1b[0m",
                     b"[D][micro_wake_word:123]: Detected wake word 'hey_sim'",
                     b"[I][esp-idf:000]: micro_decoder.http_client: Connected",
                     b"[W][api:436]: Home Assistant event 'esphome.tts_uri' dropped; client has not subscribed",
                     b"[E][i2s_audio:77]: Failed to read microphone"):
            link._on_board_log(types.SimpleNamespace(message=line))  # noqa: SLF001
        self.assertEqual(logged, ["[D][micro_wake_word:123]: Detected wake word 'hey_sim'",
                                  "[E][i2s_audio:77]: Failed to read microphone"])

    def test_it_is_a_setting(self):
        from simorgh.contracts.settings import VOICE_SAFE_KEYS
        from simorgh.voice.config import Config

        self.assertIn("satellite_lead_in_ms", VOICE_SAFE_KEYS)
        self.assertEqual(Config().satellite_lead_in_ms, 500)


class TheBoardDoesNotContinueOnItsOwn(unittest.IsolatedAsyncioTestCase):
    """2026-09-27, live: after one follow-up announcement the board kept
    ESPHome's `continue_conversation_` and started a new run every time a
    reply PIECE ended -- after the "I see." filler, mid-answer. Every
    INTENT_END now says `continue_conversation: 0`; Sim opens follow-ups
    itself, after the whole reply. And the follow-up run it asked for is
    a follow-up even though the board names its last wake word on it."""

    async def test_every_intent_end_clears_the_boards_continuation(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c1", 1, None, "hey_sim")
        link.microphone.on_state("thinking")
        with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            await link.speaker.play(silence(0.02))
        ends = [d for k, d, _t in client.events if k == "VOICE_ASSISTANT_INTENT_END"]
        self.assertEqual(ends, [{"continue_conversation": "0"}])
        await _close(stop, task)

    async def test_the_run_sim_asked_for_is_a_follow_up_whatever_it_is_called(self):
        link, client, _p = _link()
        stop, task = await _connected(link, client)
        await link._open_follow_up()  # noqa: SLF001
        await client.handlers["handle_start"]("c2", 1, None, "hey_sim")
        self.assertTrue(link._run.follow_up)  # noqa: SLF001
        self.assertEqual(link.microphone.wake_phrase, "", "no 'Hey Sim' put in front of a follow-up")
        await _close(stop, task)


class AWakeWordMidReplyStopsIt(unittest.IsolatedAsyncioTestCase):
    """The creator, 2026-09-27: "I tried to stop you five times, still you
    didn't stop." The board stopped its playback and opened a new run, and
    Sim sent the rest of the reply into it."""

    async def test_the_rest_of_the_reply_is_dropped_until_the_next_turn_is_heard(self):
        link, client, published = _link()
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c1", 1, None, "hey_sim")
        link.microphone.on_state("thinking")
        with mock.patch.object(sat, "FETCH_LEAD_S", 0.0):
            await link.speaker.play(silence(0.02))                 # the reply begins
            await client.handlers["handle_start"]("c2", 1, None, "hey_sim")   # the person cuts in
            before = len(published)
            await link.speaker.play(silence(0.02))                 # the old reply's next piece
            self.assertEqual(len(published), before, "dropped, not played")
            link.microphone.on_state("user_speaking")
            link.microphone.on_state("thinking")                   # the new turn is heard
            await link.speaker.play(silence(0.02))                 # its answer
        self.assertEqual(len(published), before + 1)
        await _close(stop, task)


class EveryRunSaysWhatItGot(unittest.IsolatedAsyncioTestCase):
    """2026-09-27: two of five "Hey Sim"s got no turn and the log could not
    say whether the board sent the speech. Every run now logs its audio."""

    async def test_a_run_the_board_stops_still_logs_its_audio(self):
        lines: list[tuple[str, dict]] = []

        class _Log:
            def info(self, event, **f): lines.append((event, f))
            warning = info

        link, client, _p = _link()
        link._logger = _Log()  # noqa: SLF001
        stop, task = await _connected(link, client)
        await client.handlers["handle_start"]("c1", 1, None, "hey_sim")
        await client.handlers["handle_audio"](b"\x10\x27" * 1600)     # 0.1 s, loud
        await client.handlers["handle_stop"](True)
        runs = [f for e, f in lines if e == "voice.satellite_run"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["audio_s"], 0.1)
        self.assertGreater(runs[0]["peak_rms"], 5000)
        self.assertFalse(runs[0]["heard"])
        self.assertIn("stopped by the board", runs[0]["ended"])
        await _close(stop, task)


class TheWakeWordIsPutBack(unittest.TestCase):
    """The board streams only what follows its wake word, so "Hey Sim, play
    music" reached the model as "Play music." and was refused for not
    naming Sim (live 2026-09-27)."""

    def _session(self, *, woken: bool, phrase: str = "Hey Sim"):
        from simorgh.voice.session import VoiceSession

        class _Mic:
            pass
        s = VoiceSession.__new__(VoiceSession)
        s._mic = _Mic()  # noqa: SLF001
        s._mic.woken = woken  # noqa: SLF001
        s._mic.wake_phrase = phrase  # noqa: SLF001
        return s

    def test_a_follow_up_voice_nobody_knows_is_the_room(self):
        """Live, 2026-09-27: wrestling commentary came in during Follow Up
        Mode as "Sim, opponents kicking out..." and was answered. In a run
        Sim opened, a voice measured and matched to nobody is not a turn;
        one too short to measure is not judged."""
        import types

        s = self._session(woken=True, phrase="")
        s._mic.follow_up = True  # noqa: SLF001
        s._turn_facts = {1: {"skip": ""}, 2: {"skip": "too_short"}}  # noqa: SLF001
        s.turns = types.SimpleNamespace(turn_id=1)
        nobody = types.SimpleNamespace(name="", score=0.1)
        self.assertTrue(s._unplaced_follow_up(1, nobody))  # noqa: SLF001
        self.assertFalse(s._unplaced_follow_up(1, types.SimpleNamespace(name="Saeed")))  # noqa: SLF001
        self.assertFalse(s._unplaced_follow_up(2, nobody), "too short to judge")  # noqa: SLF001
        s._unplaced_turn = 1  # noqa: SLF001
        self.assertFalse(s._wake_addressed(), "not addressed: nobody named Sim")  # noqa: SLF001
        self.assertEqual(s._with_wake_phrase("Opponents kicking out."), "Opponents kicking out.")  # noqa: SLF001
        s.turns.turn_id = 2
        self.assertTrue(s._wake_addressed(), "the next turn is judged afresh")  # noqa: SLF001
        s._mic.follow_up = False  # noqa: SLF001
        self.assertFalse(s._unplaced_follow_up(1, nobody), "a wake-word run is addressed whoever speaks")  # noqa: SLF001

    def test_a_satellite_turn_gets_its_wake_word_back(self):
        self.assertEqual(self._session(woken=True)._with_wake_phrase("Play music."), "Hey Sim, play music.")  # noqa: SLF001

    def test_nothing_is_added_twice_or_at_the_laptop(self):
        self.assertEqual(self._session(woken=True)._with_wake_phrase("Sim, play music."), "Sim, play music.")  # noqa: SLF001
        self.assertEqual(self._session(woken=False)._with_wake_phrase("Play music."), "Play music.")  # noqa: SLF001

    def test_a_follow_up_has_no_wake_word_and_says_sim(self):
        self.assertEqual(self._session(woken=True, phrase="")._with_wake_phrase("Yes please."), "Sim, yes please.")  # noqa: SLF001

    def test_the_board_names_the_wake_word_as_said(self):
        self.assertEqual(sat.SatelliteMicrophone("k").wake_phrase, "")


class NoSilenceIsMadeUpInsideARun(unittest.IsolatedAsyncioTestCase):
    """Live 2026-09-27: the board's audio comes over Wi-Fi in bursts, and a
    burst a few ms late got a made-up silent frame spliced into the words.
    "Play a music" became blips, the turn was dropped as too short -- the
    stuck runs, reproduced by replaying a kept run through a real session."""

    async def test_late_bursts_inside_a_run_get_no_silence_between_them(self):
        mic = sat.SatelliteMicrophone("kitchen")
        mic.woken = mic.streaming = True
        speech = b"\x10\x27" * (FRAME_BYTES // 2)
        stream = mic.stream()

        async def board():
            for _ in range(4):
                await asyncio.sleep(0.08)          # later than a 30 ms frame
                mic.feed(speech * 2)
        feeding = asyncio.create_task(board())
        got = [await asyncio.wait_for(stream.__anext__(), 2) for _ in range(8)]
        await feeding
        self.assertTrue(all(f == speech for f in got), "every frame in a run is the board's own audio")

    async def test_between_runs_the_room_is_still_paced_silence(self):
        mic = sat.SatelliteMicrophone("kitchen")
        stream = mic.stream()
        loop = asyncio.get_running_loop()
        began = loop.time()
        frame = await stream.__anext__()
        self.assertEqual(frame, b"\x00" * FRAME_BYTES)
        self.assertLess(loop.time() - began, 0.2, "no run: a quiet room, frame by frame")
