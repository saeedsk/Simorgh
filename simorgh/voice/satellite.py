"""A room satellite -- ESPHome voice hardware -- as a microphone and a speaker.

Stage 13 item 2 (docs/plan/stage-13-room-satellites.md). The creator's
first satellite, a reSpeaker XVF3800 with a XIAO ESP32S3, arrived on
2026-09-25; everything below that looks arbitrary was measured on it.

The board runs its own wake word. Until it fires, nothing leaves the
room -- the privacy line this whole design keeps. When it fires, the
board opens a "run" over the ESPHome native API and streams 16 kHz mono
s16le, the format `api.py` already speaks, so nothing transcodes on the
way in. Sim's own endpointer decides when the person has finished,
exactly as it does at the laptop; the board does not endpoint. The reply
goes back as a URL the board's media player fetches (it will not take
audio down the API socket in this firmware), and the board plays FLAC
only: WAV at any rate came back "Could not determine audio file type"
and the fetch was dropped (2026-09-26).

`SatelliteMicrophone` and `SatelliteSpeaker` sit behind the same seams as
`RemoteMicrophone`/`RemoteSpeaker` (voice/remote.py), so `VoiceSession`
does not know a satellite from a laptop. `SatelliteLink` owns the one
connection both of them use.

The rules learnt on the device, each of which is a line below:

- ONE client may hold a satellite's voice assistant. A second is refused
  on the device ("Multiple API Clients attempting to connect to Voice
  Assistant") and the first is dropped. Home Assistant, a stray probe,
  or a second Sim would all fight for it; the link says so by name and
  backs off rather than looping.
- The run-end race. `RUN_END` sent while the board is still stopping its
  microphone is ignored; the board then sits in AWAITING_RESPONSE for
  ever, and every later wake word STOPS a run instead of starting one.
  So `RUN_END` waits at least `RUN_END_GAP_S` after `STT_VAD_END`.
- The board's PLAYING/IDLE state lags real playback by up to ~10 s. A
  reply lasts as long as its audio, never as long as the board says.
- During an announcement the stock firmware's wake word only stops the
  playback (item 5 changes the firmware); here that arrives as
  `handle_stop`, and the speaker stops keeping time.

Optional dependency: `aioesphomeapi`, imported only when a satellite is
configured, and refused by name when missing -- the rule every voice
engine follows. Tests hand the link a fake client instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import time
from dataclasses import dataclass

from .api import Audio
from .remote import FRAME_BYTES, FRAME_MS

#: The measured minimum between `STT_VAD_END` and `RUN_END` (see above).
RUN_END_GAP_S = 1.0
#: A run nobody ended -- a session muted mid-turn, a turn the session
#: never took -- is closed after this long, so the board is never left
#: waiting for ever.
MAX_RUN_S = 60.0
#: A reply is fetched over HTTP before it plays; this much is added to
#: the audio's own length when keeping its time.
FETCH_LEAD_S = 0.3
#: Backoff between reconnects, doubling to this ceiling.
MAX_BACKOFF_S = 60.0
#: Frames kept when the session falls behind (~15 s at 30 ms).
MAX_QUEUED_FRAMES = 500
#: Inside a run, how long the microphone waits for the board's next frame
#: before it treats the stream as stalled and hands the session silence.
IN_RUN_WAIT_S = 1.0
#: A run the board starts this soon after Sim asked it to listen again is
#: that follow-up, whatever wake word the board names on it.
FOLLOW_UP_START_S = 20.0
#: ESPHome's media player resumes the stream an announcement interrupted,
#: so a STOP that lands during one of Sim's replies stops the reply and the
#: music comes back ("that's the third time it resumed on its own", live
#: 2026-09-27). Music the board starts again this soon after an explicit
#: stop is stopped again.
RESTOP_S = 15.0
#: The least time between two clearings of a jammed board's media queue.
UNJAM_EVERY_S = 10.0
#: The least time between two restarts of a board that refused even STOP.
RESTART_JAMMED_EVERY_S = 300.0
#: How long after the board logs its wake word a run must have started.
RUN_EXPECTED_S = 5.0
#: Seconds of audio at exactly zero after which the board's mic is dead.
DEAD_MIC_AFTER_S = 5.0
#: A reply piece that starts this long after the last one ended gets the
#: lead-in silence (`SatelliteSpeaker.lead_in_s`).
IDLE_BEFORE_LEAD_S = 2.0
#: How far the board's media-player state reports trail real playback.
BOARD_STATE_LAG_S = 15.0
#: The lead-in: a 20 Hz tone, not digital silence and not noise. Zeros left
#: an input-sleeping speaker (the Echo Dot on the jack) asleep, so the first
#: syllable woke it and was lost; quiet white noise woke it but was heard as
#: a hiss "just before Sim starts talking" (live, 2026-09-27). 20 Hz is a
#: signal on the wire the speaker's input detects, and below what a small
#: speaker reproduces or a person hears. Faded in and out: a tone that
#: starts or stops at full level clicks.
WAKE_TONE_HZ = 20.0
WAKE_TONE_AMPLITUDE = 900           # about -31 dBFS on the wire, inaudible at 20 Hz
WAKE_TONE_FADE_S = 0.05


def _wake_noise(samples: int, sample_rate: int = 16000, amplitude: int = WAKE_TONE_AMPLITUDE) -> bytes:
    """`samples` of the lead-in tone as int16 PCM (name kept for callers)."""
    import array
    import math

    out = array.array("h", [0]) * samples
    fade = max(1, int(WAKE_TONE_FADE_S * sample_rate))
    step = 2.0 * math.pi * WAKE_TONE_HZ / sample_rate
    for i in range(samples):
        edge = min(1.0, i / fade, (samples - 1 - i) / fade) if samples > 1 else 0.0
        out[i] = int(amplitude * max(0.0, edge) * math.sin(step * i))
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


#: Terminal colour codes in the board's log lines.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
#: Warnings the board prints on every reply, which say nothing.
_BOARD_NOISE = ("No text in STT_END event", "No text in TTS_START event",
                "event 'esphome.tts_uri' dropped")      # every reply; Home Assistant is not the board's client
#: How long the rest of a cut-off reply is dropped if no new turn is heard.
HOLD_REPLY_S = 30.0
#: Sent with every INTENT_END. ESPHome keeps `continue_conversation_` from
#: the follow-up announcement (`start_conversation`) until something clears
#: it, and while it is set the board starts a new run each time a reply
#: PIECE ends -- after "I see.", mid-answer -- so the rest of the answer
#: played into a run of its own (2026-09-27). Sim opens follow-ups itself,
#: after the whole reply.
_NO_CONTINUE = {"continue_conversation": "0"}

_SILENCE = b"\x00" * FRAME_BYTES
_MISSING = ("satellites need the ESPHome API client: `pip install aioesphomeapi` "
            "(the voice subsystem runs without it; only [[voice.satellites]] needs it)")


class SatelliteUnavailable(RuntimeError):
    """The optional dependency is missing, named."""


# ----------------------------------------------------------------- engines
class SatelliteMicrophone:
    """The satellite's audio, re-framed to 30 ms, with paced silence in
    between runs -- so to the session it is a quiet room, not a stream
    that stops. A session that saw no frames would never check its stop
    event and never run the timers that end a turn."""

    def __init__(self, name: str) -> None:
        self.name = f"satellite:{name}"
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MAX_QUEUED_FRAMES)
        self._partial = bytearray()
        self._on_state = None
        #: True from the board's wake word to the end of its run: the session
        #: treats that turn as addressed to Sim (`VoiceSession._wake_addressed`).
        self.woken = False
        #: True while the board is streaming this run's audio -- from the wake
        #: word until Sim decides the person finished; the only time the
        #: stream waits for real frames instead of making up silence.
        self.streaming = False
        #: The wake word that opened this run, as said ("Hey Sim"); "" for a
        #: follow-up. The session puts it back in front of the words.
        self.wake_phrase = ""
        #: This run was opened by Sim (Follow Up Mode), not by a wake word:
        #: nobody named Sim, so a voice the house does not know is the room
        #: -- the TV -- and not a turn (`VoiceSession._unplaced_follow_up`).
        self.follow_up = False

    def feed(self, pcm: bytes) -> None:
        """Audio from the board, any chunk size; kept as whole frames."""
        self._partial += pcm
        while len(self._partial) >= FRAME_BYTES:
            frame = bytes(self._partial[:FRAME_BYTES])
            del self._partial[:FRAME_BYTES]
            if self._queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()          # the oldest goes: a late turn beats a stuck one
            self._queue.put_nowait(frame)

    def clear(self) -> None:
        """A new run: nothing of the last one leaks into it."""
        self._partial.clear()
        while not self._queue.empty():
            self._queue.get_nowait()

    async def stream(self, *, max_seconds: float = 0.0):
        served = 0.0
        while True:
            # Between runs the board sends nothing, and a silent frame every
            # 30 ms keeps the session's clock going. INSIDE a run it must
            # not: the board's audio arrives over Wi-Fi in bursts, and a
            # burst a few ms late got a made-up silent frame spliced into
            # the middle of the person's words -- "play a music" chopped
            # into blips, the turn dropped as too short, worse right after
            # Sim spoke and the Mac was busy (reproduced 2026-09-27 by
            # replaying a kept run). In a run, wait for the real audio.
            wait = IN_RUN_WAIT_S if self.streaming else FRAME_MS / 1000.0
            try:
                frames = [await asyncio.wait_for(self._queue.get(), timeout=wait)]
            except asyncio.TimeoutError:
                # A stalled stream is silence for as long as it stalled,
                # not one frame of it: the session's clock is the frames.
                frames = [_SILENCE] * max(1, round(wait * 1000 / FRAME_MS))
            for frame in frames:
                yield frame
                served += FRAME_MS / 1000.0
                if max_seconds and served >= max_seconds:
                    return
            continue

    async def capture(self, *, max_seconds: float, endpointer) -> Audio:
        pcm = bytearray()
        async for frame in self.stream(max_seconds=max_seconds):
            pcm += frame
            if endpointer.feed(frame):
                break
        return Audio(bytes(pcm))

    def on_state(self, state: str) -> None:
        """The session's turn state (`VoiceSession._announce`): how the
        board learns that Sim has decided the person finished."""
        if self._on_state is not None:
            self._on_state(state)


class SatelliteSpeaker:
    """Sim's voice to the satellite, keeping the turn's time.

    `publish(audio) -> url` puts the audio where the board can fetch it
    (item 3's `/api/room/speech`); the link tells the board to play it.
    Then this waits the audio's own length -- the speaking flag, the echo
    gate and barge-in all follow it, as they follow `RemoteSpeaker`."""

    def __init__(self, name: str, link: "SatelliteLink", publish) -> None:
        self.name = f"satellite:{name}"
        self._link = link
        self._publish = publish
        self._stop: asyncio.Event | None = None
        #: Seconds of silence put in front of a reply that starts after the
        #: speaker has been quiet (`satellite_lead_in_ms`; a callable, read
        #: live). The board's output -- and an external speaker behind its
        #: jack -- takes a moment to wake, and eats whatever plays first:
        #: "the first few characters of its reply are chopped out" (the
        #: creator, 2026-09-27, with an Echo Dot on the board's 3.5 mm jack).
        self.lead_in_s = 0.0
        #: The lead-in tone's amplitude (`satellite_lead_in_level`; a callable,
        #: read per reply). The Echo Dot plays a 20 Hz tone as a low hum --
        #: the creator heard it (2026-09-29) -- so quieter where it still wakes.
        self.lead_level = WAKE_TONE_AMPLITUDE
        self._last_end = 0.0

    def _lead_in(self) -> float:
        try:
            value = self.lead_in_s() if callable(self.lead_in_s) else self.lead_in_s
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def play(self, audio: Audio) -> None:
        log = getattr(self._link, "_log", None)
        if self._link.holding_reply():
            if callable(log):
                log("info", "voice.satellite_piece", dropped="held after a cut-off", seconds=round(audio.seconds, 2))
            return          # the rest of a reply the person cut off
        lead = self._lead_in()
        padded = False
        if lead and time.monotonic() - self._last_end > IDLE_BEFORE_LEAD_S:
            padded = True
            # Only after a quiet spell: the pieces inside one reply follow
            # each other closely and the speaker is already awake.
            level = self.lead_level() if callable(self.lead_level) else self.lead_level
            audio = Audio(_wake_noise(int(lead * audio.sample_rate), audio.sample_rate, int(level or 0)) + audio.pcm,
                          audio.sample_rate)
        self._stop = asyncio.Event()
        started = time.monotonic()
        stopped = False
        try:
            url = await self._publish(audio)
            await self._link.play_url(url)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=audio.seconds + FETCH_LEAD_S)
                stopped = True
        finally:
            self._stop = None
            self._last_end = time.monotonic()
            # One line per piece (2026-09-27: multi-sentence replies lost
            # everything after the first sentence or two, and nothing in the
            # log could say whether the rest was sent, waited for or stopped).
            if callable(log):
                log("info", "voice.satellite_piece", seconds=round(audio.seconds, 2), lead=padded,
                    waited_s=round(time.monotonic() - started, 2), stopped_early=stopped)

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        await self._link.stop_playback()

    def interrupted(self) -> None:
        """The board stopped the reply itself (its wake word, mid-reply)."""
        if self._stop is not None:
            self._stop.set()


# -------------------------------------------------------------------- link
@dataclass
class _Run:
    started_at: float
    wake_word: str = ""
    vad_ended_at: float = 0.0
    replied: bool = False
    ended: bool = False
    follow_up: bool = False          # opened by Sim's question, not by a wake word
    speech: bool = False             # the person started talking in this run
    audio_bytes: int = 0             # what the board streamed in this run...
    first_audio_at: float = 0.0      # ...when it started...
    peak: int = 0                    # ...and the loudest 30 ms of it (s16 RMS)
    logged: bool = False
    pcm: bytearray | None = None     # the run's audio, when `keep_runs` asks for it
    states: list = None              # the session's turn states in this run, in order


def _default_client(host: str, port: int, key: str):
    try:
        import aioesphomeapi
    except ImportError as exc:  # pragma: no cover -- exercised by the refusal test with a patched import
        raise SatelliteUnavailable(_MISSING) from exc
    return aioesphomeapi.APIClient(host, port, None, noise_psk=key), aioesphomeapi


class SatelliteLink:
    """One satellite's connection: the voice assistant, its runs, and the
    media player the replies play on.

    `accepting()` says whether the room's session is listening (voice on,
    not muted). A wake word while it is not is answered with an error
    event, which puts the board straight back to idle instead of leaving
    it waiting for a reply nobody will send."""

    def __init__(self, name: str, host: str, key: str, *, publish, port: int = 6053, volume: float | None = None,
                 client_factory=None, accepting=lambda: True, logger=None, clock=time.monotonic,
                 follow_up_s: float = 6.0, keep_runs: str = "") -> None:
        self.name = name
        self.host = host
        self._key = key
        self._port = port
        self._volume = volume
        self._factory = client_factory or _default_client
        self._accepting = accepting
        self._logger = logger
        self._clock = clock
        self.microphone = SatelliteMicrophone(name)
        self.speaker = SatelliteSpeaker(name, self, publish)
        self.microphone._on_state = self._on_session_state
        self._client = None
        self._api = None
        self._media_key: int | None = None
        self._run: _Run | None = None
        self._ender: asyncio.Task | None = None
        self.connected = False
        self.status = "not started"
        self.runs = 0
        self.last_wake_at = 0.0
        #: `() -> bool`: after this run's reply, open the mic again without a
        #: wake word? The service sets it: true when Sim's reply was a
        #: question. `follow_up_s` is how long a follow-up waits for speech.
        self.follow_up = lambda: False
        #: `async (name) -> None`, awaited each time the board connects;
        #: the service mutes the laptop on the first (`mute_laptop_with_satellite`).
        self.on_connected = None
        #: Music or radio this link started and has not stopped. A board
        #: playing a song is not listening for a next turn: the song
        #: would be the turn.
        self.playing_media = False
        #: The board's own media-player state, as it reports it
        #: (`subscribe_states`): "playing", "paused", "announcing", "idle"...
        #: `playing_media` follows it, so music a previous Sim started -- or
        #: one the board resumed by itself after an announcement -- counts.
        self.board_media = ""
        #: The board's "Wake word sensitivity" select: its key, its value
        #: now, and what it was before music raised it (`music_sensitivity`).
        self._sensitivity_key: int | None = None
        self._sensitivity = ""
        self._sensitivity_before = ""
        #: The sensitivity to use while the board plays music ("" = leave it):
        #: over a song through a speaker on the jack the board's echo
        #: cancelling cannot hear "Hey Sim" at its everyday cutoff (live,
        #: 2026-09-27: four minutes of radio, not one wake). A callable, read live.
        self.music_sensitivity = ""
        #: When the music was last stopped on purpose; a resume within
        #: `RESTOP_S` of that is the board's, and is stopped again.
        self._stopped_music_at = 0.0
        self._unjammed_at = -1e9
        self._restarted_at = -1e9
        self._restart_key = None
        #: The board's "Microphone Mute" switch -- the button on the
        #: XVF3800 -- its key, and whether it is on. While it is, Sim says
        #: nothing on this satellite (the creator, 2026-10-04: "when I press
        #: that button and turn on mute, sim on satellite goes mute and
        #: stops saying"); the firmware already ignores the wake word.
        self._mute_key: int | None = None
        self.muted = False
        self._wake_heard_at = -1e9
        self._run_started_at = -1e9
        #: Seconds, or a callable giving them: read live, so `voice set`
        #: changes a running link.
        self._follow_up_s = follow_up_s
        #: How long a conversation stays open after the last reply or the
        #: last thing the person said (`satellite_conversation_s`); 0 is one
        #: follow-up only. Seconds or a callable.
        self.conversation_s = 0.0
        #: Until when this board's conversation is open.
        self._conversation_until = 0.0
        #: When Sim last asked the board to listen again. The board names
        #: its last wake word on that run too, so this is how a follow-up
        #: is told from a wake.
        self._follow_up_asked_at = 0.0
        #: Until when the rest of a reply the person cut off is dropped
        #: rather than played (0: nothing held). Cleared once the new turn
        #: is heard: what comes after that is the answer to it.
        self._hold_reply_until = 0.0
        self._publish = publish
        #: A folder to keep each wake run's audio in, as WAV (the last 20),
        #: for replaying a turn that went wrong; "" keeps nothing.
        self._keep_runs = keep_runs

    # ------------------------------------------------------------ logging
    def _log(self, level: str, event: str, **fields) -> None:
        if self._logger is not None:
            getattr(self._logger, level)(event, satellite=self.name, **fields)

    def _event(self, name: str, data: dict | None = None) -> None:
        if self._client is None:
            return
        kind = getattr(self._api.VoiceAssistantEventType, name)
        self._client.send_voice_assistant_event(kind, data)

    # --------------------------------------------------------- connection
    async def run(self, stop: asyncio.Event) -> None:
        """Hold the connection until `stop`, reconnecting with backoff.
        Each state change is logged once, not once per retry."""
        backoff = 1.0
        while not stop.is_set():
            dropped = asyncio.Event()
            try:
                await self._connect(dropped)
                backoff = 1.0
                waiter = asyncio.create_task(dropped.wait())
                stopper = asyncio.create_task(stop.wait())
                await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
                for task in (waiter, stopper):
                    task.cancel()
            except SatelliteUnavailable as exc:
                self._set_status(str(exc), "error")
                return                                   # retrying cannot install a package
            except Exception as exc:  # noqa: BLE001 -- a satellite that is unplugged is not a crash
                why = str(exc) or type(exc).__name__
                if "Multiple API Clients" in why:
                    why = ("another client holds this satellite's voice assistant (Home Assistant, a probe, "
                           "a second Sim?) -- only one may")
                self._set_status(f"unreachable: {why}", "warning")
            finally:
                await self._disconnect()
            if stop.is_set():
                break
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            backoff = min(MAX_BACKOFF_S, backoff * 2)

    def _set_status(self, status: str, level: str = "info") -> None:
        if status != self.status:
            self.status = status
            self._log(level, "voice.satellite", status=status)

    async def _connect(self, dropped: asyncio.Event) -> None:
        client, api = self._factory(self.host, self._port, self._key)
        self._client, self._api = client, api

        async def _on_stop(expected_disconnect: bool = False) -> None:
            dropped.set()

        await client.connect(on_stop=_on_stop, login=True)
        entities, _services = await client.list_entities_services()
        players = [e for e in entities if type(e).__name__ == "MediaPlayerInfo"]
        self._media_key = players[0].key if players else None
        selects = [e for e in entities if type(e).__name__ == "SelectInfo"
                   and "wake word sensitivity" in str(getattr(e, "name", "")).lower()]
        self._sensitivity_key = selects[0].key if selects else None
        # The firmware's own Restart button (hidden in HA's UI, there on the
        # API): the one thing that clears a media player that refuses even
        # STOP (`_restart_jammed`).
        restarts = [e for e in entities if type(e).__name__ == "ButtonInfo"
                    and str(getattr(e, "object_id", "") or getattr(e, "name", "")).lower() == "restart"]
        self._restart_key = restarts[0].key if restarts else None
        mutes = [e for e in entities if type(e).__name__ == "SwitchInfo"
                 and str(getattr(e, "object_id", "") or getattr(e, "name", "")).lower().replace(" ", "_")
                 in ("microphone_mute", "mic_mute", "mute")]
        self._mute_key = mutes[0].key if mutes else None
        if self._media_key is not None and self._volume is not None:
            client.media_player_command(self._media_key, volume=float(self._volume))
        client.subscribe_voice_assistant(handle_start=self._on_start, handle_stop=self._on_stop,
                                         handle_audio=self._on_audio)
        if (self._media_key is not None or self._sensitivity_key is not None or self._mute_key is not None) \
                and hasattr(client, "subscribe_states"):
            client.subscribe_states(self._on_entity_state)
        if hasattr(client, "subscribe_logs") and api is not None and hasattr(api, "LogLevel"):
            # The board's own account, into Sim's log: for three minutes on
            # 2026-09-27 no wake word reached Sim and nothing on Sim's side
            # could say whether the board had heard one.
            with contextlib.suppress(Exception):
                client.subscribe_logs(self._on_board_log, log_level=api.LogLevel.LOG_LEVEL_INFO)
        self.connected = True
        self._set_status("connected" if self._media_key is not None else "connected, but it has no media player")
        if self.on_connected is not None:
            try:
                await self.on_connected(self.name)
            except Exception as exc:  # noqa: BLE001 -- a hook that fails must not drop the board
                self._log("warning", "voice.satellite_hook_failed", error=repr(exc))

    def _on_board_log(self, message) -> None:
        """Keep the board's lines about the wake word, and its warnings and
        errors, minus the two it prints on every reply."""
        raw = getattr(message, "message", b"")
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        text = _ANSI.sub("", text).strip()
        if not text or any(noise in text for noise in _BOARD_NOISE):
            return
        if "wake" in text.lower() or text.startswith(("[E]", "[W]")):
            self._log("info", "voice.board_log", line=text[:240])
        if "Queue full" in text:
            if "command dropped" in text:
                self._restart_jammed()      # it would not take even the STOP
            else:
                self._unjam()
        if "wake_word_detected" in text:
            self._expect_run()

    def _expect_run(self) -> None:
        """The board heard its wake word; a run must start within
        `RUN_EXPECTED_S`. Live, 2026-09-27: after a run the board aborted
        mid-reply, it went on hearing "Hey Sim" and never opened another --
        fourteen minutes deaf until it was unplugged. No run in time is that
        state, and a restart is the only way out of it."""
        heard_at = self._clock()
        self._wake_heard_at = heard_at

        async def check() -> None:
            await asyncio.sleep(RUN_EXPECTED_S)
            if self._run_started_at < heard_at and self._wake_heard_at == heard_at:
                self._restart_jammed(reason="heard its wake word and opened no run")

        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(check())

    def _unjam(self) -> None:
        """The board's media player stopped taking audio ("Queue full, URI
        dropped") and every reply after it was silent, while Sim, timing
        each piece by its length, took it as played (live, 2026-09-27:
        "Sim is not audible over the satellite speaker"). STOP empties the
        queue; at most once per `UNJAM_EVERY_S`, so a board that stays
        jammed is not hammered."""
        now = self._clock()
        if now - self._unjammed_at < UNJAM_EVERY_S:
            return
        self._unjammed_at = now
        self._log("warning", "voice.satellite_unjammed")
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self.stop_playback())

    def _restart_jammed(self, reason: str = "media queue full; STOP refused") -> None:
        """The board refused the STOP too ("Queue full, command dropped"):
        its player is past clearing, and only a restart empties it. Pressed
        at most once per `RESTART_JAMMED_EVERY_S`; the board is back, and the
        link reconnects, within about a minute (live, 2026-09-27: the queue
        stayed full until the board was unplugged)."""
        now = self._clock()
        if self._restart_key is None or self._client is None or now - self._restarted_at < RESTART_JAMMED_EVERY_S:
            return
        self._restarted_at = now
        self._log("warning", "voice.satellite_restarted", reason=reason)
        with contextlib.suppress(Exception):
            self._client.button_command(self._restart_key)

    def _on_entity_state(self, state) -> None:
        """The board's media player, as it says it is. Music follows the
        board: PLAYING or PAUSED is music (Sim's follow-ups stay shut, or
        the song would be the next turn); IDLE is none; ANNOUNCING says
        nothing about the music under it."""
        key = getattr(state, "key", None)
        if key is not None and key == self._mute_key:
            self._on_mute(bool(getattr(state, "state", False)))
            return
        if key is not None and key == self._sensitivity_key:
            self._sensitivity = str(getattr(state, "state", "") or "")
            return
        if key != self._media_key or not hasattr(state, "state"):
            return
        name = str(getattr(state.state, "name", state.state)).lower()
        self.board_media = name
        if name in ("playing", "paused") and self._speaking_now():
            # Sim's own reply: the board reports it as media playing, and
            # this took it for music -- sensitivity raised and put back on
            # every reply, and the follow-up held shut (live, 2026-09-27).
            return
        if name in ("playing", "paused"):
            if self._stopped_music_at and self._clock() - self._stopped_music_at < RESTOP_S:
                self._log("info", "voice.satellite_music_restopped", state=name)
                self._send_stop()
                return
            self.playing_media = True
            if name == "playing":
                self._music_sensitivity(True)
        elif name in ("idle", "off", "none"):
            self.playing_media = False
            self._music_sensitivity(False)

    def _speaking_now(self) -> bool:
        """Sim is speaking through the board, or a run is open whose reply
        may be playing -- what the board reports now is not music."""
        if getattr(self.speaker, "_stop", None) is not None or (self._run is not None and not self._run.ended):
            return True
        # The board's PLAYING/IDLE reports lag real playback by up to ~10 s,
        # so a report just after Sim's reply ended is still that reply (live:
        # the sensitivity flipped at 14:43:55, a second after a reply ended).
        last = float(getattr(self.speaker, "_last_end", 0.0) or 0.0)
        return bool(last) and time.monotonic() - last < BOARD_STATE_LAG_S

    def _music_sensitivity(self, music: bool) -> None:
        """Raise the wake word's sensitivity while music plays; put the
        person's own choice back when it stops."""
        if self._client is None or self._sensitivity_key is None:
            return
        try:
            wanted = str(self.music_sensitivity() if callable(self.music_sensitivity) else self.music_sensitivity or "")
        except Exception:  # noqa: BLE001
            wanted = ""
        if music:
            if not wanted or self._sensitivity_before or self._sensitivity == wanted:
                return
            self._sensitivity_before = self._sensitivity or "Slightly sensitive"
            target = wanted
        else:
            if not self._sensitivity_before:
                return
            target, self._sensitivity_before = self._sensitivity_before, ""
        with contextlib.suppress(Exception):
            self._client.select_command(self._sensitivity_key, target)
            self._log("info", "voice.satellite_sensitivity", to=target, music=music)

    def _send_stop(self) -> None:
        if self._client is None or self._media_key is None:
            return
        with contextlib.suppress(Exception):
            self._client.media_player_command(self._media_key, command=self._api.MediaPlayerCommand.STOP)

    async def stop_media(self) -> None:
        """Stop the MUSIC, on purpose ("stop the jazz"): STOP now, and again
        if the board brings it back within `RESTOP_S`."""
        self._stopped_music_at = self._clock()
        await self.stop_playback()
        self._music_sensitivity(False)

    async def _disconnect(self) -> None:
        self.connected = False
        # Said, so nothing reports "not connected (connected)" -- a reply
        # sent while Sim was shutting down did (2026-09-27). Only over
        # "connected": a refusal that says WHY stays as it is.
        if self.status.startswith("connected"):
            self._set_status("disconnected")
        if self._ender is not None and not self._ender.done():
            self._ender.cancel()
        self._run = None
        self.microphone.woken = False
        self.microphone.streaming = False
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()

    # -------------------------------------------------------------- runs
    async def _on_start(self, conversation_id: str, flags: int, audio_settings, wake_word: str | None):
        """The board heard its wake word. 0 = stream over this connection."""
        self._run_started_at = self._clock()
        if not self._accepting():
            self._event("VOICE_ASSISTANT_ERROR", {"code": "not-listening", "message": "Sim is not listening"})
            self._log("info", "voice.satellite_wake_declined", wake_word=wake_word or "")
            return None
        self.microphone.clear()
        old = self._run
        if old is not None and not old.ended:
            # The wake word while a run is still open: the person cut in on
            # Sim's reply. The board has stopped its playback; the rest of
            # that reply must not follow into the new run -- it did, and
            # five "Hey Sim"s in a row stopped nothing (2026-09-27).
            old.ended = True
            self._log_run(old, "cut off by the wake word")
            self._cut_off_reply()
        asked, self._follow_up_asked_at = self._follow_up_asked_at, 0.0
        # A run Sim asked for: the board still names its last wake word.
        follow_up = not wake_word or (asked > 0 and self._clock() - asked < FOLLOW_UP_START_S)
        self._run = _Run(started_at=self._clock(), wake_word=wake_word or "", follow_up=follow_up,
                         pcm=bytearray() if self._keep_runs else None, states=[])
        self.microphone.woken = True
        self.microphone.streaming = True
        self.microphone.follow_up = follow_up
        self.microphone.wake_phrase = (wake_word or "").replace("_", " ").strip().title() \
            if wake_word and not follow_up else ""
        self.runs += 1
        self.last_wake_at = time.time()
        self._event("VOICE_ASSISTANT_RUN_START")
        self._event("VOICE_ASSISTANT_STT_START")
        self._event("VOICE_ASSISTANT_STT_VAD_START")
        self._log("info", "voice.satellite_wake", wake_word="(follow-up)" if follow_up else wake_word)
        self._watch(self._run)
        if self._run.follow_up:
            self._close_quiet_follow_up(self._run)
        return 0

    @staticmethod
    def _seconds(value) -> float:
        try:
            return float(value() if callable(value) else value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _keep_conversation(self) -> None:
        """The person spoke or Sim replied: the conversation stays open
        `conversation_s` from now."""
        span = self._seconds(self.conversation_s)
        if span > 0:
            self._conversation_until = max(self._conversation_until, self._clock() + span)

    def in_conversation(self) -> bool:
        return self._clock() < self._conversation_until

    def _close_quiet_follow_up(self, run: _Run) -> None:
        """A follow-up nobody answers closes after `follow_up_s` -- or,
        inside a conversation, after what is left of it (at most one run's
        length); `_end_run` then opens the next while the conversation
        lasts, so the board does not sit listening to an empty room."""
        wait = self._seconds(self._follow_up_s)
        left = self._conversation_until - self._clock()
        if left > wait:
            wait = min(left, MAX_RUN_S - 5.0)

        async def _close() -> None:
            await asyncio.sleep(wait)
            if self._run is run and not run.ended and not run.speech:
                self._log("info", "voice.satellite_turn", phase="follow-up unanswered")
                await self._end_run(run)
        asyncio.get_running_loop().create_task(_close())

    async def _on_audio(self, data: bytes, _extra=None) -> None:
        run = self._run
        if run is not None and not run.ended:
            if not run.audio_bytes:
                run.first_audio_at = self._clock()
            run.audio_bytes += len(data)
            if run.pcm is not None:
                run.pcm += data
            if len(data) >= 2:
                import audioop

                run.peak = max(run.peak, audioop.rms(data, 2))
        if run is not None and not run.ended and not run.vad_ended_at:
            self.microphone.feed(data)

    def _log_run(self, run: _Run, how: str) -> None:
        """One line per run, however it ended: did the board send audio,
        how soon after the wake, and was anyone in it? A run with no turn
        is otherwise silent, and the question -- was the speech lost on
        the board or ignored by Sim -- has no answer (2026-09-27)."""
        if run.logged:
            return
        run.logged = True
        self._log("info", "voice.satellite_run", ended=how, heard=bool(run.vad_ended_at), replied=run.replied,
                  follow_up=run.follow_up, audio_s=round(run.audio_bytes / 32000, 2),
                  first_audio_after_s=round(run.first_audio_at - run.started_at, 2) if run.first_audio_at else None,
                  peak_rms=run.peak, lasted_s=round(self._clock() - run.started_at, 2),
                  states=" ".join(f"{at}:{st}" for at, st in (run.states or [])) or "none")
        if run.peak == 0 and run.audio_bytes / 32000 >= DEAD_MIC_AFTER_S:
            # Seconds of audio at exactly zero: no room is that quiet. The
            # board's microphone stopped delivering sound (live, 2026-09-27:
            # 39 s at peak 0, right after a firmware warning), and a board
            # that cannot hear cannot hear its wake word either.
            self._restart_jammed(reason=f"its microphone sent {run.audio_bytes / 32000:.0f} s of pure silence")
        if run.pcm is not None and run.pcm:
            self._keep(run)

    def _keep(self, run: _Run) -> None:
        import wave
        from pathlib import Path

        folder = Path(self._keep_runs)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{self.name}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(run.pcm))
            for old in sorted(folder.glob("*.wav"))[:-20]:
                old.unlink()
        except OSError as exc:
            self._log("warning", "voice.satellite_keep_failed", error=str(exc)[:120])

    async def _on_stop(self, abort: bool) -> None:
        """The board ended the run itself: its wake word again (to stop a
        reply), or a microphone that gave up."""
        run = self._run
        if run is not None:
            run.ended = True
            self._run = None
            self._log_run(run, "stopped by the board" + (" (abort)" if abort else ""))
            if run.replied:
                self._cut_off_reply()
        self.microphone.woken = False
        self.microphone.streaming = False
        self.speaker.interrupted()

    def _cut_off_reply(self) -> None:
        """Stop the reply now playing and drop its remaining pieces until
        the person's next turn is heard (or `HOLD_REPLY_S` passes)."""
        self._hold_reply_until = self._clock() + HOLD_REPLY_S
        self.speaker.interrupted()
        self._log("info", "voice.satellite_barge_in")

    def _on_mute(self, muted: bool) -> None:
        """The mute button: on, the reply playing here stops now and the
        rest of it -- and anything else -- is not said here until it is off."""
        if muted == self.muted:
            return
        self.muted = muted
        self._log("info", "voice.satellite_muted" if muted else "voice.satellite_unmuted")
        if muted:
            # Sim's own words stop; music somebody put on is theirs to stop.
            speaking = self._speaking_now()
            self.speaker.interrupted()
            if speaking:
                self._send_stop()

    def holding_reply(self) -> bool:
        return self.muted or self._hold_reply_until > self._clock()

    def _watch(self, run: _Run) -> None:
        async def _expire() -> None:
            await asyncio.sleep(MAX_RUN_S)
            if self._run is run and not run.ended:
                self._log("warning", "voice.satellite_run_expired", seconds=MAX_RUN_S)
                await self._end_run(run)
        asyncio.get_running_loop().create_task(_expire())

    def _on_session_state(self, state: str) -> None:
        """The session's turn state, mapped onto the board's run."""
        run = self._run
        if run is None or run.ended:
            return
        if run.states is not None and (not run.states or run.states[-1][1] != state):
            run.states.append((round(self._clock() - run.started_at, 2), state))
        if state == "user_speaking":
            # Speech alone does not keep the conversation open: only a reply
            # does (`play_url`). The TV or a remark to someone else kept the
            # board opening empty follow-ups minute after minute (2026-09-27).
            run.speech = True
        if state == "thinking" and not run.vad_ended_at:
            run.vad_ended_at = self._clock()
            self._hold_reply_until = 0.0     # what comes now answers this turn
            self.microphone.streaming = False
            self._log("info", "voice.satellite_turn", phase="heard",
                      after_wake_s=round(run.vad_ended_at - run.started_at, 2))
            self._event("VOICE_ASSISTANT_STT_VAD_END")
            self._event("VOICE_ASSISTANT_STT_END", {"text": ""})
            self._event("VOICE_ASSISTANT_INTENT_START")
        elif state in ("listening", "idle") and (run.vad_ended_at or run.replied):
            # The reply is over (or there was none): end the run -- but
            # never inside the gap the board needs (the run-end race).
            if self._ender is None or self._ender.done():
                self._ender = asyncio.get_running_loop().create_task(self._end_run(run))

    async def _end_run(self, run: _Run) -> None:
        if not run.vad_ended_at:
            run.vad_ended_at = self._clock()
            self._event("VOICE_ASSISTANT_STT_VAD_END")
        wait = RUN_END_GAP_S - (self._clock() - run.vad_ended_at)
        if wait > 0:
            await asyncio.sleep(wait)
        if run.ended:
            return
        if not run.replied:
            self._event("VOICE_ASSISTANT_INTENT_END", _NO_CONTINUE)
            # A run that ends with no reply says which way it went: Sim never
            # heard the end of speech (nothing reached the session), or heard
            # it and chose silence.
            self._log("info", "voice.satellite_turn", phase="no reply",
                      heard=bool(run.vad_ended_at), after_wake_s=round(self._clock() - run.started_at, 2))
        self._event("VOICE_ASSISTANT_RUN_END")
        run.ended = True
        self._log_run(run, "run end")
        self.microphone.woken = False
        self.microphone.streaming = False
        if self._run is run:
            self._run = None
        # After a reply, or -- inside a conversation -- after a follow-up
        # nobody spoke into: listen again, until the conversation's time is
        # up with nobody talking (`satellite_conversation_s`).
        again = run.replied or (run.follow_up and self.in_conversation())
        if again and self.follow_up():
            asyncio.get_running_loop().create_task(self._open_follow_up())

    async def _open_follow_up(self) -> None:
        """Sim asked a question: have the board listen again with no wake
        word. It plays a tenth of a second of silence and then starts a
        run (`start_conversation`), sent only after this run is over --
        the INTENT_END flag the firmware also offers fires when the FIRST
        piece of a reply ends, and Sim's longer replies come in several."""
        await asyncio.sleep(0.3)
        client = self._client
        if client is None or self._run is not None:
            return
        try:
            url = await self._publish(Audio(b"\x00" * 3200))      # 0.1 s of silence
            self._follow_up_asked_at = self._clock()
            await client.send_voice_assistant_announcement_await_response(url, 15.0, start_conversation=True)
        except Exception as exc:  # noqa: BLE001 -- a missed follow-up is a wake word said again
            self._log("warning", "voice.satellite_follow_up_failed", error=str(exc)[:160])

    # ---------------------------------------------------------- playback
    async def play_url(self, url: str) -> None:
        """Inside a run, the first piece of a reply is the run's answer
        (`TTS_END` carries it and the board's LEDs follow); every other
        piece -- the rest of a long reply, or Sim speaking unprompted --
        is an announcement."""
        if self._client is None:
            raise RuntimeError(f"satellite {self.name} is not connected ({self.status})")
        run = self._run
        if run is not None and not run.ended and not run.replied:
            run.replied = True
            self._keep_conversation()
            now = self._clock()
            self._log("info", "voice.satellite_turn", phase="replying",
                      after_wake_s=round(now - run.started_at, 2),
                      after_speech_s=round(now - run.vad_ended_at, 2) if run.vad_ended_at else None)
            self._event("VOICE_ASSISTANT_INTENT_END", _NO_CONTINUE)
            self._event("VOICE_ASSISTANT_TTS_START", {"text": ""})
            self._event("VOICE_ASSISTANT_TTS_END", {"url": url})
            return
        if self._media_key is None:
            raise RuntimeError(f"satellite {self.name} has no media player to speak on")
        self._client.media_player_command(self._media_key, media_url=url, announcement=True)

    async def play_media(self, url: str) -> None:
        """Music, a radio stream: ordinary media, not an announcement, so a
        wake word ducks it and Sim's replies play over it (stage 13 item 8)."""
        if self._client is None or self._media_key is None:
            raise RuntimeError(f"satellite {self.name} is not connected ({self.status})")
        self._client.media_player_command(self._media_key, media_url=url, announcement=False)
        self._stopped_music_at = 0.0         # this music is wanted
        self.playing_media = True
        # Now, not on the board's PLAYING: the music usually starts right
        # after Sim's reply, inside the window where the board's reports are
        # taken for that reply, and the board says PLAYING only once -- so
        # the Persian radio played at the everyday cutoff and no "Hey Sim"
        # was heard over it, shouted or not (live, 2026-09-27).
        self._music_sensitivity(True)

    async def set_volume(self, level: float) -> None:
        if self._client is None or self._media_key is None:
            raise RuntimeError(f"satellite {self.name} is not connected ({self.status})")
        self._client.media_player_command(self._media_key, volume=float(level))

    async def stop_playback(self) -> None:
        self.playing_media = False
        if self._client is None or self._media_key is None:
            return
        with contextlib.suppress(Exception):
            self._client.media_player_command(self._media_key, command=self._api.MediaPlayerCommand.STOP)


__all__ = ["MAX_RUN_S", "RUN_END_GAP_S", "SatelliteLink", "SatelliteMicrophone", "SatelliteSpeaker",
           "SatelliteUnavailable"]
