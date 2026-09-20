"""`initiative.*` -- when Sim speaks first (stage 6 item 6).

Only the suppression is a message: a delivery is an ordinary
`action.proposed` with `speak` or `notify`, because saying something
unprompted is an effect like any other and Guardian gates effects.
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

__all__ = ["InitiativeSuppressed"]
