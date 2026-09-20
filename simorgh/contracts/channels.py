"""Every way a person can reach Sim, named once.

The creator, 2026-09-16: "CHANGE THE CONTRACT AND INTRODUCE EXTERNAL
VOICE/TEXT CHANNELS LIKE WHATSAPP AND TELEGRAM" -- after telling Sim, by
voice, what it was for: "sometimes instead of bringing my macbook to my
car to talk to you ... maybe i can connect you to a whatsapp application
so basically i leave you home somewhere with internet connection but then
i talk to you over whatsapp".

`percept.text.received`'s `channel` is a CLOSED enum, and that is
deliberate. A live bug published `channel="dashboard"` -- a value that
was never in the enum -- and every publish 500'd on contract validation
until it was noticed. Closing the enum is what caught it. So a channel is
added HERE, in one place, and the enum is built from this module: a new
channel stays one line, and a typo still fails loudly instead of
becoming a permanent third kind of "chat".

What makes a channel EXTERNAL is not its transport but its trust. `cli`
and `voice` need someone at this keyboard or in this room; the house
already admitted them. WhatsApp and Telegram need only that somebody
knows an address. An external channel is therefore a remote control of
this house -- the cameras, the doors' lights, the TV, the backlog --
offered to whoever sends a message. `allowed()` is the check that stands
in front of that, and it denies by default: a channel with no configured
senders admits nobody, rather than everybody.
"""

from __future__ import annotations

from typing import Iterable

#: Someone in the room, or at this machine's keyboard.
CLI = "cli"
VOICE = "voice"
#: Sim's own surfaces on this machine: the dashboard's chat box, a task's
#: own chat, a routed command.
API = "api"
CHAT = "chat"
COMMAND = "command"
#: From outside, over somebody's phone.
WHATSAPP = "whatsapp"
TELEGRAM = "telegram"

LOCAL: tuple[str, ...] = (CLI, VOICE, API, CHAT, COMMAND)
EXTERNAL: tuple[str, ...] = (WHATSAPP, TELEGRAM)
ALL: tuple[str, ...] = LOCAL + EXTERNAL

#: What a channel is called in a sentence a person reads or hears. Sim
#: says "on WhatsApp", never "on channel whatsapp".
DISPLAY: dict[str, str] = {
    CLI: "the terminal",
    VOICE: "the room",
    API: "the dashboard",
    CHAT: "chat",
    COMMAND: "a command",
    WHATSAPP: "WhatsApp",
    TELEGRAM: "Telegram",
}


def is_known(channel: str) -> bool:
    return (channel or "").strip().lower() in ALL


def is_external(channel: str) -> bool:
    """True for a channel that arrives from off this machine.

    The distinction a caller actually wants: not "which vendor" but
    "did this come from someone the house has already admitted".
    """
    return (channel or "").strip().lower() in EXTERNAL


def display(channel: str) -> str:
    """The channel's name for a person. An unknown one is described, not
    guessed at: a channel Sim cannot name is not one it should claim."""
    return DISPLAY.get((channel or "").strip().lower(), "another channel")


def normalise_sender(sender: str) -> str:
    """One spelling for an address that people and vendors write several
    ways.

    A phone number reaches us as `+1 (415) 555-0123` from one API and
    `14155550123` from another, and the creator will type a third form
    into settings. A Telegram handle arrives as `@Saeed` or `Saeed`.
    Comparing those raw means an allow-list that looks right and admits
    nobody -- which, for a deny-by-default gate, fails closed and
    silently. So both sides go through here before they ever meet.

    Digits win when a value is phone-shaped: `+`, spaces, dashes,
    brackets and dots are punctuation people add, not identity.
    """
    text = (sender or "").strip().lower()
    if not text:
        return ""
    if text.startswith("@"):
        text = text[1:]
    stripped = text.lstrip("+")
    digits = "".join(c for c in stripped if c.isdigit())
    if digits and all(c.isdigit() or c in " -(). " for c in stripped):
        return digits
    return text


def person_for(sender: str) -> str:
    """The household name behind an address, or "".

    Every channel namespaces what it remembers by person (stage 5 item 7),
    and the typed channels know who is writing: an allow-list is a list of
    people. A handle that matches a household name IS that person.

    An address that matches nobody yields nothing, not the address: a phone
    number or a chat handle must never reach the bus (`test_no_phone_number
    _ever_reaches_the_bus`), where it would be written to the ledger and
    into memory tags for ever. An unclaimed sender is simply unnamed.
    """
    from .household import HOUSEHOLD

    handle = normalise_sender(sender)
    if not handle:
        return ""
    for member in HOUSEHOLD:
        if normalise_sender(member.name) == handle:
            return member.name
    return ""


def allowed(sender: str, allow: Iterable[str]) -> bool:
    """Whether `sender` may drive Sim over an external channel.

    Deny by default, and deliberately so. The failure this prevents is
    not subtle: an external channel with an empty allow-list that
    defaulted to "anyone" would hand the cameras, the lights and the
    task queue to any stranger who found the number -- and it would look
    like it was working, because it would answer them.

    An empty allow-list therefore means the channel is configured but
    admits nobody, which shows up immediately as "it ignores me" rather
    than never showing up at all.
    """
    who = normalise_sender(sender)
    if not who:
        return False
    return who in {normalise_sender(a) for a in allow if str(a or "").strip()}


__all__ = ["person_for", 
    "ALL", "API", "CHAT", "CLI", "COMMAND", "DISPLAY", "EXTERNAL", "LOCAL",
    "TELEGRAM", "VOICE", "WHATSAPP",
    "allowed", "display", "is_external", "is_known", "normalise_sender",
]
