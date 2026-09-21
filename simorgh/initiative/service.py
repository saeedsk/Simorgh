"""Initiative as a Subsystem: one place decides to interrupt (stage 6 item 6).

It listens for the things that used to interrupt people on their own --
a camera event, a reminder coming due, Curiosity wanting to share -- asks
`api.decide` whether any channel is worth it given what the house is
doing, and proposes the delivery as an ordinary `action.proposed`. Sim
saying something unprompted is an effect, and Guardian gates effects.

Stage 10 item 3 adds the companion's two reasons to speak first. When the
World Model says an adult who said yes seems quieter than their usual
(`world.wellbeing.changed{state: low}`), a `check_in` is weighed; when
Curiosity's share is about something a family member cares about, it goes
to them as an `interest_share` instead of to the room as news. Both pass
the consent and role gates here as well as in the World Model, both are
private (no speaker unless the person is alone), and both are *composed*:
the notice carries a state note, one `cognition.think` call writes the
words, and the model may answer NOTHING -- which is recorded as a
suppression like any other decision to stay quiet.

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
from simorgh.contracts.people import Person, from_dict as person_from_dict
from simorgh.contracts.protocols import Context, Health

from .api import (
    CHECK_IN_AGAIN_S,
    COMPOSED,
    COOLDOWN,
    RESEARCH_MAX_USD,
    RESEARCH_PER_DAY,
    NOT_NOW_HOLD_S,
    PERSONAL,
    Notice,
    Situation,
    acceptable_line,
    companion_gate,
    pushback,
    compose_prompt,
    cooldown_key,
    decide,
    matches_interest,
    state_note,
)

VERSION = "0.2.0"

_CONSUMES = (
    topics.CAMERA_EVENT, topics.CAMERA_DESCRIBED, topics.PERCEPT_TIME_SCHEDULED, topics.CURIOSITY_SHARE_PROPOSED,
    topics.TURN_COMPLETED,
    topics.WORLD_WELLBEING_CHANGED, topics.SYSTEM_TICK_SLEEP, topics.SYSTEM_TICK_IDLE,
    topics.TASK_COMPLETED,
)
_PRODUCES = (topics.ACTION_PROPOSED, topics.INITIATIVE_OFFERED, topics.INITIATIVE_SUPPRESSED,
             topics.COGNITION_THINK, topics.WORLD_ENV_QUERY, topics.TASK_CREATE)

#: How long to wait for the model to write a composed line. Unprompted
#: speech is never urgent enough to hold anything else up.
COMPOSE_TIMEOUT_S = 20.0
COMPOSE_MAX_TOKENS = 120
COMPOSE_MAX_COST_USD = 0.01


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
        #: person -> when Sim last asked how they were, cleared when
        #: they are seen their usual self again (`CHECK_IN_AGAIN_S`).
        self._asked_about: dict[str, float] = {}
        #: How long after a check-in a "not now" is about the check-in.
        #: Beyond it, "I'm fine" is an ordinary sentence.
        self._pushback_window_s = 10 * 60.0
        self._delivered_today = 0
        self._day = 0
        #: Things Sim went and found out today, and for whom
        #: (`RESEARCH_PER_DAY`). Reset with `_day`.
        self._sought_today = 0
        #: task_id -> the person it was sought for.
        self._seeking: dict[str, str] = {}
        self.do_not_disturb: set[str] = set()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._subs = [
            await ctx.bus.subscribe(topics.CAMERA_EVENT, self._on_camera_event),
            await ctx.bus.subscribe(topics.CAMERA_DESCRIBED, self._on_camera_described),
            await ctx.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, self._on_schedule_fired),
            await ctx.bus.subscribe(topics.CURIOSITY_SHARE_PROPOSED, self._on_share_proposed),
            await ctx.bus.subscribe(topics.WORLD_WELLBEING_CHANGED, self._on_wellbeing_changed),
            await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed),
            await ctx.bus.subscribe(topics.MEMORY_FACT_STORED, self._on_fact_stored),
            await ctx.bus.subscribe(topics.SYSTEM_TICK_IDLE, self._on_idle),
            await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_completed),
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

    async def _on_camera_described(self, message: Message) -> None:
        """The vision model's own words about a camera event.

        Better than `_on_camera_event`'s "Front Door: person" and
        weighed the same way. Execution used to say this aloud itself
        (`vision.py` published `voice.speak.request`), so a camera
        described the street in the room at two in the morning with
        nothing weighing the hour or the sleeping child; the cooldown
        on `event_fyi` also means the raw event and its description
        are one interruption rather than two.
        """
        camera = str(message.payload.get("camera") or "a camera")
        text = str(message.payload.get("text") or "").strip()
        if not text:
            return
        kinds = [str(k) for k in (message.payload.get("kinds") or [])]
        kind = "safety_alert" if "person" in kinds and "front" in camera.lower() else "event_fyi"
        await self.offer(Notice(kind=kind, text=f"{camera}: {text}", ref=f"camera:{camera}"))

    async def _on_idle(self, message: Message) -> None:
        """Nothing is happening, and somebody who said yes is here.

        The other half of `interest_share` (stage 10 item 8). The
        first half reroutes what Growth happens to find; this one
        goes and FINDS something, once or twice a day, about what
        one person in the room actually cares about. A friend who
        only ever passes on what drifted past them is a feed.

        Three gates, all cheap, all before any money is spent: the
        day's cap (`RESEARCH_PER_DAY`), somebody present who granted
        `interest_shares` and has an interest recorded, and the
        ordinary `interest_share` cooldown for that person -- so the
        thing Sim found this morning is not chased by another this
        afternoon.

        What comes back is offered, not said: it goes through
        `offer()` like everything else, which is what weighs the
        hour, the room and the channel.
        """
        if self._ctx is None or RESEARCH_PER_DAY <= 0:
            return
        now = self._ctx.clock.now()
        day = int(now // 86_400)
        if day != self._day:
            self._day, self._delivered_today, self._sought_today = day, 0, 0
        if self._sought_today >= RESEARCH_PER_DAY or self._seeking:
            return          # one at a time: a queue of these is a feed again
        situation = await self._situation()
        for person in await self._people():
            if person.name not in situation.people or not person.interests:
                continue
            if companion_gate(Notice(kind="interest_share", text="", person=person.name), person):
                continue
            since = self._last_by_kind.get(f"interest_share:{person.name}")
            if since is not None and (now - since) < COOLDOWN.get("interest_share", 0.0):
                continue
            await self._seek_for(person, person.interests[0], now)
            return

    async def _seek_for(self, person, interest: str, now: float) -> None:
        """One bounded research task about `interest`, for `person`."""
        ctx = self._ctx
        task_id = uuid.uuid4().hex[:12]
        self._seeking[task_id] = person.name
        self._sought_today += 1
        # The sourcebook and `web_search` are fine HERE: this is news
        # about lego robotics, not advice about a person.
        await ctx.bus.publish(Message.new(topics.TASK_CREATE, source=ctx.bus.source, payload={
            "kind": "research", "origin": "curiosity",
            "description": (f"One interesting thing from the last week about {interest}, for {person.name}. "
                            "One short paragraph in plain words, with the source. "
                            "If there is nothing new worth telling somebody, say so and stop."),
            "subject": interest, "max_steps": 6,
            "idempotency_key": task_id,
        }))

    async def _on_task_completed(self, message: Message) -> None:
        """Something Sim went to find out came back. Offer it."""
        payload = message.payload or {}
        task_id = str(payload.get("task_id") or "")
        person = self._seeking.pop(task_id, "")
        if not person:
            return
        text = " ".join(str(payload.get("text") or payload.get("summary") or "").split())
        if not text:
            await self._suppress(Notice(kind="interest_share", text="", person=person),
                                 f"nothing worth telling {person} came back")
            return
        await self.offer(Notice(kind="interest_share", text=text, person=person,
                                ref=f"sought:{task_id}"))

    async def _on_turn_completed(self, message: Message) -> None:
        """What the person said after Sim asked how they were.

        A companion that cannot be told to leave it is not a
        companion, it is a process. "Not now" or "I'm fine" holds
        check-ins with that person for a day -- they answered, they
        just do not want to talk about it, and Sim asking again
        tomorrow is the whole complaint. "Stop asking me" is consent
        being withdrawn, and Sim does not withdraw consent on
        somebody's behalf any more than it granted it: that becomes a
        `people revoke` proposal at tier 3, which the person
        confirms (stage 10 item 6).

        Only in the window after a check-in, so "I'm fine" in an
        ordinary conversation is an ordinary sentence.
        """
        payload = message.payload or {}
        person = str(payload.get("speaker") or "").strip()
        if not person:
            return
        asked = self._asked_about.get(person)
        now = self._ctx.clock.now()
        if asked is None or now - asked > self._pushback_window_s:
            return
        said = pushback(str(payload.get("user_text") or ""))
        if not said:
            return
        if said == "not now":
            # A hold, through the machinery that already holds things:
            # the cooldown this class is keyed on for this person.
            self._last_by_kind[f"check_in:{person}"] = now + NOT_NOW_HOLD_S - COOLDOWN.get("check_in", 0.0)
            await self._suppress(Notice(kind="check_in", text="", person=person),
                                 f"{person} said not now; holding check-ins with them for a day")
            return
        await self._propose_revoke(person)

    async def _on_fact_stored(self, message: Message) -> None:
        """Somebody said what they care about. Ask before remembering
        it as an interest (stage 10 item 7).

        Consolidation records `interest` facts like any other fact,
        with the sentence that said it. A fact is not a permission:
        knowing that Aran likes lego robotics and being allowed to
        bring lego robotics up unprompted are different things, and
        the second is the person's to grant. So this proposes
        `people interest add` at tier 3, with the quote in the
        rationale so whoever confirms it can see what Sim heard --
        and nothing reaches `Person.interests` without that yes.

        Only for a person Sim knows, only for a fact about
        themselves, and never twice for the same interest.
        """
        payload = message.payload or {}
        if str(payload.get("predicate") or "").strip().lower() != "interest":
            return
        name = str(payload.get("person_scope") or "").strip()
        interest = str(payload.get("object") or "").strip()
        if not name or not interest:
            return
        person = await self._person(name)
        if person is None:
            return          # nobody Sim knows; an interest belongs to a person
        if any(interest.lower() == held.lower() for held in person.interests):
            return          # already theirs; asking again is the nuisance
        quote = ""
        for ref in (payload.get("source_refs") or []):
            quote = str(ref)
            break
        ctx = self._ctx
        await ctx.bus.publish(Message.new(topics.ACTION_PROPOSED, source=ctx.bus.source, payload={
            "action_id": uuid.uuid4().hex,
            "tool": "people",
            "args": {"action": "add_interest", "name": person.name, "interest": interest},
            "scope": {"paths": [], "network": False},
            "reversibility": "reversible",
            "rationale": (f"{person.name} said they care about {interest}"
                          + (f" ({quote})" if quote else "")),
            "proposed_by": ctx.bus.source,
            "requester": "", "requester_channel": "initiative",
        }))

    async def _propose_revoke(self, person: str) -> None:
        """Ask for `wellbeing_checkins` to be withdrawn. Tier 3: the
        person themselves says yes, exactly as they did to grant it."""
        ctx = self._ctx
        await ctx.bus.publish(Message.new(topics.ACTION_PROPOSED, source=ctx.bus.source, payload={
            "action_id": uuid.uuid4().hex,
            "tool": "people",
            "args": {"action": "revoke", "name": person, "permission": "wellbeing_checkins"},
            "scope": {"paths": [], "network": False},
            "reversibility": "reversible",
            "rationale": f"{person} asked Sim to stop checking in on them",
            "proposed_by": ctx.bus.source,
            "requester": person, "requester_channel": "voice",
        }))
        self._asked_about.pop(person, None)

    async def _on_schedule_fired(self, message: Message) -> None:
        payload = message.payload
        await self.offer(Notice(kind="reminder", text=str(payload.get("label") or "a reminder"),
                                person=str(payload.get("person") or ""),
                                ref=str(payload.get("schedule_id") or "")))

    async def _on_share_proposed(self, message: Message) -> None:
        """Curiosity found something. If it is about what a family member
        who said yes cares about, it is theirs (`interest_share`); else it
        is news for the room, which mostly waits.

        `curiosity.share.proposed` carries `kind` and `content_ref` and,
        today, no `summary`; a share with no words is suppressed with a
        reason that says so, rather than silently dropped (the wire is
        stage 10 item 8's to finish)."""
        payload = message.payload
        text = str(payload.get("summary") or "")
        ref = str(payload.get("ref") or payload.get("content_ref") or "")
        if not text.strip():
            await self._suppress(Notice(kind=str(payload.get("kind") or "news"), text="", ref=ref),
                                 "the share carried no summary to say")
            return
        situation = await self._situation()
        for person in await self._people():
            interest = matches_interest(text, person.interests)
            if interest and person.name in situation.people and not companion_gate(
                    Notice(kind="interest_share", text="", person=person.name), person):
                await self.offer(Notice(kind="interest_share", text=text, person=person.name, ref=ref),
                                 situation=situation)
                return
        await self.offer(Notice(kind=str(payload.get("kind") or "news"), text=text, ref=ref), situation=situation)

    async def _on_wellbeing_changed(self, message: Message) -> None:
        """The World Model's posterior says somebody who said yes seems
        quieter than usual. Whether that is worth a word is this
        module's question; how to put it is the model's.

        Once per stretch, not once a day: see `CHECK_IN_AGAIN_S`. A
        person who is quiet all week produces a fresh low flip most
        evenings, because the evidence decays overnight and builds
        again -- three in three days, each of them legitimately
        inside the 24-hour cooldown.
        """
        payload = message.payload or {}
        person = str(payload.get("person") or "")
        state = str(payload.get("state") or "")
        if state != "low":
            # Back to themselves ends the stretch; `unknown` does not.
            # Overnight the evidence decays below the threshold and the
            # state reads `unknown` until they speak again -- which is
            # the absence of a reading, not a recovery, and treating it
            # as one is what let Sim ask three days running.
            if state in ("usual", "high"):
                self._asked_about.pop(person, None)
            return
        asked = self._asked_about.get(person)
        now = self._ctx.clock.now()
        if asked is not None and (now - asked) < CHECK_IN_AGAIN_S:
            await self._suppress(Notice(kind="check_in", text=state_note(person, payload), person=person),
                                 f"already asked {person} about this stretch "
                                 f"{(now - asked) / 3600.0:.0f}h ago")
            return
        note = state_note(person, payload)
        delivery = await self.offer(Notice(kind="check_in", text=note, person=person,
                                           ref=f"wellbeing:{person}",
                                           weight=float(payload.get("mean") or 0.0)))
        if delivery is not None:
            self._asked_about[person] = now

    # -- the decision ------------------------------------------------------------------
    async def offer(self, notice: Notice, *, situation: Situation | None = None) -> object | None:
        """Consider one notice; the delivery proposed, or None."""
        ctx = self._ctx
        if ctx is None or not notice.text.strip():
            return None
        now = ctx.clock.now()
        day = int(now // 86_400)
        if day != self._day:
            self._day, self._delivered_today = day, 0
        person: Person | None = None
        if notice.kind in PERSONAL:
            # The consent and role gates, again, on the way out: a
            # check-in for a child, a guest, an unknown voice or an adult
            # who has not said yes is refused whatever sent the notice.
            person = await self._person(notice.person)
            why = companion_gate(notice, person)
            if why:
                await self._suppress(notice, why)
                return None
        situation = situation if situation is not None else await self._situation()
        delivery = decide(notice, situation, owner=self._owner, now=now, last_by_kind=self._last_by_kind,
                          delivered_today=self._delivered_today, do_not_disturb=self.do_not_disturb)
        if delivery is None:
            await self._suppress(notice, "nothing was worth interrupting for this right now")
            return None
        text = notice.text
        if notice.kind in COMPOSED:
            text, why = await self._compose(notice, person)
            if why:
                await self._suppress(notice, why)
                return None
        self._last_by_kind[cooldown_key(notice)] = now
        self._delivered_today += 1
        # The decision, before the effect. An `action.proposed` for
        # `speak` looks identical whoever asked for it, so without
        # this nothing downstream can tell a check-in from a reminder
        # -- including anything trying to measure how often Sim gets
        # this right, and including a person reading the log.
        await ctx.bus.publish(Message.new(topics.INITIATIVE_OFFERED, source=ctx.bus.source, payload={
            "kind": notice.kind, "tool": delivery.tool, "person": notice.person or "",
            "to": delivery.to or "", "why": delivery.why, "ref": notice.ref}))
        await ctx.bus.publish(Message.new(topics.ACTION_PROPOSED, source=ctx.bus.source, payload={
            "action_id": uuid.uuid4().hex,
            "tool": delivery.tool,
            # `notify` takes `body`, not `text`, and has no recipient
            # field: it reaches the person who runs Sim. Every
            # unprompted notification since stage 6 item 6 was denied
            # with "$.body: required property missing" -- visible in
            # the creator's log twice in one evening, 2026-09-20 -- so
            # nothing Initiative decided to send ever arrived.
            "args": ({"text": text} if delivery.tool == "speak"
                     else {"body": text, **({"subject": f"for {delivery.to}"} if delivery.to else {})}),
            "scope": {"paths": [], "network": delivery.tool == "notify"},
            "reversibility": "irreversible",
            "rationale": delivery.why,
            "proposed_by": ctx.bus.source,
            # Sim's own idea, not a person's: Guardian weighs an
            # unprompted action differently from one somebody asked for.
            "requester": "", "requester_channel": "initiative",
        }))
        return delivery

    async def _suppress(self, notice: Notice, why: str) -> None:
        ctx = self._ctx
        await ctx.bus.publish(Message.new(topics.INITIATIVE_SUPPRESSED, source=ctx.bus.source, payload={
            "kind": notice.kind, "text": notice.text[:200], "ref": notice.ref, "why": why}))

    async def _compose(self, notice: Notice, person: Person | None) -> tuple[str, str]:
        """One model call turns a state note into the words, or into
        nothing: `(line, "")` or `("", why)`. The line is checked before
        it may become a proposal."""
        ctx = self._ctx
        request = Message.new(topics.COGNITION_THINK, source=ctx.bus.source, payload={
            "purpose": "chat", "messages": [{"role": "user", "content": compose_prompt(notice, person)}],
            "budget": {"max_tokens": COMPOSE_MAX_TOKENS, "max_cost_usd": COMPOSE_MAX_COST_USD},
            "require_real_provider": False, "expected": "text",
        })
        try:
            reply = await ctx.bus.request(request, timeout=COMPOSE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 -- no model, no line; a quiet Sim is the safe Sim
            return "", f"the model did not answer ({type(exc).__name__})"
        if reply.payload.get("ok") is False:
            return "", "the model did not answer"
        return acceptable_line(str(reply.payload.get("text") or ""))

    # -- what the world model knows ----------------------------------------------------
    async def _situation(self) -> Situation:
        """What the house is doing, from World Model; an empty house is
        never assumed -- a facet that does not answer yields no people and
        no flags, which makes the speaker expensive and the phone cheap."""
        data = (await self._world("home") or {}).get("situation") or {}
        return Situation(
            quiet_hours=bool(data.get("quiet_hours")), someone_asleep=bool(data.get("someone_asleep")),
            child_alone=bool(data.get("child_alone")), tv_playing=bool(data.get("tv_playing")),
            people=dict(data.get("people") or {}),
        )

    async def _person(self, name: str) -> Person | None:
        """The Person record behind a name, or None: nobody Sim knows."""
        if not name:
            return None
        reply = await self._world("people", {"name": name})
        record = (reply or {}).get("person")
        return person_from_dict(record) if record else None

    async def _people(self) -> list[Person]:
        reply = await self._world("people")
        return [person_from_dict(p) for p in ((reply or {}).get("people") or [])]

    async def _world(self, what: str, args: dict | None = None) -> dict | None:
        ctx = self._ctx
        try:
            reply = await ctx.bus.request(
                Message.new(topics.WORLD_ENV_QUERY, source=ctx.bus.source, payload={"what": what, "args": args or {}}),
                timeout=0.5)
        except Exception:  # noqa: BLE001 -- no world model, no answer
            return None
        if reply.payload.get("ok") is False:
            return None
        return reply.payload


__all__ = ["COMPOSE_MAX_COST_USD", "COMPOSE_MAX_TOKENS", "COMPOSE_TIMEOUT_S", "Service", "VERSION"]
