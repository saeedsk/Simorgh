"""Simorgh v2 -- the message-driven re-architecture designed in
docs/blueprint/. Sixteen subsystems, one package each, sharing exactly
one dependency: `simorgh.contracts`. See docs/blueprint/00-README.md.

v1 (`src/`) remains the running system until the migration in
docs/blueprint/06-migration-from-v1.md completes.
"""

from __future__ import annotations

__version__ = "2.0.0a0"
