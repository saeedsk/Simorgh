"""The one place subsystems are named (docs/blueprint/subsystems/03-kernel.md
sections 3.4/5). `02-system-architecture.md` section 4 rule 4 permits
exactly this module to import another subsystem's `Service` -- every
other Kernel module imports only contracts + bus/ledger clients, like any
other subsystem.

All sixteen subsystems from `02` section 2 are real as of the initial
v2 build (contracts/bus/ledger/kernel in Phase 0; the remaining twelve
built concurrently by separate tracks against the frozen Phase 0
contracts, each proving itself against a real Kernel boot in its own
integration test before this file ever named it). The seven-layer
`LAYERS` order below is unchanged from the Phase 0 draft -- it was
already the full target, kept complete on purpose so adding a
subsystem was always meant to be a one-line `FACTORIES` entry, never a
reshuffle of this module's shape. A layer whose names are not (yet) in
`FACTORIES` is skipped with a clear log line, not a crash -- useful
now for any future subsystem replaced or temporarily pulled out, not
just during the original incremental build.

Every constructor below is called with no arguments (or only the
optional keyword defaults each `Service` already declares) --
bus/ledger access is not a constructor argument for any subsystem
except `bus`/`ledger` themselves (a real bootstrapping special case:
their `Service` wraps the client the Kernel already built, rather than
receiving it via `start(ctx)` like every other subsystem does). This
mirrors `test_kernel_boot_two_toy_subsystems.py`'s own pattern; that
test's `mock.patch` injection seam remains available for a test that
wants to substitute a fake for one subsystem without booting the rest.
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
    ("persona", "benchmark", "interface"),
    ("orchestration",),
)

# Subsystems whose Context is scoped the per-run HMAC secret (`02` section
# 3; the Kernel is the only other holder, and only for the self-check).
NEEDS_HMAC_SECRET: frozenset[str] = frozenset({"guardian", "execution"})

# Secrets a subsystem always receives, without anyone having to write a
# `[<subsystem>] secrets = [...]` line in `simorgh.toml`. The scoped
# store (`kernel/secrets.py::ScopedSecretStore`) is deliberately
# deny-by-default, which is right for anything optional -- but a secret
# the subsystem's *own* code names, and whose absence it already handles,
# gains nothing from a second declaration a person has to remember. A
# missing entry here is how a feature ships switched off with no way to
# switch it on but an undocumented config line.
#
# `SIM_API_TOKEN` gates `interface/httpapi.py`
# (platform-connectors-design.md section 4). Absent, the dashboard
# behaves exactly as it always has -- local and unauthenticated.
DEFAULT_SECRETS: dict[str, frozenset[str]] = {
    "interface": frozenset({"SIM_API_TOKEN"}),
    # Execution is where credentials are actually used: every
    # account-backed tool runs here. `vault:*` covers the encrypted
    # store's own namespace (`vault:imap:fastmail:password`) and nothing
    # else -- an ordinary env secret still has to be declared. The
    # alternative is a `simorgh.toml` line per mailbox, which is a line
    # people forget and then report the feature as broken.
    "execution": frozenset({"vault:*"}),
}


def build_factories(
    *, bus_client: BusClient, ledger_client: LedgerClient, run_repl: bool = False,
    execution_config: object | None = None, guardian_config: object | None = None,
) -> dict[str, Callable[[], Subsystem]]:
    """Zero-arg constructors per subsystem name, for `Supervisor.start_layer`.
    `bus`/`ledger` wrap the clients the Kernel already built (section 5.1:
    "the Kernel constructs the backend and the clients *before* any
    subsystem" -- their `Service` does not create the bus/ledger, it
    reports health/metrics for the one that already exists). Every other
    entry constructs its `Service` with defaults; richer wiring (real
    Cognition providers, a non-default Guardian pipeline) is deliberately
    a later, separate configuration change, not something this
    composition point should hardcode.

    `execution_config` and `guardian_config` are the exceptions, each
    added for the same reason: `Kernel.boot` passes
    `execution.Config.from_mapping(self.config.section("execution"))`
    (MCP server config -- `execution/mcp.py`'s module docstring,
    `execution/README.md`'s "MCP servers" section) and
    `guardian.config.Config.from_mapping(self.config.section("guardian"))`
    (the approval-gate switches -- `guardian/config.py`'s own
    `SIMORGH_GUARDIAN_AUTO_APPROVE` docstring), the same
    `simorgh.toml`-section pattern `bus`/`ledger`/`orchestration` already
    use elsewhere in this file's caller -- so a human can add an
    `[execution] mcp_servers` or `[guardian] irreversible_requires_human`
    entry to `simorgh.toml` instead of editing this file's lambda
    directly. `None` (every caller other than `Kernel.boot` -- tests,
    `--self-check`) means each `Service()`'s own default `Config()`.

    `run_repl` defaults False -- a blocking `readline` loop must never
    start under a test or `--self-check` boot, where nothing will ever
    type into it. Only `python -m simorgh run`, the one entry point whose
    entire purpose is an interactive session, passes `run_repl=True`
    (via `Kernel(..., interactive=True)`); every other caller (`status`,
    `trace`, `migrate-v1`, every test, self-check) leaves the default.
    """
    from simorgh.benchmark.service import Service as BenchmarkService
    from simorgh.bus.service import Service as BusService
    from simorgh.cognition.service import Service as CognitionService
    from simorgh.curiosity.service import Service as CuriosityService
    from simorgh.execution.service import Service as ExecutionService
    from simorgh.guardian.service import Service as GuardianService
    from simorgh.interface.service import Service as InterfaceService
    from simorgh.learning.service import Service as LearningService
    from simorgh.ledger.service import Service as LedgerService
    from simorgh.memory.service import Service as MemoryService
    from simorgh.orchestration.service import Service as OrchestrationService
    from simorgh.persona.service import Service as PersonaService
    from simorgh.planning.service import Service as PlanningService
    from simorgh.reflection.service import Service as ReflectionService
    from simorgh.verification.service import VerificationService
    from simorgh.worldmodel.service import Service as WorldModelService

    return {
        "bus": lambda: BusService(bus_client),
        "ledger": lambda: LedgerService(ledger_client),
        "cognition": lambda: CognitionService(),
        "memory": lambda: MemoryService(),
        "worldmodel": lambda: WorldModelService(),
        "guardian": lambda: GuardianService(config=guardian_config),
        "execution": lambda: ExecutionService(config=execution_config),
        "verification": lambda: VerificationService(),
        "planning": lambda: PlanningService(),
        "learning": lambda: LearningService(),
        "reflection": lambda: ReflectionService(),
        "curiosity": lambda: CuriosityService(),
        "persona": lambda: PersonaService(),
        "benchmark": lambda: BenchmarkService(),
        "interface": lambda: InterfaceService(run_repl=run_repl, wait_for_boot=run_repl),
        "orchestration": lambda: OrchestrationService(),
    }


def known_layers(factories: dict[str, Callable[[], Subsystem]]) -> tuple[tuple[str, ...], ...]:
    """`LAYERS`, filtered to only the names `factories` can actually
    build -- what the Kernel's boot sequence iterates today."""
    return tuple(tuple(name for name in layer if name in factories) for layer in LAYERS)


__all__ = ["DEFAULT_SECRETS", "LAYERS", "NEEDS_HMAC_SECRET", "build_factories", "known_layers"]
