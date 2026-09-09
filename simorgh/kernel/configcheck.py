"""Tell the human when a config section changes nothing.

Every `from_mapping` here ignores a key it does not recognise. That is
the right behaviour for forward compatibility and the wrong behaviour
for a typo: `[planing]` instead of `[planning]`, or `lease_secs`
instead of `lease_seconds`, is silently indistinguishable from a
setting that works. The creator edits the file and the system does
exactly what it did before, with nothing on screen.

The check is a probe rather than a schema, and deliberately so. A
schema would have to be written out by hand for sixteen subsystems and
would go stale the first time a field was added. Instead: build the
config from the empty mapping, build it again from the section as
written, and compare. A non-empty section that produces an identical
config had no effect, whatever the reason -- an unknown key, a
misspelled group, a value the parser rejected.

It reports; it never refuses. A section that cannot even be parsed is
that subsystem's problem to raise at its own boot, not a reason to
stop the whole system here.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

# Keys the Kernel itself consumes, so a section that no subsystem reads
# is not reported against them.
KERNEL_SECTIONS = frozenset({"runtime", "bus", "ledger", "logging", "telemetry"})

# Defaults the Kernel applies to a section before the subsystem sees it
# (`kernel/service.py`), so the probe compares against the baseline that
# will really be in force.
#
# Without this the check was INVERTED on the one switch that matters
# most. `sim.sh` auto-approves by default, so the Kernel sets
# `irreversible_requires_human = False`; the dataclass default is True.
# Writing `true` -- which an observer proved flips a real proposal from
# approved to needs_human -- was reported as "changed nothing", and
# writing `false`, which genuinely changes nothing, was reported as
# working. Anyone trusting the warning would have disabled their own
# safety gate (observer, 2026-09-08).
EFFECTIVE_DEFAULTS: dict[str, dict] = {
    "guardian": {"irreversible_requires_human": False},
}


def _config_classes() -> dict[str, Callable[..., Any]]:
    """Imported here, not at module scope: this runs once at boot and
    should not add sixteen imports to every process that touches the
    Kernel package."""
    from simorgh.cognition.config import Config as CognitionConfig
    from simorgh.curiosity.config import Config as CuriosityConfig
    from simorgh.execution.config import Config as ExecutionConfig
    from simorgh.guardian.config import Config as GuardianConfig
    from simorgh.learning.config import Config as LearningConfig
    from simorgh.memory.config import Config as MemoryConfig
    from simorgh.persona.config import Config as PersonaConfig
    from simorgh.planning.config import Config as PlanningConfig
    from simorgh.reflection.config import Config as ReflectionConfig
    from simorgh.verification.config import VerificationConfig
    from simorgh.worldmodel.config import Config as WorldModelConfig

    return {
        "cognition": CognitionConfig,
        "curiosity": CuriosityConfig,
        "execution": ExecutionConfig,
        "guardian": GuardianConfig,
        "learning": LearningConfig,
        "memory": MemoryConfig,
        "persona": PersonaConfig,
        "planning": PlanningConfig,
        "reflection": ReflectionConfig,
        "verification": VerificationConfig,
        "worldmodel": WorldModelConfig,
    }


def dead_sections(config, *, names: Iterable[str] | None = None) -> list[str]:
    """Section names that were written and had no effect.

    `config` is a `LoadedConfig`; only its `section(name)` is used, so a
    test can pass anything with that method.
    """
    classes = _config_classes()
    dead: list[str] = []
    for name in sorted(names if names is not None else classes):
        cls = classes.get(name)
        if cls is None:
            continue
        section = config.section(name)
        if not section:
            continue
        baseline = dict(EFFECTIVE_DEFAULTS.get(name, {}))
        written = baseline | dict(section)
        try:
            if cls.from_mapping(written) == cls.from_mapping(baseline):
                dead.append(name)
        except Exception:  # noqa: BLE001 -- a section that cannot parse is the subsystem's to report
            continue
    return dead


def report(config, logger) -> list[str]:
    """Log one warning per dead section. Returns them, for the caller
    and for tests."""
    dead = dead_sections(config)
    for name in dead:
        logger.warning(
            "config.section_had_no_effect", section=name,
            detail=f"[{name}] in simorgh.toml changed nothing -- check the key names against "
                   f"simorgh/{name}/config.py",
        )
    return dead


__all__ = ["dead_sections", "report"]
