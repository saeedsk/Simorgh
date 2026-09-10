"""What a finding is, and how two sightings of the same problem are
recognised as one.

The fingerprint is the whole design. A check runs daily and reports
what it sees; without a stable identity for the *problem*, every run
either creates duplicates or loses the history that makes "still open
after three weeks" and "came back" sayable. So the fingerprint is
derived from what makes the problem that problem -- the asset, the
category, and a discriminator -- and deliberately not from the
evidence, which changes (a certificate's remaining days tick down
without it becoming a different finding).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["info", "low", "medium", "high", "critical"]

#: Weakest first, so severities compare and a score can weight them.
SEVERITIES: tuple[Severity, ...] = ("info", "low", "medium", "high", "critical")

#: `open` -- currently true. `fixed` -- was true, is not any more.
#: `accepted` -- true, and a person has said it is fine, with a reason
#: and an expiry. `regressed` -- was fixed, and is true again.
Status = Literal["open", "fixed", "accepted", "regressed"]

#: Default weights for the posture score. Roughly: one critical finding
#: should dominate the score on its own, because it does.
DEFAULT_WEIGHTS: dict[str, int] = {"critical": 25, "high": 10, "medium": 3, "low": 1, "info": 0}

#: An accepted risk expires, or it becomes a permanent blind spot --
#: which is the same as not having found it.
ACCEPTANCE_DAYS = 90.0


@dataclass(frozen=True)
class Finding:
    """One thing that is true about this system and should not be.

    `evidence` is for a person to verify the finding with, so it must
    be specific -- and it must never contain the thing it is warning
    about. A finding that says "the password `hunter2` is in
    workspace/notes.md" has written the password into a second file.
    """

    category: str            # "api_exposure", "secret_in_workspace", "vault_permissions"
    severity: Severity
    asset: str               # what it is about: "sim:api", "~/.simorgh/vault.age"
    title: str
    evidence: str = ""
    remediation: str = ""
    #: Distinguishes two findings of the same category on the same
    #: asset (two different files with secrets in them). Part of the
    #: fingerprint; the evidence is not.
    discriminator: str = ""
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}; one of {SEVERITIES}")
        if not self.category or not self.asset:
            raise ValueError("a finding needs a category and an asset to be identifiable")

    @property
    def fingerprint(self) -> str:
        """Stable across runs, and across a change in the evidence. A
        certificate's remaining days tick down without it becoming a
        different finding."""
        raw = f"{self.category}\x00{self.asset}\x00{self.discriminator}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def weight(self) -> int:
        return DEFAULT_WEIGHTS.get(self.severity, 0)

    def render(self) -> str:
        line = f"[{self.severity}] {self.title}  ({self.asset})"
        if self.evidence:
            line += f"\n    {self.evidence}"
        return line


def redact(text: str, *, keep: int = 4) -> str:
    """A secret reduced to something a person can recognise but nobody
    can use. Never the value itself: evidence is written to a database
    and read back into a model's context, so a finding that quoted the
    password would be putting it in two more places."""
    text = (text or "").strip()
    if len(text) <= keep:
        return "*" * len(text)
    return text[:keep] + "*" * min(len(text) - keep, 12)


def score(findings, weights: dict | None = None) -> int:
    """0-100, worst to best.

    Subtractive from 100 rather than additive to it: a system with no
    findings scores 100, and every real problem takes something away.
    An additive score has to invent a ceiling and then argue about it.
    """
    weights = weights or DEFAULT_WEIGHTS
    penalty = sum(weights.get(f.severity, 0) for f in findings)
    return max(0, 100 - penalty)


def top_reasons(findings, limit: int = 3) -> list[str]:
    """The findings a person should deal with first -- what a score is
    actually for. A number with no reasons attached is a number nobody
    can act on."""
    ordered = sorted(findings, key=lambda f: (-SEVERITIES.index(f.severity), f.category))
    return [f"{f.severity}: {f.title}" for f in ordered[:limit]]


__all__ = ["ACCEPTANCE_DAYS", "DEFAULT_WEIGHTS", "Finding", "SEVERITIES", "Severity", "Status",
           "redact", "score", "top_reasons"]
