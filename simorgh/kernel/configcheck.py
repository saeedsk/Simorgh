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

# Fields that parse into a real (non-default) value on the Config
# dataclass -- so the whole-section comparison below never flags
# them -- but that no code path ever reads. `[memory] default_k`
# is the first of these (2026-09-08 observer audit): both real
# publishers of `memory.retrieve` (execution/service.py's skill
# lookup, orchestration/context.py's context build) pass `k`
# explicitly, and the wire contract (`contracts/messages/memory.py`)
# declares `k` as a required field, so `Service._on_retrieve`'s
# `payload.get("k", self._config.default_k)` fallback can never
# fire from a real caller. Writing `default_k = 10` changes the
# parsed Config (10 != 5) and would sail through `dead_sections`
# silently -- this list exists so it does not.
#
# Unlike `EFFECTIVE_DEFAULTS`, this is a statement about *data flow*
# (nothing downstream reads the field), which the section-equality
# probe cannot discover on its own -- it has to be told. Add to this
# only when you can point at the specific reason the field is
# unreachable, the way the comment above does; it is not a place to
# park "seems unused."
KNOWN_DEAD_FIELDS: dict[str, frozenset[str]] = {
    "memory": frozenset({"default_k"}),
}


def _config_classes() -> dict[str, Callable[..., Any]]:
    """Imported here, not at module scope: this runs once at boot and
    should not add sixteen imports to every process that touches the
    Kernel package."""
    from simorgh.cognition.config import Config as CognitionConfig
    from simorgh.curiosity.config import Config as CuriosityConfig
    from simorgh.execution.config import Config as ExecutionConfig
    from simorgh.guardian.config import Config as GuardianConfig
    from simorgh.interface.config import Config as InterfaceConfig
    from simorgh.learning.config import Config as LearningConfig
    from simorgh.memory.config import Config as MemoryConfig
    from simorgh.orchestration.config import Config as OrchestrationConfig
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
        "interface": InterfaceConfig,
        "learning": LearningConfig,
        "memory": MemoryConfig,
        "orchestration": OrchestrationConfig,
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


def dead_fields(config, *, names: Iterable[str] | None = None) -> list[tuple[str, str]]:
    """`(section, field)` pairs that were explicitly set to something
    other than their default, and parsed cleanly, but that no code
    path reads (`KNOWN_DEAD_FIELDS`). A section already caught by
    `dead_sections` (an unrecognised key) is skipped here -- it is
    already reported, and this check only adds value for a field that
    genuinely parses into a different, live-looking Config value."""
    classes = _config_classes()
    already_dead = set(dead_sections(config, names=names))
    dead: list[tuple[str, str]] = []
    for name in sorted(names if names is not None else KNOWN_DEAD_FIELDS):
        known = KNOWN_DEAD_FIELDS.get(name)
        if not known or name in already_dead:
            continue
        cls = classes.get(name)
        if cls is None:
            continue
        section = config.section(name)
        if not section:
            continue
        present = known & set(section)
        if not present:
            continue
        baseline = dict(EFFECTIVE_DEFAULTS.get(name, {}))
        try:
            written_cfg = cls.from_mapping(baseline | dict(section))
            baseline_cfg = cls.from_mapping(baseline)
        except Exception:  # noqa: BLE001 -- an unparseable section is the subsystem's to report
            continue
        for field in sorted(present):
            if getattr(written_cfg, field) != getattr(baseline_cfg, field):
                dead.append((name, field))
    return dead


def report(config, logger) -> list[str]:
    """Log one warning per dead section, and one per known-dead field
    in an otherwise-live section. Returns the dead section names, for
    the caller and for tests -- the same contract as before this
    function also checked fields."""
    dead = dead_sections(config)
    for name in dead:
        logger.warning(
            "config.section_had_no_effect", section=name,
            detail=f"[{name}] in simorgh.toml changed nothing -- check the key names against "
                   f"simorgh/{name}/config.py",
        )
    for name, field in dead_fields(config):
        logger.warning(
            "config.field_had_no_effect", section=name, field=field,
            detail=f"[{name}] {field} in simorgh.toml parses but nothing reads it -- see "
                   f"simorgh/kernel/configcheck.py KNOWN_DEAD_FIELDS for why.",
        )
    return dead


__all__ = ["dead_sections", "dead_fields", "report"]
