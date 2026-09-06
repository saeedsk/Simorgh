"""The user model (theory of mind) -- a confidence-weighted facet store
(spec section 4's `UserModelProjection`: last-write-wins per facet,
confidence merged as max(old*0.9, new); a lower-confidence conflicting
value halves the prior). Facet extraction this session is honest and
narrow: simple pattern matching on explicit statements ("I prefer X",
"call me X") rather than anything LLM-driven -- Persona never calls
Cognition (section 2's "never in the call path").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PREFER_RE = re.compile(r"\bi prefer\s+(.+?)[.!]?$", re.IGNORECASE)
_CALL_ME_RE = re.compile(r"\bcall me\s+(\w+)", re.IGNORECASE)


@dataclass(frozen=True)
class Facet:
    value: object
    confidence: float
    updated_at: float
    source_ref: str = ""


class UserModel:
    def __init__(self) -> None:
        self._facets: dict[str, Facet] = {}

    def facets(self) -> dict[str, Facet]:
        return dict(self._facets)

    def observe(self, facet: str, value, confidence: float, *, source_ref: str = "", ts: float = 0.0) -> Facet:
        existing = self._facets.get(facet)
        if existing is not None and existing.value == value:
            confidence = min(1.0, max(existing.confidence * 0.9, confidence))
        elif existing is not None:
            confidence = existing.confidence * 0.5  # a conflicting observation lowers the prior, doesn't erase it
        record = Facet(value=value, confidence=confidence, updated_at=ts, source_ref=source_ref)
        self._facets[facet] = record
        return record

    def register(self, *, min_confidence: float = 0.5) -> str:
        f = self._facets.get("register")
        if f is not None and f.confidence >= min_confidence:
            return f.value
        return "neutral"

    def extract_from_text(self, text: str, *, ts: float, source_ref: str) -> list[tuple[str, object]]:
        """Returns [(facet, value)] pairs found by simple pattern
        matching -- honest and narrow by design (see module docstring)."""
        found = []
        m = _PREFER_RE.search(text)
        if m:
            found.append(("preference", m.group(1).strip()))
        m = _CALL_ME_RE.search(text)
        if m:
            found.append(("preferred_name", m.group(1).strip()))
        for facet, value in found:
            self.observe(facet, value, 0.7, source_ref=source_ref, ts=ts)
        return found
