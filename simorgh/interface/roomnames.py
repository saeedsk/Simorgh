"""The rooms Sim listens in, remembered for Tab.

The creator, 2026-10-04: "room, mute and unmute commands all should allow
room name autocomplete from cli". The completer runs on a keystroke and
cannot wait for the voice service, so it reads this cache: filled by every
`voice.status` reply the interface sees (`room`, `mute ?`, `voice status`)
and refreshed in the background when a Tab finds it older than
`MAX_AGE_S`. A stale answer is a moment old; a blocked keystroke is worse.
"""

from __future__ import annotations

import time

MAX_AGE_S = 10.0

_rooms: list[dict] = []
_at = 0.0
_loop = None
_refresh = None
_pending = False


def remember(rooms) -> None:
    global _rooms, _at
    _rooms = [dict(r) for r in rooms or [] if isinstance(r, dict) and r.get("name")]
    _at = time.monotonic()


def attach(loop, refresh) -> None:
    """`refresh` is a coroutine function that asks the voice service and
    calls `remember`; it runs on `loop`, never on the completer's thread."""
    global _loop, _refresh
    _loop, _refresh = loop, refresh


def _schedule() -> None:
    global _pending
    if _pending or _loop is None or _refresh is None or _loop.is_closed():
        return
    _pending = True

    async def _run() -> None:
        global _pending
        try:
            await _refresh()
        except Exception:  # noqa: BLE001 -- a missed refresh only means an older list
            pass
        finally:
            _pending = False

    try:
        _loop.call_soon_threadsafe(lambda: _loop.create_task(_run()))
    except RuntimeError:
        _pending = False


def known() -> list[dict]:
    """The rooms as last seen, asking for fresh ones if these are old."""
    if time.monotonic() - _at > MAX_AGE_S:
        _schedule()
    return list(_rooms)


def state(room: dict) -> str:
    if room.get("kind") == "satellite" and not room.get("connected", True):
        return "offline"
    if room.get("button_muted"):
        return "muted by its button"
    return "muted" if room.get("muted") else "listening"


def choices(verb: str = "") -> list[tuple[str, str]]:
    """(word, what it is now) for Tab after `mute`, `unmute`, `room` or
    `room mute|unmute`: every room, then `all`. The laptop is offered even
    before the first status reply arrives."""
    rooms = known() or [{"name": "laptop", "kind": "laptop"}]
    out = [(str(r["name"]), state(r)) for r in rooms]
    if verb in ("mute", "unmute"):
        out.append(("all", f"{verb} every room"))
    return out


__all__ = ["MAX_AGE_S", "attach", "choices", "known", "remember", "state"]
