"""Stage 13 item 2: an ESPHome satellite as a microphone and a speaker,
against a fake API client -- no board on the network.

Every rule here was measured on the creator's reSpeaker XVF3800
(2026-09-25/26): the run-end race, one client per board, FLAC-by-URL
replies, and playback state that lags the audio.
"""

from __future__ import annotations

import asyncio
import sys
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

    async def _service(self, *, secrets, reply_url="http://192.168.50.33:8765"):
        from simorgh.voice.config import Config
        from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser
        from simorgh.voice.service import Service
        from tests.simorgh.voice.test_session import _Bus

        client = _Client()
        config = Config(stt="fake", tts="fake", microphone="fake", speaker="fake", speaker_id="off",
                        stt_partials=False, backchannel=False, enabled=False, satellite_reply_url=reply_url,
                        satellites=({"name": "kitchen", "host": "sim-room-1.local",
                                     "key_env": "SIM_SATELLITE_KITCHEN_KEY", "volume": 1.0},))
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
        self.assertIn("kitchen", state["rooms"])
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
        self.assertEqual(replies.asked, ["What time is it?"], "heard and asked, not dropped as noise")
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
                if any("catch" in t for t in tts.spoken):
                    break
                await asyncio.sleep(0.01)
            stop.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        self.assertTrue(any("didn't catch that" in t for t in tts.spoken), tts.spoken)
        self.assertTrue(published, "and it was played on the board")
        await _close(stop_link, link_task)

    def test_the_laptop_microphone_never_claims_a_wake(self):
        from simorgh.voice.fakes import FakeMicrophone

        self.assertFalse(getattr(FakeMicrophone(), "woken", False))
        self.assertFalse(sat.SatelliteMicrophone("kitchen").woken, "and a satellite only inside a run")
