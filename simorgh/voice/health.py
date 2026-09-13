"""Why the machine is slow, when it is: the notes a person needs beside
a 45-second transcription.

2026-09-13, 15:14: every spoken turn took 45-50 s to hear. whisper,
Kokoro and Chatterbox were all fine; the MacBook's battery was at 2%
and macOS had throttled the GPU to a fifteenth of its speed (a Metal
matrix multiply ran at 0.3 TFLOPS). Nothing in Sim said so. This reads
the power state (macOS `pmset`, best effort, cached for a minute) so
`voice status` and a slow turn's line on the screen can."""

from __future__ import annotations

import re
import shutil
import subprocess
import time

#: a hearing this slow gets a note on the screen
SLOW_STT_S = 8.0
#: below this charge macOS throttles the GPU hard, charger or not
LOW_BATTERY_PCT = 20

_cache: tuple[float, dict] = (0.0, {})


def power_state() -> dict:
    """`{"battery_pct": int | None, "charging": bool | None, "source": str}`;
    empty on a machine without `pmset` or when it fails."""
    global _cache
    now = time.monotonic()
    if now - _cache[0] < 60.0:
        return dict(_cache[1])
    state: dict = {}
    pmset = shutil.which("pmset")
    if pmset:
        try:
            out = subprocess.run([pmset, "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"(\d+)%;\s*([A-Za-z ]+?);", out)
            if m:
                state["battery_pct"] = int(m.group(1))
                phase = m.group(2).lower()
                state["charging"] = ("charging" in phase or "charged" in phase) and "dis" not in phase and "not " not in phase
            src = re.search(r"drawing from '([^']+)'", out)
            if src:
                state["source"] = src.group(1)
        except (OSError, subprocess.SubprocessError, ValueError):
            state = {}
    _cache = (now, state)
    return dict(state)


def machine_notes() -> list[str]:
    """Human lines about what is slowing the machine down; [] when nothing known."""
    notes: list[str] = []
    state = power_state()
    pct = state.get("battery_pct")
    if isinstance(pct, int) and pct <= LOW_BATTERY_PCT:
        notes.append(f"battery at {pct}%: macOS throttles the GPU hard until it charges -- hearing and speaking run "
                     f"many times slower ({'charging' if state.get('charging') else 'not charging'})")
    return notes


def slow_hearing_note(stt_seconds: float) -> str:
    """"" or why a transcription took `stt_seconds`."""
    if stt_seconds < SLOW_STT_S:
        return ""
    reasons = machine_notes()
    head = f"hearing took {stt_seconds:.0f} s"
    return head + (": " + reasons[0] if reasons else " -- the machine is busy or throttled (`voice status` shows what it knows)")


__all__ = ["LOW_BATTERY_PCT", "SLOW_STT_S", "machine_notes", "power_state", "slow_hearing_note"]
