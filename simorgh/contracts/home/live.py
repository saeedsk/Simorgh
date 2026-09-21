"""Which live camera sessions are open, and whether anybody is watching.

Here rather than in the Ring domain because two sides need it and they
may not import each other: the domain opens and refreshes the session,
and the dashboard -- which is the only thing that knows a person still
has the page up -- says so. `contracts/home/` already holds what both
sides share (the client, the safety policy, the fake house), and this
is one more of those.

Why it exists at all: the dashboard used to send a keep-alive per
camera every twenty seconds, each one a full `action.proposed` for
Guardian to approve. Four tiles is 720 approvals an hour -- 640 in the
worst measured hour -- every one written to the ledger as its own
`action:` stream, against a stage 1 target of ten per hour. Reading the
decision log for the stage 6 safety numbers meant looking past 838
`ring_live` rows to find the ten that mattered (2026-09-20).

A keep-alive is not a new capability. The session id was minted by an
approved `offer`; keeping an already-open stream open is that same
approval continuing, and approving it again 180 times an hour is not
oversight, it is the log describing a video playing. So the OFFER is
gated, the CLOSE is gated, and in between the process refreshes the
session itself for as long as somebody is watching.
"""

from __future__ import annotations

#: How often an open session is refreshed with the camera's cloud.
KEEPALIVE_EVERY_S = 20.0

#: With no sign of the page for this long, the session is dropped. A
#: browser that closed without saying so must not hold a camera open.
WATCHING_TIMEOUT_S = 90.0

#: `session -> {"camera": str, "watched_at": float, "task": ...}`.
SESSIONS: dict = {}


def opened(session: str, *, camera: str, now: float) -> dict:
    """Remember a session that an approved `offer` just opened."""
    SESSIONS[session] = {"camera": camera, "watched_at": now}
    return SESSIONS[session]


def closed(session: str) -> dict | None:
    """Forget a session. Returns what was known about it, if anything."""
    return SESSIONS.pop(session, None)


def watching(now: float) -> None:
    """Somebody still has the page up.

    Called by the dashboard's own ten-second poll, which it makes for
    its own reasons anyway -- so liveness costs no extra request and
    still comes from the browser rather than from an assumption.
    """
    for state in SESSIONS.values():
        state["watched_at"] = now


def stale(session: str, *, now: float) -> bool:
    """Whether nobody has been seen watching `session` for too long."""
    state = SESSIONS.get(session)
    if state is None:
        return True
    return (now - float(state.get("watched_at") or 0.0)) > WATCHING_TIMEOUT_S


__all__ = ["KEEPALIVE_EVERY_S", "SESSIONS", "WATCHING_TIMEOUT_S", "closed", "opened", "stale", "watching"]
