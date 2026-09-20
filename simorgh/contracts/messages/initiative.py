"""`initiative.*` -- when Sim speaks first (stage 6 item 6).

A delivery is still an ordinary `action.proposed` with `speak` or
`notify`, because saying something unprompted is an effect like any
other and Guardian gates effects. But the *decision* is a message too
(`initiative.offered`), because a proposal does not say which notice
it came from or who it is for, and for a day that meant a household
could see every word Sim held back and not one it chose to send.
"""

from __future__ import annotations

from .. import topics as t
from ..fields import F, O, Str
from ..registry import define

InitiativeSuppressed = define(t.INITIATIVE_SUPPRESSED, [
    F("kind", Str),
    F("why", Str),
    O("text", Str),
    O("ref", Str),
], doc="Something Sim decided not to say, and why -- so a household can see what it held back, "
       "not only what it said.")

InitiativeOffered = define(t.INITIATIVE_OFFERED, [
    F("kind", Str),
    F("tool", Str),
    O("person", Str),
    O("to", Str),
    O("why", Str),
    O("ref", Str),
], doc="A notice Sim decided to deliver, before the words are composed: which kind, for whom, "
       "and by which channel. The proposal that follows is an effect; this is the judgement.")

__all__ = ["InitiativeOffered", "InitiativeSuppressed"]
