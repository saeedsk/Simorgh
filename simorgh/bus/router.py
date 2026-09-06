"""Subscription routing: which registered subscriptions a message reaches
(docs/blueprint/subsystems/01-bus.md section 5, `router.py`).

Two routing modes, decided by the *message*, not the subscriber:

- Ordinary messages go to every subscription whose pattern matches the
  type (`contracts.topics.matches`: `*` one segment, `#` the rest).
- A reply (`reply_to` set and `correlation_id` set) goes *only* to the
  inbox subscription whose pattern is exactly `reply_to`. Replies are
  point-to-point by definition; fanning them out to whoever subscribed
  to `*.reply` would leak one requester's answers to everyone.

Competing subscriptions (`group` set) are collapsed to one delivery per
group; broadcast subscriptions (`group=None`) each get their own.
"""

from __future__ import annotations

from dataclasses import dataclass

from simorgh.contracts.envelope import Message
from simorgh.contracts.topics import matches

from .api import Handler, SubscriptionSpec

INBOX_PREFIX = "_inbox."


@dataclass
class Registered:
    id: str
    spec: SubscriptionSpec
    handler: Handler


def is_inbox(pattern: str) -> bool:
    return pattern.startswith(INBOX_PREFIX)


def is_reply_routed(message: Message) -> bool:
    return bool(message.reply_to) and bool(message.correlation_id)


def route(message: Message, registered: list[Registered]) -> list[Registered]:
    """The subscriptions this message is delivered to, one entry per
    broadcast subscription and one per competing group (the first
    registered member stands in for the group; the backend picks the
    actual member at dispatch time)."""
    if is_reply_routed(message):
        return [r for r in registered if r.spec.pattern == message.reply_to]
    out: list[Registered] = []
    seen_groups: set[str] = set()
    for r in registered:
        if is_inbox(r.spec.pattern):
            continue  # inboxes only ever receive replies
        if not matches(r.spec.pattern, message.type):
            continue
        if r.spec.group is None:
            out.append(r)
        elif r.spec.group not in seen_groups:
            seen_groups.add(r.spec.group)
            out.append(r)
    return out


def groups_for(message: Message, registered: list[Registered]) -> set[str]:
    """The competing-consumer groups a message would land in -- what
    backpressure measures depth against."""
    return {r.spec.group for r in route(message, registered) if r.spec.group is not None}


__all__ = ["INBOX_PREFIX", "Registered", "groups_for", "is_inbox", "is_reply_routed", "route"]
