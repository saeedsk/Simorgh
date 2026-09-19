"""Simorgh ("Sim"): a self-improving personal agent for one household.

Nineteen packages, one per subsystem, composed by the Kernel and sharing
exactly one dependency, `simorgh.contracts`; they talk only through typed
messages on the Bus, and every effect passes Guardian. Start at
docs/ARCHITECTURE.md; each package's CONTRACT.md says what it consumes,
produces, owns and promises.
"""

from __future__ import annotations

__version__ = "2.0.0a0"
