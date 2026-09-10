"""Quiet hours: the `"22:00-07:00"` convention, parsed in one place.

Two subsystems need this and may not import each other. Reflection uses
it to hold back a `warn` alert overnight (`reflection/digest.py`);
Execution's media tools use it to refuse a loud speaker at three in the
morning. Both mean exactly the same thing by the string, and the moment
they each parse it there are two answers to "is it quiet hours" that
can disagree -- which would show up as an alert held back by one rule
and a stereo turned up by the other, in the same minute.

Stdlib only, no state, no I/O: the kind of shared convention
`contracts` exists to hold.
"""

from __future__ import annotations


def parse_quiet_hours(spec: str) -> tuple[int, int] | None:
    """`"22:00-07:00"` -> `(22, 7)`. `""` -> `None`.

    Only the hour matters: a quiet-hours window is a blunt instrument
    by design, and minute precision would invite the belief that it is
    something finer than it is.
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    start, _, end = spec.partition("-")
    try:
        start_h = int(start.strip().split(":")[0])
        end_h = int(end.strip().split(":")[0])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"quiet_hours must look like '22:00-07:00', not {spec!r}") from exc
    for hour in (start_h, end_h):
        if not 0 <= hour <= 23:
            raise ValueError(f"quiet_hours hour out of range in {spec!r}")
    return (start_h, end_h)


def in_quiet_hours(hour: int, window: tuple[int, int] | None) -> bool:
    """Handles the window that wraps midnight, which is the only kind
    anybody actually configures."""
    if window is None:
        return False
    start, end = window
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


__all__ = ["in_quiet_hours", "parse_quiet_hours"]
