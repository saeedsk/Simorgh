"""A stdlib token estimator (docs/blueprint/subsystems/04-cognition.md
section 7, "Token estimation without a tokenizer dependency"): chars/4,
which keeps enough headroom in every threshold that a real tokenizer
dependency isn't needed for budgeting purposes (principle 4.14)."""

from __future__ import annotations

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(0, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


__all__ = ["estimate_tokens"]
