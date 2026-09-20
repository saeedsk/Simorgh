"""When Sim speaks first, and where (stage 6 item 6; stage 10 item 3).

Four things could interrupt a household before this existed, each with its
own rules and none of them aware of the others: Curiosity's growth notes,
Persona's news sharing, the camera announcer, and reminder delivery. The
question they were all answering badly is one question -- *is this worth
interrupting these people, here, now?* -- so it is answered once, here.

    utility = urgency(class) x relevance(person) x weight [x reach(channel)] - cost(activity, time, channel)

The cost term is what the old code lacked. A camera event at two in the
morning with a child asleep in the room is not worth the speaker, and the
old announcer said it aloud anyway; the same event to the owner's phone
costs almost nothing. So the decision is not "say it or drop it" but
*which channel*, and dropping is what is left when no channel is cheap
enough.

Stage 10 adds the two classes that make Sim a companion rather than an
assistant: a `check_in` (an adult who said yes seems quieter than their
usual, and the World Model's posterior says so) and an `interest_share`
(something turned up about what a person cares about). Both are
*personal* -- their cooldown is per person -- and *private*: the speaker
is used only when the person is alone in their area, and it is cheaper
then, because a quiet word to one person alone interrupts nobody else.
Both are *composed*: the notice carries a state note, never the words to
say; the model writes those, and may write nothing. The `weight` on a
check-in is the posterior mean itself, so a weak reading stays quiet and a
strong one is worth a phone message even when the room is not.

Nothing here talks to a device. It returns a `Delivery`, and the service
proposes it as an ordinary action, so Guardian sees every word Sim says
unprompted exactly as it sees every other effect.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from simorgh.contracts.people import Person, may_check_in, may_share_interest

#: What a thing is, and how urgent that makes it. Anything unknown is
#: treated as the least urgent class rather than the most.
URGENCY: dict[str, float] = {
    "safety_alert": 1.0,     # smoke, a stranger at the door, water
    "check_in": 0.8,         # somebody who said yes seems quieter than usual (weighted by the posterior)
    "reminder": 0.7,         # the person asked for this, at this time
    "event_fyi": 0.4,        # a camera saw a car; the washing is done
    "interest_share": 0.55,  # something about what a person cares about
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

#: A class may not interrupt more often than this, in seconds. A
#: personal class keeps the cooldown per person (`cooldown_key`).
COOLDOWN: dict[str, float] = {"safety_alert": 0.0, "reminder": 0.0, "event_fyi": 15 * 60.0,
                              "growth": 6 * 3600.0, "news": 6 * 3600.0,
                              "check_in": 24 * 3600.0, "interest_share": 8 * 3600.0}

#: However interesting the day is, this many unprompted deliveries and no
#: more. A cap the household can feel is better than one they cannot.
DAILY_CAP = 12

#: The companion classes (stage 10 item 3). Personal: the cooldown is per
#: person. Private: the speaker only when the person is alone in their
#: area, and cheaper then. Composed: the notice's text is a state note
#: for the model, never the words to say.
PERSONAL: frozenset[str] = frozenset({"check_in", "interest_share"})
PRIVATE: frozenset[str] = PERSONAL
COMPOSED: frozenset[str] = PERSONAL

#: What a quiet word to one person alone saves on the speaker's cost.
ALONE_DISCOUNT = 0.2

#: How much of a personal notice actually reaches its person by each
#: channel, right now. A word spoken to somebody in the room lands; a
#: phone message may sit unread for an hour; a screen may not be looked
#: at. Without this the phone, being cheapest, would win every private
#: word even with the person standing alone in the kitchen. Personal
#: classes only: the household classes keep stage 6's arithmetic.
REACH: dict[str, float] = {"speaker": 1.0, "screen": 0.5, "phone": 0.6}

#: A composed line may not name a condition. This is a floor, not the
#: fix -- the fix is the prompt and the creator's corpus (stage 10 items
#: 6 and 9) -- but a line that trips it never becomes a proposal.
FORBIDDEN_WORDS: tuple[str, ...] = ("diagnos", "depress", "anxi", "disorder", "therap", "medicat", "clinical",
                                    "mental health", "bipolar", "trauma")
#: The model's way of saying "nothing fits"; a fine answer, and the common one.
NOTHING = "NOTHING"
#: A composed line is a sentence or two, not a speech.
LINE_MAX_CHARS = 300


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
    text: str                   # the words, or for a COMPOSED class the state note
    person: str = ""            # who it is for; "" is the household
    ref: str = ""               # what it came from, for the ledger
    weight: float = 1.0         # how much the evidence is worth (a check-in: the posterior mean)


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


def alone(person: str, situation: Situation) -> bool:
    """Whether `person` is placed somewhere nobody else is. Somebody the
    house cannot place is not alone: `unknown` is not `yes`."""
    area = situation.people.get(person)
    if not area:
        return False
    return all(a != area for p, a in situation.people.items() if p != person)


def cost(channel: str, situation: Situation, *, now: float | None = None, private_to: str = "") -> float:
    """What interrupting through `channel` costs right now. `private_to`
    names the one person a private word is for: the speaker is cheaper
    when they are alone in the room, because it then interrupts only
    them."""
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
        if private_to and alone(private_to, situation):
            base -= ALONE_DISCOUNT
    if channel == "screen" and not situation.anyone_home:
        base += 0.2
    return max(0.0, base)


def cooldown_key(notice: Notice) -> str:
    """What a class's cooldown is keyed on: the class, or for a personal
    class the class and the person -- a check-in with Soodeh does not
    silence one with Saeed."""
    return f"{notice.kind}:{notice.person}" if notice.kind in PERSONAL and notice.person else notice.kind


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
    since = (last_by_kind or {}).get(cooldown_key(notice))
    if since is not None and (now - since) < COOLDOWN.get(notice.kind, 0.0):
        return None
    worth = relevance(notice, situation) * urgency * max(0.0, min(1.0, notice.weight))
    private_to = notice.person if notice.kind in PRIVATE else ""
    best: Delivery | None = None
    for channel in CHANNELS:
        if channel == "speaker" and notice.person and notice.person not in situation.people:
            continue        # saying it in a room they are not in is not delivery
        if channel == "speaker" and private_to and not alone(private_to, situation):
            continue        # a private word is not said in front of somebody else
        channel_cost = cost(channel, situation, now=now, private_to=private_to)
        reach = REACH.get(channel, 1.0) if notice.kind in PERSONAL else 1.0
        utility = worth * reach - channel_cost
        if utility < WORTH_IT:
            continue
        to = notice.person or (owner if channel == "phone" else "the room")
        why = f"{notice.kind} worth {worth:.2f} against {channel_cost:.2f} to interrupt by {channel}"
        candidate = Delivery(notice=notice, channel=channel, to=to, utility=round(utility, 3), why=why)
        if best is None or candidate.utility > best.utility:
            best = candidate
    if best is None and notice.kind == "safety_alert":
        # A safety alert is never dropped for cost. It goes to the phone,
        # which wakes nobody who is not already holding it.
        return Delivery(notice=notice, channel="phone", to=notice.person or owner, utility=URGENCY["safety_alert"],
                        why="a safety alert always reaches somebody")
    return best


# -- the companion classes (stage 10 item 3) ---------------------------------------------
def companion_gate(notice: Notice, person: Person | None) -> str:
    """Why a personal notice may not go to `person`, or "" when it may.

    The same gates the wellbeing facet applies on the way in
    (`contracts.people`), applied again here on the way out: a check-in
    is for an adult who said yes, a share for the family with the grant,
    and nobody Sim cannot place gets either. Defence in depth, because a
    notice can arrive from more than one place.
    """
    if notice.kind not in PERSONAL:
        return ""
    if not notice.person:
        return f"a {notice.kind} needs a person"
    ok, why = may_check_in(person) if notice.kind == "check_in" else may_share_interest(person)
    return "" if ok else why


def matches_interest(text: str, interests) -> str:
    """The first of `interests` that `text` is about, or "". Lexical and
    deliberately plain: an interest is a short topic, and a share about it
    names it."""
    low = (text or "").lower()
    if not low:
        return ""
    for interest in interests or ():
        words = [w for w in re.findall(r"[a-z0-9]+", str(interest).lower()) if len(w) > 2]
        if words and all(re.search(rf"\b{re.escape(w)}", low) for w in words):
            return str(interest)
    return ""


def state_note(person: str, estimate: dict) -> str:
    """The note a check-in carries for the model: what Sim noticed, with
    the numbers it rests on and no words of the person's."""
    mean = float(estimate.get("mean") or estimate.get("low") or 0.0)
    evidence = float(estimate.get("evidence") or 0.0)
    return (f"{person} seems quieter than usual to you lately: about {mean:.0%} of roughly {evidence:.0f} "
            f"recent turns were shorter or slower than their own usual. You do not know why, or how they feel.")


def compose_prompt(notice: Notice, person: Person | None) -> str:
    """What the model is asked, for a composed class. Ask, do not tell."""
    name = notice.person or "them"
    role = person.role if person is not None else "adult"
    if notice.kind == "check_in":
        because = notice.text
        rules = ("One or two short, warm sentences to them, in plain words. Ask, do not tell: an opening, "
                 "not a verdict. You do not know how they feel -- only that they seem a little quieter than "
                 "usual to you. Never name a condition, never diagnose, never advise, never mention data, "
                 "counts or percentages, never say you have been monitoring them.")
    else:
        because = f"you came across something about what they care about: {notice.text}"
        rules = ("One or two short sentences, light and friendly, that mention it and leave them room to pick "
                 "it up or not. No hard sell, no lecture.")
    return (f"You are Sim, part of this family. You are about to say one thing to {name} ({role}), unprompted, "
            f"because {because}\n{rules}\nIf nothing fits right now, reply exactly {NOTHING}.\n"
            f"Reply with the sentence only.")


def acceptable_line(text: str) -> tuple[str, str]:
    """`(line, "")` for a composed line Sim may say, or `("", why)`. The
    model may decline; a line that names a condition, runs long, or is
    empty is refused here and recorded as suppressed."""
    line = " ".join((text or "").split()).strip().strip('"').strip()
    if not line or line.upper().rstrip(".!") == NOTHING:
        return "", "the model had nothing worth saying"
    low = line.lower()
    for word in FORBIDDEN_WORDS:
        if word in low:
            return "", f"the line named a condition ({word.strip()})"
    if len(line) > LINE_MAX_CHARS:
        return "", f"the line ran long ({len(line)} chars)"
    return line, ""


__all__ = ["ALONE_DISCOUNT", "CHANNELS", "CHANNEL_COST", "COMPOSED", "COOLDOWN", "DAILY_CAP", "Delivery",
           "FORBIDDEN_WORDS", "LINE_MAX_CHARS", "NOTHING", "Notice", "PERSONAL", "PRIVATE", "REACH", "Situation",
           "URGENCY",
           "WORTH_IT", "acceptable_line", "alone", "companion_gate", "compose_prompt", "cooldown_key", "cost",
           "decide", "matches_interest", "relevance", "state_note"]
