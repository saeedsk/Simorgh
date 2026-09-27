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
