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

InitiativeMarkedWrong = define(t.INITIATIVE_MARKED_WRONG, [
    F("ref", Str),
    O("person", Str),
    O("by", Str),
    O("why", Str),
], doc="A household member said one of Sim's unprompted notices was wrong or unwanted "
       "(`people wrong <ref>`). The only measurement of this that is worth anything comes "
       "from the person on the receiving end, so it is recorded as its own event rather "
       "than inferred from silence -- stage 10 item 10's false-alarm rate is a count of these "
       "against `initiative.offered`.")

__all__ = ["InitiativeMarkedWrong", "InitiativeOffered", "InitiativeSuppressed"]
