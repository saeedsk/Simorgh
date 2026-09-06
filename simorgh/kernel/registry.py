"""The one place subsystems are named (docs/blueprint/subsystems/03-kernel.md
sections 3.4/5). `02-system-architecture.md` section 4 rule 4 permits
exactly this module to import another subsystem's `Service` -- every
other Kernel module imports only contracts + bus/ledger clients, like any
other subsystem.

Only `bus` and `ledger` exist as real subsystems as of Phase 0; the
seven-layer `LAYERS` order below is the full target from `02` section 2,
kept complete on purpose so adding Phase 1+ subsystems is a one-line
`FACTORIES` entry, never a reshuffle of this module's shape. A layer
whose names are not (yet) in `FACTORIES` is skipped with a clear log
line, not a crash -- this repository builds subsystems incrementally and
the Kernel has to boot meaningfully at every intermediate point.

Phase 1 packages land here as their own PRs merge -- see
`tests/simorgh/kernel/test_kernel_boot_two_toy_subsystems.py` for the
`mock.patch` injection pattern subsystem-track forks should use in their
own integration tests instead of editing this file concurrently.
"""

from __future__ import annotations

from typing import Callable

from simorgh.bus.client import BusClient
from simorgh.contracts.protocols import Subsystem
from simorgh.ledger.client import LedgerClient

LAYERS: tuple[tuple[str, ...], ...] = (
    ("bus", "ledger"),
    ("cognition", "memory", "worldmodel"),
    ("guardian", "execution", "verification", "planning"),
    ("learning", "reflection", "curiosity"),
    ("persona", "interface"),
    ("orchestration",),
)

# Subsystems whose Context is scoped the per-run HMAC secret (`02` section
# 3; the Kernel is the only other holder, and only for the self-check).
NEEDS_HMAC_SECRET: frozenset[str] = frozenset({"guardian", "execution"})


def build_factories(*, bus_client: BusClient, ledger_client: LedgerClient) -> dict[str, Callable[[], Subsystem]]:
    """Zero-arg constructors per subsystem name, for `Supervisor.start_layer`.
    `bus`/`ledger` wrap the clients the Kernel already built (section 5.1:
    "the Kernel constructs the backend and the clients *before* any
    subsystem" -- their `Service` does not create the bus/ledger, it
    reports health/metrics for the one that already exists). Phase 1+
    entries are added here as their packages land -- e.g.:

        from simorgh.guardian.service import Service as GuardianService
        factories["guardian"] = lambda: GuardianService(...)
    """
    from simorgh.bus.service import Service as BusService
    from simorgh.ledger.service import Service as LedgerService

    return {
        "bus": lambda: BusService(bus_client),
        "ledger": lambda: LedgerService(ledger_client),
    }


def known_layers(factories: dict[str, Callable[[], Subsystem]]) -> tuple[tuple[str, ...], ...]:
    """`LAYERS`, filtered to only the names `factories` can actually
    build -- what the Kernel's boot sequence iterates today."""
    return tuple(tuple(name for name in layer if name in factories) for layer in LAYERS)


__all__ = ["LAYERS", "NEEDS_HMAC_SECRET", "build_factories", "known_layers"]
