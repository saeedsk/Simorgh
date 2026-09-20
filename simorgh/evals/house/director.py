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


class Director:
    """Drives one sandbox through a scenario."""

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox
        self._session_ids: dict[str, str] = {}

    @property
    def record(self) -> Record:
        return self.sandbox.record

    def now(self) -> float:
        """A mark to measure from: `since = director.now()`."""
        return time.monotonic()

    # -- somebody speaks ------------------------------------------------------------
    async def say(self, person: str, text: str, *, where: str = "", wait: bool = True,
                  confidence: float = 0.95, session: str = "", aloud: bool = True) -> float:
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
        mark = self.now()
        pipeline = self._pipeline()
        session_id = session or self._session_ids.setdefault(person, uuid.uuid4().hex)
        reply = await pipeline.ask(text, session_id=session_id, speaker_name=person,
                                   confidence=float(confidence), room=where)
        if aloud and reply.strip():
            await pipeline.speak(reply, session_id=session_id)
        if wait:
            await self.settle(since=mark)
        return mark

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

    async def device(self, key: str, *, kind: str = "", state: str = "", area: str = "",
                     **detail) -> float:
        """Something in the house changed by itself: the TV started, a
        camera saw somebody, a door opened."""
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message

        mark = self.now()
        topic = topics.CAMERA_EVENT if (kind or key).startswith("camera") else topics.TV_STATE
        payload = ({"camera": key, "kinds": list(detail.get("kinds") or ["motion"])}
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

        A simulated week cannot be real seconds, so the fake clock
        belongs here -- but a fake clock that the event loop does not
        share makes every `asyncio.sleep` in the system lie. That is
        the memory and companion arcs' problem to solve (items 5 and
        6), and it will be solved here, in this method, so no scenario
        changes.
        """
        total = seconds + minutes * 60.0 + hours * 3600.0 + days * 86400.0
        if total <= 0:
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


__all__ = ["Director", "TURN_TIMEOUT_S"]
