"""Loads docs/SOUL.md read-only (09-guardian.md section 1: "Guardian is
the constitution made structural"). Never writes to it -- SOUL.md is
itself in `protected_subjects`. This module only needs to prove the
charter was actually read at boot; the directives themselves are
enforced as the concrete rules in `rules.py`, not re-parsed from prose
at decision time.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_SOUL_PATH = Path("docs/SOUL.md")


def load_charter(path: Path = DEFAULT_SOUL_PATH) -> str:
    """Returns the charter text, or an explanatory placeholder if it
    can't be read -- Guardian must still start (fail-closed on
    *decisions*, not on an optional read of prose) since the real
    boundaries live in `Config.protected_subjects`/`denylist`, not in
    parsing this file at runtime."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"[charter unavailable: {exc!r} -- protected_subjects/denylist config remains authoritative]"
