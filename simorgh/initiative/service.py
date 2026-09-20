"""Initiative as a Subsystem: one place decides to interrupt (stage 6 item 6).

It listens for the things that used to interrupt people on their own --
a camera event, a reminder coming due, Curiosity wanting to share -- asks
`api.decide` whether any channel is worth it given what the house is
doing, and proposes the delivery as an ordinary `action.proposed`. Sim
saying something unprompted is an effect, and Guardian gates effects.

What it will not do: reach a device itself, keep its own copy of who is
where (it asks World Model), or interrupt for something that can wait.
`initiative.suppressed` records the ones it holds back, with the reason,
because a decision to stay quiet is exactly as much a decision as a
decision to speak and only one of them is visible by default.
"""

from __future__ import annotations

import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .api import Notice, Situation, decide

VERSION = "0.1.0"

_CONSUMES = (
    topics.CAMERA_EVENT, topics.PERCEPT_TIME_SCHEDULED, topics.CURIOSITY_SHARE_PROPOSED,
    topics.SYSTEM_TICK_SLEEP,
)
_PRODUCES = (topics.ACTION_PROPOSED, topics.INITIATIVE_SUPPRESSED)


class Service:
    name = "initiative"
    version = VERSION
    consumes = _CONSUMES
    produces = _PRODUCES

    def __init__(self, *, owner: str = "Saeed") -> None:
        self._ctx: Context | None = None
        self._subs: list = []
        self._owner = owner
        self._last_by_kind: dict[str, float] = {}
        self._delivered_today = 0
        self._day = 0
        self.do_not_disturb: set[str] = set()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._subs = [
            await ctx.bus.subscribe(topics.CAMERA_EVENT, self._on_camera_event),
            await ctx.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, self._on_schedule_fired),
            await ctx.bus.subscribe(topics.CURIOSITY_SHARE_PROPOSED, self._on_share_proposed),
        ]

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()

    async def health(self) -> Health:
        return Health.ok(f"{self._delivered_today} unprompted delivery(ies) today")

    # -- what might be worth saying ---------------------------------------------------
    async def _on_camera_event(self, message: Message) -> None:
        kinds = [str(k) for k in (message.payload.get("kinds") or [])]
        camera = str(message.payload.get("camera") or "a camera")
        kind = "safety_alert" if "person" in kinds and "front" in camera.lower() else "event_fyi"
        await self.offer(Notice(kind=kind, text=f"{camera}: {', '.join(kinds) or 'movement'}",
                                ref=f"camera:{camera}"))

    async def _on_schedule_fired(self, message: Message) -> None:
        payload = message.payload
        await self.offer(Notice(kind="reminder", text=str(payload.get("label") or "a reminder"),
                                person=str(payload.get("person") or ""),
                                ref=str(payload.get("schedule_id") or "")))

    async def _on_share_proposed(self, message: Message) -> None:
        payload = message.payload
        await self.offer(Notice(kind=str(payload.get("kind") or "news"),
                                text=str(payload.get("summary") or ""), ref=str(payload.get("ref") or "")))

    # -- the decision ------------------------------------------------------------------
    async def offer(self, notice: Notice) -> object | None:
        """Consider one notice; the delivery proposed, or None."""
        ctx = self._ctx
        if ctx is None or not notice.text.strip():
            return None
        now = ctx.clock.now()
        day = int(now // 86_400)
        if day != self._day:
            self._day, self._delivered_today = day, 0
        situation = await self._situation()
        delivery = decide(notice, situation, owner=self._owner, now=now, last_by_kind=self._last_by_kind,
                          delivered_today=self._delivered_today, do_not_disturb=self.do_not_disturb)
        if delivery is None:
            await ctx.bus.publish(Message.new(topics.INITIATIVE_SUPPRESSED, source=ctx.bus.source, payload={
                "kind": notice.kind, "text": notice.text[:200], "ref": notice.ref,
                "why": "nothing was worth interrupting for this right now"}))
            return None
        self._last_by_kind[notice.kind] = now
        self._delivered_today += 1
        await ctx.bus.publish(Message.new(topics.ACTION_PROPOSED, source=ctx.bus.source, payload={
            "action_id": uuid.uuid4().hex,
            "tool": delivery.tool,
            "args": ({"text": notice.text} if delivery.tool == "speak"
                     else {"text": notice.text, "to": delivery.to}),
            "scope": {"paths": [], "network": delivery.tool == "notify"},
            "reversibility": "irreversible",
            "rationale": delivery.why,
            "proposed_by": ctx.bus.source,
            # Sim's own idea, not a person's: Guardian weighs an
            # unprompted action differently from one somebody asked for.
            "requester": "", "requester_channel": "initiative",
        }))
        return delivery

    async def _situation(self) -> Situation:
        """What the house is doing, from World Model; an empty house is
        never assumed -- a facet that does not answer yields no people and
        no flags, which makes the speaker expensive and the phone cheap."""
        ctx = self._ctx
        try:
            reply = await ctx.bus.request(
                Message.new(topics.WORLD_ENV_QUERY, source=ctx.bus.source, payload={"what": "home", "args": {}}),
                timeout=0.5)
        except Exception:  # noqa: BLE001 -- no world model, no situation
            return Situation()
        data = reply.payload.get("situation") or {}
        return Situation(
            quiet_hours=bool(data.get("quiet_hours")), someone_asleep=bool(data.get("someone_asleep")),
            child_alone=bool(data.get("child_alone")), tv_playing=bool(data.get("tv_playing")),
            people=dict(data.get("people") or {}),
        )


__all__ = ["Service", "VERSION"]
