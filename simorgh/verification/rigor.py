"""`select_rigor` (docs/blueprint/subsystems/10-verification.md section
5.2): `max(by_kind[kind], by_reversibility[reversibility])`, clamped by
an env/config override -- this is harness-05 section 4's reversibility-
weighted verification effort: a read-only research finding gets a light
touch, a self-patch gets everything.
"""

from __future__ import annotations

from .api import Rigor, VerifyRequest
from .config import VerificationConfig

_ORDER = [Rigor.NONE, Rigor.LIGHT, Rigor.STANDARD, Rigor.FULL]


def _max(a: Rigor, b: Rigor) -> Rigor:
    return a if _ORDER.index(a) >= _ORDER.index(b) else b


def select_rigor(req: VerifyRequest, config: VerificationConfig) -> Rigor:
    if config.forced_rigor is not None:
        return config.forced_rigor
    by_kind = config.rigor_by_kind.get(req.kind, Rigor.STANDARD)
    by_reversibility = config.rigor_by_reversibility.get(req.reversibility, Rigor.STANDARD)
    return _max(by_kind, by_reversibility)
