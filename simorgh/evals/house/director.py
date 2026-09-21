"""The one thing a scenario talks to (stage 11 item 1).

A scenario should read like an account of an evening -- somebody says
something from the kitchen, somebody else answers, the TV goes on, an
hour passes, Sim is restarted -- and not like a test harness. So the
director is the whole surface: five verbs in, one record out.

    await director.say("Ira", "Sim, what time is it", where="kitchen")
    await director.type("status")
    await director.advance(hours=3)
    await director.device("tv", state="playing")
    await director.restart()

`say` puts a percept on the bus with the speaker attributed, which is
what the voice pipeline produces once it has heard and placed somebody.
Real audio -- distance, noise, the television talking over it -- is the
audio scene (item 3), and when it lands `say` grows a `distance=` and
`noise=` and goes through the microphone instead. Everything a scenario
writes today keeps working then, because what a scenario asserts is
what Sim did, not how the sound got there.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from .record import Record
from .sandbox import Sandbox

#: How long a turn may take before the director stops waiting for it.
#: Generous: a real model behind a scenario is slower than the floor.
TURN_TIMEOUT_S = 120.0
#: How long to wait for the listening loop to finish with a beat it may
#: decide to ignore. Short, because "Sim said nothing" is a legitimate
#: and common outcome and every quiet beat pays this.
LISTEN_TIMEOUT_S = 12.0


#: An `advance()` longer than this moves the world's clock instead of
#: sleeping. Under it, real seconds -- a filler at two seconds and a
#: "still checking" at six are exactly the timers being tested.
SKIP_OVER_S = 60.0


class Director:
    """Drives one sandbox through a scenario."""

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox
        self._session_ids: dict[str, str] = {}
        #: The room these beats happen in (item 3). A scenario sets it
        #: once and every later beat is in that room.
        from .scene import Scene

        self.scene = Scene()
        self._voices: dict = {}
        self._kokoro = None
        self.listen_timeout_s = LISTEN_TIMEOUT_S

    @property
    def record(self) -> Record:
        return self.sandbox.record

    def now(self) -> float:
        """A mark to measure from: `since = director.now()`."""
        return time.monotonic()

    # -- somebody speaks ------------------------------------------------------------
    async def say(self, person: str, text: str, *, where: str = "", wait: bool = True,
                  confidence: float = 0.95, session: str = "", aloud: bool = True,
                  seconds: float = 0.0) -> float:
        """`person` says `text` out loud. Returns the mark it went in at.

        Driven through the voice pipeline's own `ask`, not by putting a
        percept on the bus: `ask` claims the session as a voice session,
        which is what makes the reply Sim's to SAY rather than merely to
        write. Everything from the percept to the synthesiser is the
        real path; only the microphone and the recogniser are skipped,
        and the audio scene (item 3) puts those back.

        One session per person by default, because two things somebody
        says in an evening are one conversation, which is what Sim's
        own conversation window assumes.
        """
        mark = self.record.somebody_spoke(person, text, in_the_room=False)
        pipeline = self._pipeline()
        if seconds > 0.0:
            # How long the person took to say it. `ask` skips the
            # recogniser, so the transcript that carries this in the
            # live path is never published; the World Model reads it
            # for the wellbeing baseline (how fast somebody is
            # talking), and without it a companion arc would be
            # measuring word count alone. Published in the shape the
            # real path publishes, and only when a scenario asks:
            # `into_the_room` produces the genuine article.
            from simorgh.contracts import topics
            from simorgh.contracts.envelope import Message

            await self.sandbox.kernel.bus.publish(Message.new(
                topics.VOICE_TRANSCRIPT, source="voice",
                payload={"text": text, "speaker": person, "confidence": float(confidence),
                         "seconds": float(seconds), "engine": "scripted", "device": "fake",
                         "room": where or "here", "session_id": session or ""}))
        session_id = session or self._session_ids.setdefault(person, uuid.uuid4().hex)
        reply = await pipeline.ask(text, session_id=session_id, speaker_name=person,
                                   confidence=float(confidence), room=where)
        if aloud and reply.strip():
            await pipeline.speak(reply, session_id=session_id)
        if wait:
            await self.settle(since=mark)
        return mark

    async def into_the_room(self, person: str, text: str, *, distance: float | None = None,
                            tv: str = "", overlap_with: str = "", wait: bool = True) -> float:
        """`person` speaks, and Sim has to decide whether it was for it.

        The other half of `say`. `say` asks Sim; this one makes a
        sound in the room and leaves every decision to the listening
        loop -- was that speech, whose voice is it, was it addressed
        to me, was it my own echo coming back. Those decisions are
        where the live failures were, and `ask` skips all of them.

        The voice is real (Kokoro, through the scene, into the
        microphone) because the speaker book needs real audio. The
        words are scripted, because whether Sim stayed out of a
        conversation should not depend on whether whisper heard every
        syllable -- that is measured on its own (item 3's table).
        """
        from .people import by_name

        persona = by_name(person)
        if persona is None:
            raise LookupError(f"nobody called {person!r} lives here")
        # Wait until Sim is actually listening again. A person does
        # not start the next sentence while the other one is still
        # talking, and a beat fed into a session that is still
        # finishing the last turn is dropped -- intermittently, which
        # is worse than always (2026-09-20: beats 2 and 3 of four were
        # lost, the other two fine).
        await self._ready_to_listen()
        mark = self.record.somebody_spoke(person, text, in_the_room=True)
        audio = await self._voice_of(persona, text)
        other = None
        if overlap_with:
            speaker = by_name(overlap_with)
            other = await self._voice_of(speaker, "no I said the blue one, not that one") if speaker else None
        if tv:
            self.scene.playing = await self._voice_of(by_name("Devin"), tv)
        heard = self.scene.hear(audio, distance=distance, also=other, also_after=0.4)
        self.sandbox.recogniser.queue(text)
        self.sandbox.microphone.feed(heard)
        if wait:
            # The end of a turn is a decision the session makes after
            # the speech stops, so waiting for quiet on the bus is not
            # enough: wait for the turn itself, and then for the room
            # to settle. A beat Sim deliberately ignores never
            # produces one, which is why this is a timeout and not a
            # failure.
            await self.wait_for("turn.completed", since=mark, timeout=self.listen_timeout_s)
            await self.settle(since=mark, quiet_for=0.6)
        # What Sim said now becomes what its microphone hears next.
        said = self.record.said_since(mark)
        if said:
            self.scene.last_said = await self._voice_of(None, said[-1].text)
        return mark

    async def from_the_television(self, text: str, *, wait: bool = True) -> float:
        """The television says something and nobody is in the room.

        Stage 11 item 3's third named guarantee -- "the TV never gets
        an answer" -- which had the mixer for it and no way to fire it
        alone: `into_the_room(..., tv=...)` lays the television UNDER
        a person who is really speaking, so it never tested the case
        where the only voice is the set.

        The creator hit it live on 2026-09-20. A YouTube documentary
        was playing; whisper transcribed the narration, the speaker
        book placed it as him at 0.37 against a 0.30 threshold, and
        Sim answered "They try to flee, but running isn't an
        emperor's strong point" as though he had said it -- then built
        a theory about which story he was telling. He had to type "it
        is a youtuibe audio not me".

        Deliberately a real voice through the real scene: the bug is
        in the listening path's decisions, and handing it a synthetic
        marker would skip the ones that went wrong.
        """
        from .people import by_name
        from .scene import silence

        await self._ready_to_listen()
        mark = self.now()
        voice = await self._voice_of(by_name("Devin"), text)
        self.scene.playing = voice
        heard = self.scene.hear(silence(0.25), distance=self.scene.distance)
        self.sandbox.recogniser.queue(text)
        self.sandbox.microphone.feed(heard)
        if wait:
            await self.wait_for("turn.completed", since=mark, timeout=self.listen_timeout_s)
            await self.settle(since=mark, quiet_for=0.6)
        return mark

    async def _ready_to_listen(self, *, timeout: float = 20.0) -> bool:
        """Wait for the session to be back on the microphone."""
        from simorgh.voice.turns import LISTENING

        session = getattr(self.sandbox.service("voice"), "_session", None)
        if session is None:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            speaking = getattr(getattr(session, "_pipeline", None), "speaking", False)
            if session.turns.state == LISTENING and not speaking:
                # One extra beat of quiet, so the frame the session is
                # mid-way through is finished before new speech starts.
                await asyncio.sleep(0.15)
                return True
            await asyncio.sleep(0.05)
        return False

    async def _voice_of(self, persona, text: str):
        """`text` in a persona's voice, synthesised once and kept."""
        key = (getattr(persona, "voice", "af_heart"), text)
        if key in self._voices:
            return self._voices[key]
        from .voicecache import cached_speech
        from .scene import resample

        # At the microphone's rate, not the synthesiser's. Kokoro
        # speaks at 24 kHz and the pipeline is 16 kHz; handing one to
        # the other makes every persona sound like somebody else.
        audio = await cached_speech(key[0], text, lambda: self._tts().synthesise(text, voice=key[0]),
                                    transform=resample)
        self._voices[key] = audio
        return audio

    def _tts(self):
        if self._kokoro is None:
            from simorgh.voice.config import Config
            from simorgh.voice.tts.kokoro import KokoroSynthesiser

            self._kokoro = KokoroSynthesiser(Config())
        return self._kokoro

    def _pipeline(self):
        """The voice pipeline of the running sandbox.

        Built at `voice.Service.start`, so it is fetched per call rather
        than held: `restart()` replaces it.
        """
        voice = self.sandbox.service("voice")
        pipeline = getattr(voice, "_pipeline", None) if voice is not None else None  # noqa: SLF001
        if pipeline is None:
            raise RuntimeError("the sandbox has no voice pipeline: is [voice] enabled?")
        return pipeline

    async def type(self, text: str, *, wait: bool = True) -> float:
        """The creator types at the console -- the owner's channel."""
        mark = self.now()
        interface = self.sandbox.service("interface")
        await interface._handle_line(text)  # noqa: SLF001 -- the seam `evals/scenario.py` uses
        if wait:
            await self.settle(since=mark)
        return mark

    async def propose(self, tool: str, args: dict | None = None, *, requester: str = "",
                      channel: str = "voice", reversibility: str = "irreversible",
                      wait: bool = True) -> float:
        """Somebody asks Sim to do something, and Guardian decides.

        Stands where Orchestration stands once the model has chosen a
        tool. A scenario about the safety gates needs this: with the
        floor provider Sim never proposes anything at all, so
        `did_not_call("home_call")` passed even with the whole tier
        computation deliberately broken (2026-09-20). An expectation
        that cannot fail is a line of documentation pretending to be a
        test.
        """
        import uuid

        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message

        mark = self.now()
        await self.sandbox.kernel.bus.publish(Message.new(
            topics.ACTION_PROPOSED, source="orchestration",
            payload={"action_id": uuid.uuid4().hex, "tool": tool, "args": dict(args or {}),
                     "scope": {"paths": [], "network": False}, "reversibility": reversibility,
                     "rationale": f"{requester or 'somebody'} asked", "proposed_by": "orchestration",
                     "requester": requester, "requester_channel": channel}))
        if wait:
            await self.settle(since=mark, quiet_for=0.4)
        return mark

    async def device(self, key: str, *, kind: str = "", state: str = "", area: str = "",
                     **detail) -> float:
        """Something in the house changed by itself: the TV started, a
        camera saw somebody, a door opened."""
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message

        mark = self.now()
        topic = topics.CAMERA_EVENT if (kind or key).startswith("camera") else topics.TV_STATE
        payload = ({"camera": key, "kinds": list(detail.get("kinds") or ["motion"]),
                    "channel": int(detail.get("channel") or 1)}
                   if topic == topics.CAMERA_EVENT
                   else {"mode": state or "playing", "title": str(detail.get("title") or "")})
        await self.sandbox.kernel.bus.publish(Message.new(topic, source="execution", payload=payload))
        await self.settle(since=mark, quiet_for=0.2)
        assert area or True  # `area` is the scene's (item 3); accepted now so scenarios need no rewrite
        return mark

    # -- time passes ------------------------------------------------------------------
    async def advance(self, seconds: float = 0.0, *, minutes: float = 0.0, hours: float = 0.0,
                      days: float = 0.0) -> None:
        """Let time pass. Real seconds for now, so anything on a timer
        behaves as it does live.

        Above `SKIP_OVER_S` it is the world's clock that moves instead
        (`clock.SkippingClock`): a nine-day companion arc cannot be
        nine days of real seconds, and a fake clock the event loop
        shares would make every `asyncio.sleep` in the system lie. So
        a skip moves what a skip can honestly mean -- decay,
        baselines, cooldowns, half-lives, "last heard 40 minutes ago"
        -- and nothing that waits waits any less. After a skip, poll
        for the state you expect; do not wait for a timer to notice.
        """
        total = seconds + minutes * 60.0 + hours * 3600.0 + days * 86400.0
        if total <= 0:
            return
        if total >= SKIP_OVER_S:
            self.sandbox.clock.skip(total)
            # A beat of real time so whatever was mid-flight finishes
            # on the new clock rather than straddling the jump.
            await asyncio.sleep(0.2)
            return
        await asyncio.sleep(min(total, 5.0))

    # -- the crash half ----------------------------------------------------------------
    async def restart(self) -> None:
        """Stop Sim and boot it again on the same data directory.

        What stage 4's resume is for, and the only way to tell a
        memory that was written down from one that was merely still in
        a process. The record continues across the restart: a scenario
        asks what Sim knew afterwards, not which boot it learnt it in.
        """
        record, data_dir = self.sandbox.record, self.sandbox.data_dir
        config, cap = self.sandbox._extra, self.sandbox._spend_cap_usd  # noqa: SLF001
        # Let what Sim just learnt reach the disk. Memory writes an
        # episodic record on `turn.completed`, after the reply, so a
        # restart that follows the reply too closely takes the memory
        # with it -- and the scenario then reports that Sim forgot,
        # which is a lie about Sim and a bug in the harness
        # (2026-09-20: `remembered blue tin` failed in the pack and
        # passed by hand, the difference being a few hundred
        # milliseconds).
        await self.settle(quiet_for=1.0)
        # Keep the data directory: `stop()` deletes a temporary one,
        # and the whole point of a restart is to come back to what was
        # written there. Without this the "fresh" Sim booted on a path
        # that had just been removed and remembered nothing, which the
        # scenario then reported as Sim forgetting across a restart --
        # a lie about Sim, produced by the harness (2026-09-20).
        self.sandbox._keep = True  # noqa: SLF001
        await self.sandbox.stop()
        fresh = Sandbox(config=config, data_dir=data_dir, keep=True, spend_cap_usd=cap)
        fresh.record = record
        await fresh.start()
        self.sandbox = fresh

    # -- waiting ------------------------------------------------------------------------
    async def settle(self, *, since: float = 0.0, quiet_for: float = 0.35,
                     timeout: float = TURN_TIMEOUT_S) -> None:
        """Wait until Sim has stopped doing things.

        Quiet on the bus rather than a fixed sleep: a scenario that
        sleeps long enough for the slowest turn wastes that long on
        every fast one, and a scenario that sleeps for the fast one is
        the flake nobody can reproduce.
        """
        deadline = time.monotonic() + timeout
        last = len(self.record.messages)
        idle_since = time.monotonic()
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            if len(self.record.messages) != last:
                last = len(self.record.messages)
                idle_since = time.monotonic()
                continue
            if time.monotonic() - idle_since >= quiet_for:
                return
        assert since >= 0.0

    async def wait_for(self, type_: str, *, since: float, timeout: float = TURN_TIMEOUT_S):
        """Wait for one message, or None. For a scenario that wants the
        thing itself rather than the quiet after it."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.record.first(type_, since=since)
            if found is not None:
                return found
            await asyncio.sleep(0.05)
        return None


__all__ = ["Director", "LISTEN_TIMEOUT_S", "TURN_TIMEOUT_S"]
