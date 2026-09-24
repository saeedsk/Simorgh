"""A phone as a microphone and a speaker, over one WebSocket.

The creator, 2026-09-24: "I like to have live voice connection from my
iphone to sim". The point is presence AWAY from the house -- so the
household keeps the laptop microphone, and a phone turn is answered in
that person's ear, not out loud in the living room.

Why this lives in Voice and not in Interface: audio must not cross the
Bus. The Bus carries typed messages and the Ledger carries blobs; 16 kHz
mono at 30 ms a frame is 33 messages a second per listener, which is the
wrong shape for both. Voice already owns microphones, speakers, the
endpointer and the turn manager, so the socket ends here and the frames
go straight into the same `stream()` seam `SounddeviceMicrophone` and
`FfmpegMicrophone` implement. `RemoteMicrophone` is another microphone;
nothing above it needs to know where the samples came from.

Stdlib only, including the WebSocket itself (RFC 6455): the handshake is
a SHA-1 and a base64, the framing is a few bytes of `struct`, and
`asyncio.start_server` gives us the socket -- the same choice
`interface/httpapi.py` already made for HTTP. A dependency for 80 lines
would have to be worth it.

WHAT THE PHONE SENDS: binary frames of signed 16-bit little-endian PCM,
mono, 16 kHz -- the format the whole pipeline already speaks, so nothing
transcodes. A browser cannot record that directly; the page downsamples
in an AudioWorklet before sending. Anything else (a text frame, a wrong
sample rate) is the page's bug, and this refuses it by closing rather
than guessing.

WHAT THE PHONE GETS BACK: the same, Sim's synthesised voice, frame by
frame as it is spoken. `RemoteSpeaker` is the `SilentSpeaker` idea one
step on -- it keeps the turn's time exactly as the local player does, so
the speaking flag, the echo gate and barge-in all still follow the audio,
and it also puts the samples on the wire.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import struct

from .api import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, Audio

#: RFC 6455 section 1.3. Not a secret, not a salt -- a constant that stops
#: a cached HTTP response being mistaken for a handshake.
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_OP_CONT, _OP_TEXT, _OP_BINARY = 0x0, 0x1, 0x2
_OP_CLOSE, _OP_PING, _OP_PONG = 0x8, 0x9, 0xA

#: One frame of audio, in bytes: the same 30 ms the local microphones use
#: (`audio.FRAME_MS`), so the endpointer sees the cadence it was tuned on.
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * FRAME_MS // 1000

#: A single client's backlog. At 30 ms a frame this is ~15 seconds. Past
#: it the OLDEST frames go: a listener that cannot keep up should hear
#: the recent past, not a growing delay, and unbounded would be a phone
#: on a bad connection eating the machine's memory.
MAX_QUEUED_FRAMES = 500

#: Bigger than any audio frame, so a wrong-format sender is refused at
#: the door rather than buffered.
MAX_FRAME_BYTES = 1 << 20


def accept_key(client_key: str) -> str:
    """The `Sec-WebSocket-Accept` value for a client's `Sec-WebSocket-Key`."""
    digest = hashlib.sha1((client_key.strip() + _GUID).encode("ascii")).digest()  # noqa: S324 -- RFC 6455 says SHA-1
    return base64.b64encode(digest).decode("ascii")


def handshake_response(headers: dict[str, str]) -> bytes | None:
    """The 101 bytes to write, or None when this is not a WebSocket upgrade.

    Case-insensitive on every header it reads: `Upgrade: WebSocket` and
    `upgrade: websocket` are both what browsers send, at different times.
    """
    lower = {k.lower(): v for k, v in headers.items()}
    if "websocket" not in lower.get("upgrade", "").lower():
        return None
    if "upgrade" not in lower.get("connection", "").lower():
        return None
    key = lower.get("sec-websocket-key", "")
    if not key:
        return None
    return ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n").encode("ascii")


def token_ok(given: str, expected: str) -> bool:
    """Constant-time, and an unset token means NOBODY, not everybody.

    The mirror of `interface/httpapi.py`: a microphone reachable on the
    LAN without a token would be a listening device anyone on the network
    could open, which is worse than a dashboard they could read.
    """
    if not expected or not given:
        return False
    return hmac.compare_digest(given, expected)


def frame(payload: bytes, *, opcode: int = _OP_BINARY) -> bytes:
    """One unmasked server-to-client frame. Servers never mask (RFC 6455
    section 5.1), and a masked server frame is a client-side error."""
    head = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        return head + bytes([size]) + payload
    if size < (1 << 16):
        return head + bytes([126]) + struct.pack("!H", size) + payload
    return head + bytes([127]) + struct.pack("!Q", size) + payload


class ProtocolError(Exception):
    """The peer broke the framing. The connection closes; it is never guessed at."""


async def read_frame(reader) -> tuple[int, bytes] | None:
    """`(opcode, payload)`, or None at a clean end of stream.

    Continuation frames are joined, so a caller sees whole messages. A
    client frame MUST be masked (section 5.1) and an unmasked one is a
    protocol error rather than something to tolerate: tolerating it is how
    a proxy's half-understood traffic becomes audio.
    """
    opcode, chunks = None, []
    while True:
        head = await reader.readexactly(2)
        final = bool(head[0] & 0x80)
        this_op = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        size = head[1] & 0x7F
        if size == 126:
            size = struct.unpack("!H", await reader.readexactly(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", await reader.readexactly(8))[0]
        if size > MAX_FRAME_BYTES:
            raise ProtocolError(f"frame of {size} bytes is over the {MAX_FRAME_BYTES} limit")
        if not masked:
            raise ProtocolError("a client frame must be masked")
        mask = await reader.readexactly(4)
        body = bytearray(await reader.readexactly(size))
        for i in range(size):
            body[i] ^= mask[i & 3]
        if this_op in (_OP_CLOSE, _OP_PING, _OP_PONG):
            return this_op, bytes(body)
        if this_op != _OP_CONT:
            opcode = this_op
        chunks.append(bytes(body))
        if final:
            return (opcode if opcode is not None else _OP_BINARY), b"".join(chunks)


class RemoteMicrophone:
    """Frames from a socket, behind the same interface as a real microphone.

    `stream()` is what `VoiceSession` runs on and `capture()` is
    push-to-talk, exactly as in `audio.py`. Neither knows about sockets:
    the connection pushes with `feed`, and `close` ends the stream so a
    session waiting on it is not left hanging when the phone walks out of
    wifi.
    """

    name = "remote"

    def __init__(self, *, max_queued: int = MAX_QUEUED_FRAMES) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._max = max(1, max_queued)
        self._closed = False
        #: Frames thrown away because this listener fell behind. Reported,
        #: never silent: a phone dropping audio is why an answer is wrong.
        self.dropped = 0

    @property
    def connected(self) -> bool:
        return not self._closed

    def feed(self, pcm: bytes) -> None:
        """Audio from the wire. Whole frames only: a partial frame is held
        over rather than passed on short, because the endpointer measures
        loudness per frame and a short one reads as a quiet one."""
        if self._closed or not pcm:
            return
        while self._queue.qsize() >= self._max:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self.dropped += 1
        self._queue.put_nowait(pcm)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put_nowait(None)      # wake a waiting stream

    async def stream(self, *, max_seconds: float = 0.0):
        """Frames as they arrive, until `close()` or `max_seconds`."""
        sent = 0
        limit = int(max_seconds * SAMPLE_RATE) * SAMPLE_WIDTH if max_seconds else 0
        held = bytearray()
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                if held:
                    yield bytes(held)
                return
            held += chunk
            while len(held) >= FRAME_BYTES:
                out, held = bytes(held[:FRAME_BYTES]), bytearray(held[FRAME_BYTES:])
                yield out
                sent += len(out)
                if limit and sent >= limit:
                    return

    async def capture(self, *, max_seconds: float, endpointer) -> Audio:
        """One utterance, for `voice test` and health -- the streaming path
        is `stream`. Ends when the endpointer says so, as the local
        microphones do, so the same silence rules apply to a phone."""
        pcm = bytearray()
        async for chunk in self.stream(max_seconds=max_seconds):
            pcm += chunk
            if endpointer is not None and endpointer.feed(chunk):
                break
        return Audio(pcm=bytes(pcm), sample_rate=SAMPLE_RATE)


class RemoteSpeaker:
    """Sim's voice down the same socket, keeping the turn's time.

    `SilentSpeaker` exists so the TV can play the voice while the local
    player still marks the turn's duration; this is that, plus the samples
    on the wire. Keeping the time matters: the speaking flag, the echo
    gate and barge-in all follow the player, so a speaker that returned
    at once would make Sim think it had finished talking before the phone
    had played a word.
    """

    name = "remote"

    def __init__(self, send) -> None:
        #: `send(bytes) -> Awaitable`, the connection's writer.
        self._send = send
        self._stop: asyncio.Event | None = None

    async def play(self, audio: Audio) -> None:
        self._stop = asyncio.Event()
        pcm = audio.pcm
        for start in range(0, len(pcm), FRAME_BYTES):
            if self._stop.is_set():
                return
            await self._send(pcm[start:start + FRAME_BYTES])
            # Real time, frame by frame: the phone plays at 1x, and a
            # burst would put the whole reply on the wire before the
            # person had heard the first syllable -- and barge-in would
            # have nothing left to stop.
            await asyncio.sleep(FRAME_MS / 1000.0)

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()


__all__ = ["FRAME_BYTES", "MAX_QUEUED_FRAMES", "ProtocolError", "RemoteMicrophone", "RemoteSpeaker",
           "accept_key", "frame", "handshake_response", "read_frame", "token_ok"]
