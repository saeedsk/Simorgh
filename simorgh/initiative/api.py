"""When Sim speaks first, and where (stage 6 item 6).

Four things could interrupt a household before this existed, each with its
own rules and none of them aware of the others: Curiosity's growth notes,
Persona's news sharing, the camera announcer, and reminder delivery. The
question they were all answering badly is one question -- *is this worth
interrupting these people, here, now?* -- so it is answered once, here.

    utility = urgency(class) x relevance(person) - cost(activity, time, channel)

The cost term is what the old code lacked. A camera event at two in the
morning with a child asleep in the room is not worth the speaker, and the
old announcer said it aloud anyway; the same event to the owner's phone
costs almost nothing. So the decision is not "say it or drop it" but
*which channel*, and dropping is what is left when no channel is cheap
enough.

Nothing here talks to a device. It returns a `Delivery`, and the service
proposes it as an ordinary action, so Guardian sees every word Sim says
unprompted exactly as it sees every other effect.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: What a thing is, and how urgent that makes it. Anything unknown is
#: treated as the least urgent class rather than the most.
URGENCY: dict[str, float] = {
    "safety_alert": 1.0,     # smoke, a stranger at the door, water
    "reminder": 0.7,         # the person asked for this, at this time
    "event_fyi": 0.4,        # a camera saw a car; the washing is done
    "growth": 0.15,          # Sim learnt something about itself
    "news": 0.1,             # Sim read something it found interesting
}

#: Channels, cheapest interruption first. `speaker` is the room: it
#: interrupts everyone in it, including people it is not for.
CHANNELS = ("phone", "screen", "speaker")

#: How much each channel costs to use, before the hour and the room.
CHANNEL_COST: dict[str, float] = {"phone": 0.1, "screen": 0.2, "speaker": 0.45}

#: Under this, nothing is delivered: it waits for the digest instead.
WORTH_IT = 0.25

#: A class may not interrupt more often than this, in seconds.
COOLDOWN: dict[str, float] = {"safety_alert": 0.0, "reminder": 0.0, "event_fyi": 15 * 60.0,
                              "growth": 6 * 3600.0, "news": 6 * 3600.0}

#: However interesting the day is, this many unprompted deliveries and no
#: more. A cap the household can feel is better than one they cannot.
DAILY_CAP = 12


@dataclass(frozen=True)
class Situation:
    """What the house is doing, as `world:home` reports it."""

    quiet_hours: bool = False
    someone_asleep: bool = False
    child_alone: bool = False
    tv_playing: bool = False
    people: dict = field(default_factory=dict)      # person -> area

    @property
    def anyone_home(self) -> bool:
        return bool(self.people)


@dataclass(frozen=True)
class Notice:
    """Something Sim might say, before anyone asked."""

    kind: str                   # a key of URGENCY
    text: str
    person: str = ""            # who it is for; "" is the household
    ref: str = ""               # what it came from, for the ledger


@dataclass(frozen=True)
class Delivery:
    """How to say it: a channel, to a person, with the reasoning kept."""

    notice: Notice
    channel: str
    to: str
    utility: float
    why: str

    @property
    def tool(self) -> str:
        return "speak" if self.channel == "speaker" else "notify"


def relevance(notice: Notice, situation: Situation) -> float:
    """How much this matters to the people who would be interrupted."""
    if not notice.person:
        return 1.0 if situation.anyone_home else 0.5
    return 1.0 if notice.person in situation.people else 0.3


def cost(channel: str, situation: Situation, *, now: float | None = None) -> float:
    """What interrupting through `channel` costs right now."""
    base = CHANNEL_COST.get(channel, 0.5)
    if channel == "speaker":
        if situation.quiet_hours or situation.someone_asleep:
            # The room is the one channel that cannot be ignored, and at
            # night it wakes whoever is in it -- including a child asleep
            # on the sofa, which is the case this module exists for.
            base += 0.6
        if not situation.anyone_home:
            base += 0.5      # talking to an empty room is pure noise
        if situation.tv_playing:
            base += 0.1
    if channel == "screen" and not situation.anyone_home:
        base += 0.2
    return base


def decide(notice: Notice, situation: Situation, *, owner: str = "Saeed", now: float | None = None,
           last_by_kind: dict | None = None, delivered_today: int = 0,
           do_not_disturb: set | None = None) -> Delivery | None:
    """The cheapest channel worth using, or None to stay quiet.

    None is a real answer and the common one: most of what Sim notices is
    worth recording and not worth saying.
    """
    now = time.time() if now is None else now
    urgency = URGENCY.get(notice.kind, min(URGENCY.values()))
    dnd = do_not_disturb or set()
    if notice.person and notice.person in dnd and notice.kind != "safety_alert":
        return None
    if delivered_today >= DAILY_CAP and notice.kind != "safety_alert":
        return None
    since = (last_by_kind or {}).get(notice.kind)
    if since is not None and (now - since) < COOLDOWN.get(notice.kind, 0.0):
        return None
    worth = relevance(notice, situation) * urgency
    best: Delivery | None = None
    for channel in CHANNELS:
        if channel == "speaker" and notice.person and notice.person not in situation.people:
            continue        # saying it in a room they are not in is not delivery
        utility = worth - cost(channel, situation, now=now)
        if utility < WORTH_IT:
            continue
        to = notice.person or (owner if channel == "phone" else "the room")
        why = (f"{notice.kind} worth {worth:.2f} against {cost(channel, situation, now=now):.2f} "
               f"to interrupt by {channel}")
        candidate = Delivery(notice=notice, channel=channel, to=to, utility=round(utility, 3), why=why)
        if best is None or candidate.utility > best.utility:
            best = candidate
    if best is None and notice.kind == "safety_alert":
        # A safety alert is never dropped for cost. It goes to the phone,
        # which wakes nobody who is not already holding it.
        return Delivery(notice=notice, channel="phone", to=notice.person or owner, utility=URGENCY["safety_alert"],
                        why="a safety alert always reaches somebody")
    return best


__all__ = ["CHANNELS", "CHANNEL_COST", "COOLDOWN", "DAILY_CAP", "Delivery", "Notice", "Situation", "URGENCY",
           "WORTH_IT", "cost", "decide", "relevance"]
