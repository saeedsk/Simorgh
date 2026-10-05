"""ElevenLabs as a Farsi voice -- in the cloud, with Mana underneath.

The creator, 2026-10-04: "go ahead and implement eleven ai live voice tts
integration", after the cost check (about 3,400 characters a day spoken,
~100k a month: ~$5 on Flash, ~$10 on the quality models). His chosen Farsi
reference, Roya, is an ElevenLabs voice to begin with.

Stdlib HTTP, no SDK: `POST /v1/text-to-speech/{voice_id}` with
`output_format=pcm_24000` -- raw 16-bit mono PCM at 24 kHz, which is an
`Audio` as it arrives, no decoding. One request per spoken piece.

**Never silent.** Every failure -- no key, no network, a quota, a bad voice,
a reply slower than `tts_elevenlabs_timeout_s` -- answers that piece with
the fallback voice (Mana) and records why in `problems`. A cloud voice
that can go quiet is worse than a local one that sounds plainer.

**What leaves the house:** the text of each spoken reply, to ElevenLabs.
That is why this is a named choice (`tts_farsi = "elevenlabs"`), never
something `auto` picks.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ..api import Audio

ENGINE = "elevenlabs"
API = "https://api.elevenlabs.io"
RATE = 24000
KEY_NAME = "ELEVENLABS_API_KEY"


class ElevenLabsSynthesiser:
    name = ENGINE

    def __init__(self, config, *, key, fallback, opener=None) -> None:
        """`key` is a callable returning the API key (or None), read at
        call time so a key added to secrets.toml works after a restart of
        the voice service only, and a rotated one without anything.
        `fallback` speaks whenever this cannot."""
        self._config = config
        self._key = key
        self._fallback = fallback
        self._opener = opener or urllib.request.urlopen
        self._voice_id = str(config.tts_elevenlabs_voice or "").strip()
        self._resolved: str | None = None
        self.problems: list[str] = []
        self.last_engine = ""

    def voices(self) -> list[str]:
        return [self._voice_id or "default"]

    # -- the API -------------------------------------------------------------------
    def _request(self, method: str, path: str, *, body: dict | None = None, query: dict | None = None,
                 timeout: float = 10.0) -> bytes:
        key = self._key() if callable(self._key) else self._key
        if not key:
            raise RuntimeError(f"no {KEY_NAME}: put it in ~/.simorgh/secrets.toml and list it in [voice] secrets")
        url = API + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "xi-api-key": key, "Content-Type": "application/json", "Accept": "*/*"})
        try:
            with self._opener(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace") if hasattr(exc, "read") else ""
            raise RuntimeError(f"ElevenLabs HTTP {exc.code}: {detail}") from exc

    def _voice(self) -> str:
        """The configured voice: an id is used as is; a name is looked up
        in the account's voices, then in the shared library."""
        if self._resolved:
            return self._resolved
        wanted = self._voice_id
        if not wanted:
            raise RuntimeError("no ElevenLabs voice: set [voice] tts_elevenlabs_voice to a voice id or name")
        if wanted.isalnum() and len(wanted) >= 18:
            self._resolved = wanted
            return wanted
        mine = json.loads(self._request("GET", "/v1/voices") or b"{}").get("voices") or []
        for voice in mine:
            if str(voice.get("name", "")).lower().startswith(wanted.lower()):
                self._resolved = str(voice["voice_id"])
                return self._resolved
        shared = json.loads(self._request("GET", "/v1/shared-voices",
                                          query={"search": wanted, "page_size": 20}) or b"{}").get("voices") or []
        for voice in shared:
            if str(voice.get("name", "")).lower().startswith(wanted.lower()):
                self._resolved = str(voice["voice_id"])
                return self._resolved
        raise RuntimeError(f"no ElevenLabs voice named {wanted!r} in the account or the shared library")

    def _speak(self, text: str) -> Audio:
        body = {"text": text, "model_id": self._config.tts_elevenlabs_model}
        language = str(self._config.tts_elevenlabs_language or "").strip()
        if language:
            body["language_code"] = language
        pcm = self._request("POST", f"/v1/text-to-speech/{self._voice()}", body=body,
                            query={"output_format": f"pcm_{RATE}"},
                            timeout=float(self._config.tts_elevenlabs_timeout_s))
        if len(pcm) < 2:
            raise RuntimeError("ElevenLabs returned no audio")
        return Audio(pcm=pcm[: len(pcm) - len(pcm) % 2], sample_rate=RATE)

    # -- the synthesiser ---------------------------------------------------------------
    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "") -> Audio:
        started = time.monotonic()
        try:
            audio = await asyncio.wait_for(asyncio.to_thread(self._speak, text),
                                           timeout=float(self._config.tts_elevenlabs_timeout_s) + 1.0)
            self.last_engine = ENGINE
            return audio
        except Exception as exc:  # noqa: BLE001 -- any failure is the fallback's turn, never silence
            why = f"ElevenLabs failed after {time.monotonic() - started:.1f}s ({exc}); spoke with {self._fallback.name}"
            self.problems = (self.problems + [why[:300]])[-5:]
            self.last_engine = getattr(self._fallback, "name", "fallback")
            return await self._fallback.synthesise(text, voice=voice, speed=speed, tone=tone)

    async def warmup(self) -> None:
        warm = getattr(self._fallback, "warmup", None)
        if callable(warm):
            await warm()


__all__ = ["API", "ENGINE", "ElevenLabsSynthesiser", "KEY_NAME", "RATE"]
