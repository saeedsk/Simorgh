"""`curiosity.*` -- intrinsic motivation and discovery (section 4.13)."""

from __future__ import annotations

from ..fields import Any_, Bool, Enum, F, Float, Int, List, O, Str
from ..registry import define
from .. import topics as t

CuriosityCandidate = define(t.CURIOSITY_CANDIDATE, [
    F("kind", Enum("patch", "research")),
    F("description", Str),
    F("area", Str),
    F("why_this_area", Str),
    F("novelty_score", Float),
    O("subject", Str),
])
CuriosityInterestUpdated = define(t.CURIOSITY_INTEREST_UPDATED, [
    F("topic", Str),
    F("last_followed_up", Float),
    F("items_found", Int),
])
CuriosityShareProposed = define(t.CURIOSITY_SHARE_PROPOSED, [
    F("kind", Enum("growth", "news")),
    F("content_ref", Str),
])
CuriosityDiscoverRequest = define(t.CURIOSITY_DISCOVER_REQUEST, [])
CuriosityDiscoverReply = define(t.CURIOSITY_DISCOVER_REPLY, [F("created", List(Str))])
CuriosityShareRequest = define(t.CURIOSITY_SHARE_REQUEST, [F("kind", Enum("growth", "news"))])
CuriosityShareReply = define(t.CURIOSITY_SHARE_REPLY, [F("shared", Bool), O("content_ref", Str)])
CuriosityInterestAdd = define(t.CURIOSITY_INTEREST_ADD, [
    O("topic", Str),
    O("feed_url", Str),
], doc="Exactly one of topic / feed_url (validated by curiosity).")
CuriosityInterestListRequest = define(t.CURIOSITY_INTEREST_LIST_REQUEST, [])
CuriosityInterestListReply = define(t.CURIOSITY_INTEREST_LIST_REPLY, [F("interests", List(Any_))])
CuriosityInterestFollowUpRequest = define(t.CURIOSITY_INTEREST_FOLLOW_UP_REQUEST, [O("topic", Str)])
CuriosityInterestFollowUpReply = define(t.CURIOSITY_INTEREST_FOLLOW_UP_REPLY, [F("items_found", Int)])
