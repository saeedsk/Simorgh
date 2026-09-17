"""Where Sim is, and what this place is called.

Two live failures, the same missing slot.

The creator named his house: "Name Tamagamka as your house." Sim said
"Done -- this house is Tamagamka now", and it was not done, because
there is nowhere to put it. The name survived only as one episodic
record, findable by recall on a good day and gone on a bad one.

Then, 2026-09-16, driving: "voice environment everything is same you're
still in the car I'm driving". Sim answered honestly -- "There's no
setting that stores it, so please just tell me again next session" --
and its own honesty guard had just caught it promising otherwise. Minutes
later, home, it said "good to be back on the house Wi-Fi", which it
inferred from the words alone; it has no way to know a network from a
network.

So: a house name, and a map from a network's name to what being on it
means. `Aranet` is home; `Woody` is the car (the creator's idea). This
is deliberately TOLD, not detected -- nothing in this codebase reads an
SSID, and inventing that capability is a separate question with its own
permissions. What it buys is that telling Sim once is enough.

In `contracts` because the write side (a tool, in Execution) and the
read side (the prompt, in Orchestration) may not import each other --
the same argument as `scratch.py` and `console.py`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .settings import config_path, persist

#: The TOML section these live in: `[household] house_name`, and
#: `[household.networks] Aranet = "home"`.
SECTION = "household"

_cache: tuple[float, dict] | None = None


def _read(path: Path | None = None) -> dict:
    """`[household]` from the settings file, cached on the file's mtime.

    Cached because `place_line()` is asked once per turn and this is a
    file read; keyed on mtime so a `persist()` from the tool is picked
    up on the very next turn, with no restart. That immediacy is the
    point: "tell me again next session" is the failure being fixed.
    """
    global _cache
    target = path or config_path()
    try:
        stamp = target.stat().st_mtime
    except OSError:
        return {}
    if _cache is not None and _cache[0] == stamp:
        return _cache[1]
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    section = dict(data.get(SECTION) or {})
    _cache = (stamp, section)
    return section


def house_name(path: Path | None = None) -> str:
    return str(_read(path).get("house_name") or "").strip()


def networks(path: Path | None = None) -> dict[str, str]:
    """`{"Aranet": "home", "Woody": "the car"}` -- network name to place."""
    raw = _read(path).get("networks") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v).strip() for k, v in raw.items() if str(v).strip()}


def remember_house_name(name: str, path: Path | None = None) -> str:
    clean = " ".join(str(name or "").split())[:60]
    if not clean:
        return ""
    persist(path or config_path(), "house_name", clean, section=SECTION)
    _forget()
    return clean


def remember_network(network: str, place: str, path: Path | None = None) -> tuple[str, str]:
    """`Aranet` -> `home`. Both trimmed; either empty means no change."""
    key = " ".join(str(network or "").split())[:60]
    value = " ".join(str(place or "").split())[:80]
    if not key or not value:
        return "", ""
    known = networks(path)
    known[key] = value
    persist(path or config_path(), "networks", known, section=SECTION)
    _forget()
    return key, value


def forget_network(network: str, path: Path | None = None) -> bool:
    key = " ".join(str(network or "").split())[:60]
    known = networks(path)
    if key not in known:
        return False
    del known[key]
    persist(path or config_path(), "networks", known, section=SECTION)
    _forget()
    return True


def _forget() -> None:
    global _cache
    _cache = None


def place_line(path: Path | None = None) -> str:
    """The prompt line, or "" when nothing has been told yet.

    Says what is known and, crucially, what is not: Sim cannot see which
    network it is on, so it must ask rather than assume. "Good to be back
    on the house Wi-Fi" was a guess dressed as knowledge.
    """
    name = house_name(path)
    known = networks(path)
    if not name and not known:
        return ""
    bits = []
    if name:
        bits.append(f"This house is called {name}.")
    if known:
        listed = "; ".join(f"{net} means {place}" for net, place in sorted(known.items()))
        bits.append(f"Networks you have been told about: {listed}.")
        bits.append("You cannot see which network you are on, so do not claim to know where you "
                    "are -- if it matters, ask.")
    return " ".join(bits)


__all__ = ["SECTION", "forget_network", "house_name", "networks", "place_line",
           "remember_house_name", "remember_network"]
