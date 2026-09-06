"""Fuzzy dedupe (spec section 5.6, port of v1's `_creative_agenda_already_covered`,
`src/main.py`). Free-form LLM prose paraphrases the same idea differently
each time -- exact substring matching (discovery.py's own, correctly
stricter, `_already_covered` for machine-generated text) never catches
it; `difflib.SequenceMatcher` does. Threshold 0.45 was measured in v1
against real near-duplicate pairs (0.45-0.72) vs. unrelated ones
(0.13-0.27) -- see docs/EVOLUTION.md milestone 95."""

from __future__ import annotations

import difflib
from typing import Iterable


def is_duplicate(candidate: str, existing: Iterable[str], threshold: float) -> bool:
    return any(
        difflib.SequenceMatcher(None, candidate, other).ratio() >= threshold
        for other in existing
    )


__all__ = ["is_duplicate"]
