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
    # 2026-09-08 whole-config audit (same method as `default_k` above:
    # grep every field's read site across the WHOLE repo, not just its
    # own package). Each entry below cites the specific place the field
    # should have been read and confirms nothing reads it there.
    #
    # `bus.stop()` (`bus/client.py`) takes its own `drain_seconds`
    # keyword (default `None`) that nothing in its body actually uses,
    # and every real caller (`kernel/service.py`, `kernel/supervisor.py`,
    # `kernel/selfcheck.py`, `kernel/cli.py`) calls `.stop()` with no
    # arguments -- `Config.drain_seconds` is never read to fill that
    # keyword, so the `[bus] drain_seconds` setting has no path to any
    # running code at all.
    #
    # `bus.metrics_interval_seconds` should reach `BusService`'s
    # `metrics_interval` constructor argument (`bus/service.py`, which
    # defaults it to `15.0` independently), but `kernel/registry.py`
    # constructs it as `BusService(bus_client)` -- the keyword is never
    # passed, so the config value that feeds `Config.metrics_interval_
    # seconds` never reaches the loop it is named for.
    "bus": frozenset({"drain_seconds", "metrics_interval_seconds"}),
    # `execution/verifier.py`'s `ApprovalVerifier.verify` checks
    # `now > float(expires_at)` using the `expires_at` Guardian put on
    # the approval message (governed by `guardian.Config.approval_ttl_s`)
    # -- `execution.Config.approval_max_age_s` is never read anywhere to
    # bound anything on the execution side.
    #
    # (`readable_root_files` was listed here until 2026-09-19; every read
    # tool now passes it to `pathsafety` as `root_files`.)
    "execution": frozenset({"approval_max_age_s"}),
    # `guardian/rules.py`'s `ReversibilityRule.evaluate` reads `ctx.
    # config.mode` and `ctx.config.irreversible_requires_human` but never
    # `reversible_auto_in_guarded` -- a `reversible` proposal is
    # unconditionally allowed outside `locked` mode regardless of
    # posture, so the field that looks like it should gate "auto-approve
    # reversible actions while guarded" controls nothing.
    #
    # `guardian/pipeline.py`'s escalation branch awaits `ctx.classify
    # (proposal)` with no `asyncio.wait_for`/timeout wrapping it at all,
    # so `classifier_timeout_s` is never applied to that call.
    "guardian": frozenset({"reversible_auto_in_guarded", "classifier_timeout_s"}),
    # Four `[interface]` fields with no reader anywhere in
    # `simorgh/interface/`: `prompt_timeout_s` (no `timeout=` on the
    # prompt_toolkit/readline prompt in `tui.py`), `vitals_idle_
    # reprint_s`/`vitals_interval_s` (`vitals.py` has no interval or
    # reprint logic that reads either), and `notice_queue_max` (no
    # `Queue(...)` construction anywhere in the package that would take
    # a max size from it).
    "interface": frozenset({
        "prompt_timeout_s", "vitals_idle_reprint_s", "vitals_interval_s", "notice_queue_max",
    }),
    # `planning/service.py`'s retry/give-up logic reads `self.config.
    # max_blocked_retries` (a different field) everywhere task attempts
    # are compared against a limit; `max_task_attempts` itself is never
    # read outside `config.py`.
    #
    # `planning/store.py`'s `TaskStore` docstring says "`leader` gates
    # only the background emitter loops (spec section 5.7)" but neither
    # `TaskStore.__init__` nor `planning/service.py` ever reads `self.
    # config.leader` -- the gate the docstring describes was never
    # wired to the field.
    "planning": frozenset({"max_task_attempts", "leader"}),
    # `[reflection] stall_idle_seconds` used to live here: nothing read
    # it, and 12-reflection.md section 3.5 had specified it since the
    # subsystem was designed. It is now really read, by
    # `reflection/service.py::_check_stalls` on `system.tick.idle`
    # (observer bulk5-02, 2026-09-10), so it is no longer dead and no
    # longer belongs in this list. A whitelist entry is a statement
    # that a field is unreachable; leaving one behind after the field
    # is wired would suppress the warning for a key that works.
}

# Same standard of evidence as `KNOWN_DEAD_FIELDS`, for a field whose
# `simorgh.toml` key is nested one level inside its `[section]` --
# `[persona.user_model] min_confidence_to_use` rather than a flat
# `[persona] min_confidence_to_use`. `KNOWN_DEAD_FIELDS`'s `present =
# known & set(section)` line only matches a bare top-level key, so it
# can never see these; `dead_fields` below checks this dict too, one
# level of nesting deep (`section[subsection][key]`), which is all four
# entries here need -- see the module docstring's reasoning for why a
# hand-written schema isn't the fix. Maps the TOML `"subsection.key"`
# path to the dataclass attribute it parses into (the two names differ
# for every entry here, which is exactly why this can't just reuse
# `KNOWN_DEAD_FIELDS`'s bare-string form).
#
# Confirmed dead by the same grep-the-whole-repo method as everything
# in `KNOWN_DEAD_FIELDS` (2026-09-08, re-verified against every fix
# committed earlier the same day -- none of them wired these up):
#   (persona.user_model.min_confidence_to_use was listed here until
#     2026-09-19, when the field and its dead reader were removed from
#     `persona/config.py`; the key is now simply unknown.)
#   verification.trajectory.wasted_step_ratio_warn (-> VerificationConfig.
#     trajectory_wasted_step_ratio_warn) -- `TrajectoryMetrics.wasted`
#     (`verification/trajectory.py`) is counted but never turned into a
#     ratio or compared against this field anywhere in `verdict.py`
#     (whose `combine()` checks only `trajectory.denied_actions` against
#     `max_denied_actions`) or `service.py`.
#   (verification.review.require_real_provider was listed here until
#     2026-09-19, when `verification/service.py::_think` started sending
#     it on every `cognition.think`.)
#   worldmodel.git.refresh_seconds (-> Config.git_refresh_seconds) -- no
#     file under `simorgh/worldmodel/` reads it outside `config.py`;
#     there is no periodic git-refresh loop anywhere in the package
#     (`facets/git_state.py` runs `git` synchronously on demand, not on
#     an interval) for it to throttle.
KNOWN_DEAD_NESTED_FIELDS: dict[str, dict[str, str]] = {
    "verification": {
        "trajectory.wasted_step_ratio_warn": "trajectory_wasted_step_ratio_warn",
    },
    "worldmodel": {"git.refresh_seconds": "git_refresh_seconds"},
}


def _config_classes() -> dict[str, Callable[..., Any]]:
    """Imported here, not at module scope: this runs once at boot and
    should not add sixteen imports to every process that touches the
    Kernel package."""
    from simorgh.cognition.config import Config as CognitionConfig
    from simorgh.growth.explore.config import Config as CuriosityConfig
    from simorgh.execution.config import Config as ExecutionConfig
    from simorgh.guardian.config import Config as GuardianConfig
    from simorgh.interface.config import Config as InterfaceConfig
    from simorgh.growth.estimate.config import Config as LearningConfig
    from simorgh.memory.config import Config as MemoryConfig
    from simorgh.orchestration.config import Config as OrchestrationConfig
    from simorgh.persona.config import Config as PersonaConfig
    from simorgh.planning.config import Config as PlanningConfig
    from simorgh.growth.monitors.config import Config as ReflectionConfig
    from simorgh.verification.config import VerificationConfig
    from simorgh.worldmodel.config import Config as WorldModelConfig

    # `benchmark` and `bus` are not in `KERNEL_SECTIONS` (the Kernel
    # doesn't consume `[benchmark]` at all, and it consumes `[bus]` only
    # to build the transport, not on the subsystem's behalf) but each
    # has a genuine `Config.from_mapping` a 2026-09-08 audit found a dead
    # field in (`benchmark.concurrency`, removed 2026-09-19; `bus.drain_seconds`,
    # `bus.metrics_interval_seconds`) -- without listing the classes
    # here, adding those names to `KNOWN_DEAD_FIELDS` below would be
    # inert: `dead_fields` looks up `classes.get(name)` and silently
    # skips a name this dict doesn't have, which is exactly the kind of
    # silent no-op this whole module exists to prevent. `BusConfig.
    # from_mapping`'s `data_dir` keyword defaults to "." so the
    # baseline/written comparison below still works with a plain dict.
    from simorgh.benchmark.config import Config as BenchmarkConfig
    from simorgh.bus.config import Config as BusConfig
    # `[telemetry]` is the Kernel's own section (it builds the store), in
    # `KERNEL_SECTIONS`; its class is listed so a typo there is reported.
    from simorgh.telemetry.config import Config as TelemetryConfig

    return {
        "benchmark": BenchmarkConfig,
        "bus": BusConfig,
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
        "telemetry": TelemetryConfig,
        "verification": VerificationConfig,
        "worldmodel": WorldModelConfig,
    }


def _perturbed(value):
    """A different value of the same kind, or None when there is none to try."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "_x"
    if isinstance(value, (list, tuple)):
        return [*value, "_x"]
    return None


def _leaves(section: dict, prefix: str = ""):
    for key, value in section.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _leaves(value, path + ".")
        else:
            yield path, value


def _with(section: dict, path: str, value) -> dict:
    head, _, rest = path.partition(".")
    out = dict(section)
    out[head] = _with(dict(section.get(head) or {}), rest, value) if rest else value
    return out


#: Keys the Kernel itself reads from every subsystem's section, which no
#: subsystem Config parses: `secrets` (ContextFactory scopes the secret
#: store with it). Reported as unread on the first live boot of the check
#: (2026-09-19, `[execution] secrets`).
KERNEL_READ_KEYS = frozenset({"secrets"})


def unread_keys(cls, section: dict, baseline: dict | None = None) -> list[str]:
    """The keys of `section` nothing reads: changing the value of each
    changes nothing in the parsed config. A key merely set to its default
    is read -- `[guardian.physical] auto_approve = false` was reported as a
    section that "changed nothing -- check the key names" on every boot
    (2026-09-19) though the key was right."""
    baseline = dict(baseline or {})
    written = baseline | dict(section)
    try:
        parsed = cls.from_mapping(written)
    except Exception:  # noqa: BLE001 -- a section that cannot parse is the subsystem's to report
        return []
    unread = []
    for path, value in _leaves(dict(section)):
        if path.split(".", 1)[0] in KERNEL_READ_KEYS:
            continue
        other = _perturbed(value)
        if other is None:
            continue
        try:
            if cls.from_mapping(_with(written, path, other)) == parsed:
                unread.append(path)
        except Exception:  # noqa: BLE001 -- a value the parser rejects was read
            continue
    return unread


def dead_sections(config, *, names: Iterable[str] | None = None) -> list[str]:
    """Section names holding at least one key nothing reads.

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
        if unread_keys(cls, dict(section), EFFECTIVE_DEFAULTS.get(name, {})):
            dead.append(name)
    return dead


def _present_nested(section: dict, nested_known: dict[str, str]) -> dict[str, str]:
    """The subset of `nested_known` (`"subsection.key" -> attr`) whose
    `subsection.key` is actually present in `section` -- one level of
    nesting, `section[subsection][key]`, which is all `KNOWN_DEAD_
    NESTED_FIELDS` needs."""
    present: dict[str, str] = {}
    for path, attr in nested_known.items():
        subsection, _, key = path.partition(".")
        sub = section.get(subsection)
        if isinstance(sub, dict) and key in sub:
            present[path] = attr
    return present


def dead_fields(config, *, names: Iterable[str] | None = None) -> list[tuple[str, str]]:
    """`(section, field)` pairs that were explicitly set to something
    other than their default, and parsed cleanly, but that no code
    path reads (`KNOWN_DEAD_FIELDS`, plus `KNOWN_DEAD_NESTED_FIELDS`
    for a field nested one level inside its section). A section already
    caught by `dead_sections` (an unrecognised key) is skipped here --
    it is already reported, and this check only adds value for a field
    that genuinely parses into a different, live-looking Config value.

    A nested field is reported with its dotted `"subsection.key"` path
    as `field`, so `report()` needs no changes to log it."""
    classes = _config_classes()
    already_dead = set(dead_sections(config, names=names))
    all_names = set(KNOWN_DEAD_FIELDS) | set(KNOWN_DEAD_NESTED_FIELDS)
    dead: list[tuple[str, str]] = []
    for name in sorted(names if names is not None else all_names):
        if name in already_dead:
            continue
        known = KNOWN_DEAD_FIELDS.get(name, frozenset())
        nested_known = KNOWN_DEAD_NESTED_FIELDS.get(name, {})
        if not known and not nested_known:
            continue
        cls = classes.get(name)
        if cls is None:
            continue
        section = config.section(name)
        if not section:
            continue
        present = known & set(section)
        present_nested = _present_nested(section, nested_known)
        if not present and not present_nested:
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
        for path, attr in sorted(present_nested.items()):
            if getattr(written_cfg, attr) != getattr(baseline_cfg, attr):
                dead.append((name, path))
    return dead


def report(config, logger) -> list[str]:
    """Log one warning per dead section, and one per known-dead field
    in an otherwise-live section. Returns the dead section names, for
    the caller and for tests -- the same contract as before this
    function also checked fields."""
    dead = dead_sections(config)
    classes = _config_classes()
    for name in dead:
        keys = unread_keys(classes[name], dict(config.section(name)), EFFECTIVE_DEFAULTS.get(name, {}))
        logger.warning(
            "config.section_had_no_effect", section=name, keys=keys,
            detail=f"[{name}] {', '.join(keys)} in simorgh.toml: nothing reads "
                   f"{'it' if len(keys) == 1 else 'them'} -- check the names against simorgh/{name}/config.py",
        )
    for name, field in dead_fields(config):
        logger.warning(
            "config.field_had_no_effect", section=name, field=field,
            detail=f"[{name}] {field} in simorgh.toml parses but nothing reads it -- see "
                   f"simorgh/kernel/configcheck.py KNOWN_DEAD_FIELDS for why.",
        )
    return dead


__all__ = ["dead_sections", "dead_fields", "report", "unread_keys"]
