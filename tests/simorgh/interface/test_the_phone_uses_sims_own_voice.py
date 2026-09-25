"""`POST /api/say` and `POST /api/listen`: Sim's real engines, over the wire.

Stage 12. The phone used Apple's `AVSpeechSynthesizer` and
`SFSpeechRecognizer` until 2026-09-24 -- "why the voice on sim app sounds
robotic, I want to have same voice chat experience as I have on mac with
same stt and tts engines" (the creator). These two routes hand it Kokoro's
WAV and whisper's words instead.

Neither goes through `_run_for_page`: no tool is being asked for and no
effect proposed. `chat` is the gate, because saying a sentence to the
person holding the phone is what `chat` already means.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi


class _Reply:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


class _Bus:
    """One request, one canned reply, and a record of what was asked."""

    def __init__(self, replies: dict) -> None:
        self.replies = replies
        self.asked: list[tuple[str, dict]] = []

    async def request_or_error(self, message, *, timeout: float):
        self.asked.append((message.type, dict(message.payload)))
        answer = self.replies[message.type]
        if isinstance(answer, Exception):
            raise answer
        return _Reply(answer)


class _Ledger:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put_blob(self, data: bytes, *, content_type: str = "") -> str:
        ref = f"sha256:{len(self.blobs):064d}"
        self.blobs[ref] = data
        return ref

    async def get_blob(self, ref: str) -> bytes:
        return self.blobs[ref]


class ThePhoneUsesSimsOwnVoice(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")
        self.ledger = _Ledger()
        self.bus = _Bus({
            topics.VOICE_SYNTHESISE_REQUEST: {"ok": True, "ref": "", "seconds": 1.25, "engine": "kokoro"},
            topics.VOICE_TRANSCRIBE_REQUEST: {"ok": True, "text": "turn the porch light on",
                                              "confidence": 0.94, "engine": "whisper_server", "seconds": 2.0},
        })
        self.api = HttpApi(bus=self.bus, ledger=self.ledger, token="shared", devices=self.book)

    def _token(self, *, capabilities=("read", "chat")) -> str:
        pending = self.book.begin_pairing(name="iPhone", capabilities=capabilities)
        _, token = self.book.redeem(pending.code)
        return token

    async def _call(self, path: str, body: bytes, token: str | None, query: dict | None = None):
        handler = self.api._routes[("POST", path)].handler               # noqa: SLF001
        headers = {"authorization": f"Bearer {token}"} if token else {}
        return await handler(query or {}, body, headers)

    # --------------------------------------------------------------- say
    async def test_the_wav_itself_comes_back_with_the_engine_that_made_it(self):
        self.ledger.blobs["sha256:" + "0" * 64] = b"RIFF....WAVE"
        self.bus.replies[topics.VOICE_SYNTHESISE_REQUEST]["ref"] = "sha256:" + "0" * 64
        result = await self._call("/api/say", json.dumps({"text": "the porch light is on"}).encode(), self._token())
        status, payload, kind = result[0], result[1], result[2]
        self.assertEqual((status, kind), (200, "audio/wav"))
        self.assertEqual(payload, b"RIFF....WAVE", "the bytes, not a ref: one request, straight to the player")
        self.assertIn("X-Sim-Engine: kokoro", result[3])
        self.assertEqual(self.bus.asked[0][1]["text"], "the porch light is on")

    async def test_the_voice_and_speed_the_app_asks_for_travel_with_it(self):
        self.ledger.blobs["sha256:" + "0" * 64] = b"wav"
        self.bus.replies[topics.VOICE_SYNTHESISE_REQUEST]["ref"] = "sha256:" + "0" * 64
        await self._call("/api/say", json.dumps({"text": "hello", "voice": "af_bella", "speed": 1.1}).encode(),
                         self._token())
        self.assertEqual(self.bus.asked[0][1], {"text": "hello", "voice": "af_bella", "speed": 1.1})

    async def test_a_device_without_chat_may_not_make_sim_speak(self):
        status, payload, _ = await self._call(
            "/api/say", b'{"text":"hello"}', self._token(capabilities=("read",)))
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(payload)["error"]["capability"], "chat")

    async def test_nothing_to_say_is_a_four_hundred_not_a_bus_call(self):
        status, _, _ = await self._call("/api/say", b'{"text":"   "}', self._token())
        self.assertEqual(status, 400)
        self.assertEqual(self.bus.asked, [])

    async def test_a_voice_subsystem_that_is_not_there_is_a_503_the_app_can_act_on(self):
        self.bus.replies[topics.VOICE_SYNTHESISE_REQUEST] = RuntimeError("no reply to voice.synthesise.request")
        status, payload, _ = await self._call("/api/say", b'{"text":"hello"}', self._token())
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(payload)["error"]["code"], "voice_unavailable")
        # The app falls back to Apple's synthesiser on this, rather than
        # going silent; a 503 is what tells it to.

    async def test_a_reply_with_no_audio_says_why(self):
        self.bus.replies[topics.VOICE_SYNTHESISE_REQUEST] = {"ok": False, "detail": "kokoro is not installed"}
        status, payload, _ = await self._call("/api/say", b'{"text":"hello"}', self._token())
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(payload)["error"]["detail"], "kokoro is not installed")

    # ------------------------------------------------------------ listen
    async def test_recorded_audio_is_stored_then_transcribed(self):
        status, payload, _ = await self._call("/api/listen", b"RIFF....WAVE", self._token())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["text"], "turn the porch light on")
        self.assertEqual(json.loads(payload)["engine"], "whisper_server")
        ref = self.bus.asked[0][1]["ref"]
        self.assertEqual(self.ledger.blobs[ref], b"RIFF....WAVE")

    async def test_the_language_in_the_query_reaches_the_recogniser(self):
        await self._call("/api/listen", b"wav", self._token(), {"language": ["fa"]})
        self.assertEqual(self.bus.asked[0][1]["language"], "fa")

    async def test_an_empty_body_is_refused_before_the_ledger(self):
        status, _, _ = await self._call("/api/listen", b"", self._token())
        self.assertEqual(status, 400)
        self.assertEqual(self.ledger.blobs, {})

    async def test_a_device_without_chat_may_not_send_audio(self):
        status, _, _ = await self._call("/api/listen", b"wav", self._token(capabilities=("read",)))
        self.assertEqual(status, 403)

    async def test_a_minute_of_speech_fits_the_cap(self):
        # 16 kHz mono int16 is 32 kB a second. A cap that cuts a turn in
        # half would be a bug nobody could see from the phone: the audio
        # would simply be short.
        cap = self.api._routes[("POST", "/api/listen")].max_body         # noqa: SLF001
        self.assertGreater(cap, 60 * 16000 * 2)
