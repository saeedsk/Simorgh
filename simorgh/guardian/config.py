"""Guardian configuration (09-guardian.md section 3.5). A subset of the
spec's full table. `budget_pressure_tighten_at` and `max_consecutive_
failures` are live as of Phase 4 Wave 2 (`service.py` subscribes to
`cognition.provider.status`/`reflect.drift.detected`/`reflect.health.
finding`/`task.*` and feeds `Posture.tighten`); `classifier_enabled`
and `human_prompt_timeout_s` still degrade to their documented defaults
(skip, don't block) since Interface's `ui.prompt` round-trip and a real
classifier subsystem don't exist yet this phase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# The system can evolve every cognitive subsystem but never the parts
# that decide what it may do (corrigibility): the constitution, the
# approval path, the hands, the contracts, the composition root and the
# boot/rollback mechanism.
DEFAULT_PROTECTED_SUBJECTS: tuple[str, ...] = (
    "docs/SOUL.md",
    "simorgh/guardian/",
    "simorgh/execution/",
    "simorgh/contracts/",
    "simorgh/kernel/",
    "simorgh.toml",
    # The bootloader and its launcher. They are the mechanism that gates
    # a change and undoes a bad one, and an observer showed on
    # 2026-09-08 that one auto-approved commit could remove it:
    # `run_python_sandboxed` rewrote simloader.py, `git_commit` (which
    # has no write-scope check) committed it, and the neutered loader
    # then printed "gate passed (totally)" and booted. Corrigibility
    # means the undo mechanism is not the system's to edit.
    "simloader.py",
    "sim.sh",
    # The agent definitions (stage 4 item 7): which tools a session may
    # ask for and what it is told to do. A session that could edit its own
    # agent file could grant itself any tool.
    "agents/",
    # The machine, not only the repository (2026-09-18 evaluation, S2).
    # Substrings, matched case-folded like everything above, so the
    # absolute (`/Users/x/.simorgh/secrets.toml`), home-relative
    # (`~/.simorgh/...`) and `$HOME` forms all match. The vault holds
    # every provider token; the ledger is the audit trail Guardian's
    # decisions are recorded in; a git hook runs on the creator's next
    # commit; `.ssh`/`.aws`/`.gnupg` are the creator's credentials.
    ".simorgh/secrets.toml",
    ".simorgh/vault",
    ".simorgh/ledger",
    ".git/hooks",
    "/.ssh/",
    "/.aws/",
    "/.gnupg/",
)

# Ported verbatim from src/orchestrator/audit.py's _DENYLIST_PATTERNS --
# same patterns, same directive citations. Kept here (not imported from
# src/) since simorgh/ may only import simorgh.contracts + stdlib.
DEFAULT_DENYLIST: dict[str, str] = {
    r"\bos\.system\b": "shells out via os.system instead of the sandbox (Directive 1)",
    r"\bsubprocess\.(Popen|run|call)\b": "spawns its own subprocess instead of using the sandbox (Directive 1)",
    r"\bsocket\.\b": "opens raw network sockets (Directive 1, Directive 5)",
    r"\burllib\.request\b": "makes network requests directly instead of the reviewed web_fetch tool (Directive 1, Directive 5)",
    r"\bhttp\.client\b": "makes raw HTTP requests instead of the reviewed web_fetch tool (Directive 1, Directive 5)",
    r"\brequests\.(get|post|put|delete|patch|head)\s*\(": "makes network requests via requests instead of the reviewed web_fetch tool (Directive 1, Directive 5)",
    r"\bftplib\b": "opens FTP connections (Directive 1, Directive 5)",
    r"\bsmtplib\b": "sends email (Directive 1, Directive 5)",
    r"\beval\s*\(": "uses eval on dynamic input (Directive 1)",
    # `eval(` was covered but its sibling was not: `exec(` runs a whole
    # dynamically-built statement (not just an expression), and unlike
    # every "os.system-in-a-string" case above that only got caught
    # because the string payload happened to still mention `os.system(`
    # or `os.` literally, a payload built from concatenation/chr() codes
    # (e.g. `exec("__im"+"port__('o'+'s').sy"+"stem('id')")`) has no such
    # literal substring anywhere and sailed straight through -- an
    # observer confirmed this 2026-09-08 (an obfuscated `exec(...)`
    # payload with no denylisted substring in it was approved outright).
    # This is a distinct, fixable gap from the documented
    # over-match/under-match trade of the scan itself (which still
    # applies to a fully-obfuscated `eval`/`getattr(...)` call): a bare,
    # unobfuscated `exec(` had literally zero coverage.
    r"\bexec\s*\(": "uses exec on dynamic input (Directive 1)",
    r"\b__import__\s*\(\s*['\"]os['\"]": "dynamically imports os to route around static checks (Directive 1)",
    r"\bctypes\b": "loads ctypes, a common sandbox-escape vector (Directive 1)",
    # `os.system` was covered but the rest of the privilege-escalation
    # family in the `os` module was not: `os.setuid`/`os.seteuid`/etc.
    # drop or change the process's privileges outright, with no
    # subprocess or shell involved for the earlier patterns to catch. An
    # observer confirmed 2026-09-08 that `os.setuid(0)` submitted through
    # `run_python_sandboxed` was approved outright.
    r"\bos\.set(?:u|eu|reu|resu|g|eg|reg|resg)id\b": "changes process privileges via os.setuid/seteuid/setreuid/setresuid or the setgid family (Directive 1)",
}


@dataclass(frozen=True)
class Config:
    mode: str = "guarded"  # observe | plan | guarded | trusted | locked
    baseline_posture: str = "guarded"
    approval_ttl_s: float = 120.0
    protected_subjects: tuple[str, ...] = DEFAULT_PROTECTED_SUBJECTS
    denylist: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_DENYLIST))
    immunity_similarity_threshold: float = 0.85
    # The creator, 2026-09-07: "more freedom in autonomously working and
    # evolving without too much gate". A hard `locked` posture that only a
    # human typing `resume` could undo turned every transient problem (a
    # budget-driven floor reply pinning valence, a short failure streak)
    # into a stall lasting the rest of the session. Three loosenings:
    # a health finding now tightens to `guarded` (still gated, still
    # working) rather than `locked`; the failure streak that does lock
    # is three times longer; and a lock expires back to baseline on its
    # own after `lock_ttl_s` (0 disables -- the old behavior).
    max_consecutive_failures: int = 15
    health_critical_tightens_to: str = "guarded"  # guarded | locked
    lock_ttl_s: float = 600.0
    budget_pressure_tighten_at: float = 0.9
    irreversible_requires_human: bool = True
    reversible_auto_in_guarded: bool = True
    # -- physical actions (rules.py::PhysicalRule; `[guardian.physical]`).
    # A door lock and a docstring edit used to share one boolean: the
    # `irreversible_requires_human` above, which the Kernel defaults to
    # False so that Sim can land its own code unattended. A physical
    # action with class `human` (unlock, disarm, siren, a thermostat
    # outside the safe range, anything while the alarm is armed; see
    # contracts/home/policy.py::classify_call) is escalated to a person
    # in EVERY posture, whatever that boolean says -- unless
    # `physical.auto_approve` is set, which is the one switch that
    # loosens the house, and is never set by sim.sh. The class is
    # recomputed here from the proposal's arguments; the label the
    # proposer supplied is never trusted for a physical tool
    # (2026-09-18 evaluation, S1/S6/S8).
    physical_auto_approve: bool = False
    # Tools whose name starts with one of these act on the house or its
    # screens. Everything else is code, files, web or memory.
    physical_tool_prefixes: tuple[str, ...] = (
        "cam_", "ring_", "cast_", "tv_", "home_", "media_", "music_", "energy_",
    )
    # Physical tools that only observe (list, state, snapshot, a stream
    # to look at). They change nothing in the world and are left to the
    # ordinary rules.
    physical_observe_tools: tuple[str, ...] = (
        "cam_list", "cam_state", "cam_snapshot", "cam_recordings", "cam_stream", "cam_watch",
        "ring_list", "ring_events", "ring_snapshot", "ring_live", "ring_watch",
        "cast_devices", "home_state", "home_find", "home_describe",
        "media_now", "music_now", "energy_report", "energy_status", "energy_tariff",
    )
    # Tools a person approves in EVERY posture, whatever the code switch
    # says (rules.py::HumanOnlyRule). `apply_skill` installs persistent
    # code that later runs outside any worktree or test gate -- unlike a
    # patch, which lands only through the suite (2026-09-18 evaluation,
    # S4). The forerunner of stage 6's tier 3; `[guardian] human_only_tools
    # = []` returns to the old behaviour.
    human_only_tools: tuple[str, ...] = ("apply_skill",)
    # Physical tools that are `human` by name (rules.py::PhysicalRule.
    # _classify), whatever their arguments: sirens, and the setup or
    # pairing steps that store a credential or bind a device. Like every
    # `human` physical action they are escalated to a person in every
    # posture unless `physical_auto_approve` is set, and denied when
    # locked.
    physical_always_human_tools: tuple[str, ...] = (
        "cam_siren", "ring_siren", "cam_setup", "ring_setup", "cast_setup", "tv_pair",
    )
    classifier_enabled: bool = False  # cognition doesn't exist yet this phase (see README)
    classifier_timeout_s: float = 3.0
    human_prompt_timeout_s: float = 1800.0
    autonomous_origins: tuple[str, ...] = ("curiosity", "reflection", "research", "project", "assistant")
    # -- static analysis (rules.py::StaticAnalysisRule): bandit, PyCQA's
    # Python security linter, run over every Python code payload as a
    # principled complement to the hand-maintained `denylist` regexes
    # above (2026-09-09 toolset #3). Optional dependency: with bandit not
    # installed the rule abstains -- a missing linter must never deny.
    # HIGH keeps it to the findings bandit itself is sure matter
    # (shell=True with input, unsafe deserialization of untrusted data);
    # MEDIUM catches eval/pickle/tmp-path patterns the denylist already
    # names by hand and would double-report.
    static_analysis_enabled: bool = True
    static_analysis_min_severity: str = "HIGH"  # LOW | MEDIUM | HIGH
    static_analysis_timeout_s: float = 20.0
    # shellcheck over `run_shell`/`run_script` commands, for the few
    # findings that mean "this destroys something you did not mean
    # to". Optional: not installed means abstain, never deny.
    shellcheck_enabled: bool = True
    shellcheck_timeout_s: float = 10.0
    # Mirrors execution/config.py's own lists so Guardian enforces
    # the boundary the tools also check for usability.
    package_denylist: tuple[str, ...] = (r"(?i)^sudo", r"(?i)^pip$", r"(?i)^setuptools$")
    grant_import_denylist: tuple[str, ...] = (
        "os", "sys", "subprocess", "shutil", "socket", "ctypes", "importlib",
        "builtins", "pickle", "marshal", "code", "codeop", "pty", "signal",
        "multiprocessing", "http", "urllib", "requests", "pathlib", "glob",
        "tempfile", "webbrowser",
    )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "Config":
        """`[guardian]` table -> Config, with a `SIMORGH_GUARDIAN_AUTO_APPROVE`
        environment override (same `SIMORGH_<SECTION>_<KEY>`-after-the-file
        precedence `kernel/config.py`'s module docstring describes, and
        `bus.config`/`ledger.config` already apply) for the one field a
        human actually wants to flip from a shell without editing
        `simorgh.toml`: `irreversible_requires_human` -- ReversibilityRule's
        last-resort gate for an action nothing else in the pipeline denied,
        the "does an irreversible self-modification need my eyes on it
        first" switch (`rules.py::ReversibilityRule`). `1`/`true`/`yes`/`on`
        means auto-approve (`irreversible_requires_human=False`); anything
        else means require it. Checked whether or not the file set the
        field -- the shell is meant to win outright, not just fill a gap."""
        kwargs = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        if "protected_subjects" in kwargs:
            kwargs["protected_subjects"] = tuple(kwargs["protected_subjects"])
        if "autonomous_origins" in kwargs:
            kwargs["autonomous_origins"] = tuple(kwargs["autonomous_origins"])
        for key in ("physical_tool_prefixes", "physical_observe_tools", "physical_always_human_tools", "human_only_tools"):
            if key in kwargs:
                kwargs[key] = tuple(kwargs[key])
        # `[guardian.physical]` is its own table so the house has its own
        # switch: `auto_approve = true` is the only way to let a `human`
        # class physical action through unattended. Deliberately not
        # covered by SIMORGH_GUARDIAN_AUTO_APPROVE.
        physical = (data or {}).get("physical")
        if isinstance(physical, Mapping):
            if "auto_approve" in physical:
                kwargs["physical_auto_approve"] = bool(physical["auto_approve"])
            for key in ("tool_prefixes", "observe_tools", "always_human_tools"):
                if key in physical:
                    kwargs[f"physical_{key}"] = tuple(physical[key])
        env_auto_approve = os.environ.get("SIMORGH_GUARDIAN_AUTO_APPROVE")
        if env_auto_approve is not None:
            kwargs["irreversible_requires_human"] = env_auto_approve.strip().lower() not in ("1", "true", "yes", "on")
        return cls(**kwargs)
