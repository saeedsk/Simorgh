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


def _collapse_groups(candidates: list[Registered]) -> list[Registered]:
    """Collapse competing subscriptions to one delivery per group:
    the first registered member stands in for the group (the backend
    picks the actual member at dispatch time); broadcast subscriptions
    (group=None) each get their own delivery."""
    out: list[Registered] = []
    seen_groups: set[str] = set()
    for r in candidates:
        if r.spec.group is None:
            out.append(r)
        elif r.spec.group not in seen_groups:
            seen_groups.add(r.spec.group)
            out.append(r)
    return out


def route(message: Message, registered: list[Registered]) -> list[Registered]:
    """The subscriptions this message is delivered to, one entry per
    broadcast subscription and one per competing group (the first
    registered member stands in for the group; the backend picks the
    actual member at dispatch time)."""
    if is_reply_routed(message):
        # Point-to-point, but still one delivery per competing group:
        # a plain pattern loop would fan a reply out to every member.
        return _collapse_groups(
            [r for r in registered if r.spec.pattern == message.reply_to]
        )
    return _collapse_groups(
        [
            r
            for r in registered
            if not is_inbox(r.spec.pattern)  # inboxes only ever receive replies
            and matches(r.spec.pattern, message.type)
        ]
    )


def groups_for(message: Message, registered: list[Registered]) -> set[str]:
    """The competing-consumer groups a message would land in -- what
    backpressure measures depth against."""
    return {r.spec.group for r in route(message, registered) if r.spec.group is not None}


__all__ = ["INBOX_PREFIX", "Registered", "groups_for", "is_inbox", "is_reply_routed", "route"]
