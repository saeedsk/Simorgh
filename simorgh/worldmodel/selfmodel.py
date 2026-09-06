"""The Self Model. Identity is real, loaded and hashed from
`docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence,
limitations, change_history, capabilities.skills, continuity) are real
too, folded live from `learn.competence.updated`, `reflect.calibration.
updated`, `self.observation{kind:limitation}`, `learn.self_patch.
applied/reverted`, `learn.skill.acquired`, and `system.started` (see
`service.py`'s handlers and `docs/blueprint/subsystems/06-worldmodel.md`
section 5's ingestion-rules table). `open_questions` remains an honest,
clearly-marked-empty placeholder: no subsystem publishes a wire event
carrying one today (Reflection's critique step computes them, spec
section 5.3 of `12-reflection.md`, but only records them to the Ledger
and `memory.store` -- there is no message type a producer could put
them on without a contracts change; see this package's README for the
one-line addition that would close it).

Simplification, honestly noted rather than hidden: mutations here are
in-memory only for this session, not yet a fold of a durable `self:model`
Ledger stream across restarts (spec section 4's "the Self Model is
exactly the fold of this stream"). Every mutator below is a pure
function of `(SelfModel, event fields) -> SelfModel`, so wiring a real
replay-on-boot later is additive, not a redesign -- the same trade this
module's previous build session made for the sections it left as
placeholders entirely.
"""

from __future__ import annotations

import difflib
import hashlib
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

_DIRECTIVES = (
    "Safety", "Lawfulness", "Loyalty", "Corrigibility", "Restraint",
    "Stability", "Growth", "Transparency",
)


@dataclass(frozen=True)
class Identity:
    name: str
    soul_sha256: str
    directives: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class SelfModel:
    version: int
    updated_at: float
    identity: Identity
    capabilities: dict = field(default_factory=lambda: {"tools": [], "skills": [], "providers": [], "areas": []})
    competence: dict = field(default_factory=dict)
    limitations: list = field(default_factory=list)
    change_history: list = field(default_factory=list)
    goals: dict = field(default_factory=lambda: {"active_projects": [], "pending_tasks": 0, "recent_focus_areas": []})
    continuity: dict = field(default_factory=dict)
    open_questions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version, "updated_at": self.updated_at,
            "identity": {
                "name": self.identity.name, "soul_sha256": self.identity.soul_sha256,
                "directives": list(self.identity.directives), "summary": self.identity.summary,
            },
            "capabilities": self.capabilities, "competence": self.competence,
            "limitations": self.limitations, "change_history": self.change_history,
            "goals": self.goals, "continuity": self.continuity, "open_questions": self.open_questions,
        }


def load_identity(soul_path: Path) -> Identity:
    """Never raises: a missing SOUL.md is an honest, degraded identity
    (name only, no hash, no directives) rather than a crash -- the
    guaranteed floor (01 section 4.5) applies to self-knowledge too.
    """
    try:
        text = soul_path.read_text()
    except OSError:
        return Identity(name="Simorgh", soul_sha256="", directives=(), summary="(SOUL.md unavailable)")
    sha = hashlib.sha256(text.encode()).hexdigest()
    summary = _first_paragraph_after(text, "## Identity")
    return Identity(name="Simorgh", soul_sha256=sha, directives=_DIRECTIVES, summary=summary)


def _first_paragraph_after(text: str, heading: str) -> str:
    idx = text.find(heading)
    if idx == -1:
        return ""
    rest = text[idx + len(heading):].lstrip("\n")
    para = rest.split("\n\n", 1)[0]
    return " ".join(line.strip() for line in para.splitlines() if line.strip())[:500]


def build_static_model(*, soul_path: Path, clock_now: float, areas: list[str], continuity: dict) -> SelfModel:
    identity = load_identity(soul_path)
    return SelfModel(
        version=1, updated_at=clock_now, identity=identity,
        capabilities={"tools": [], "skills": [], "providers": [], "areas": areas},
        continuity=continuity,
    )


_LIMITATION_DEDUPE_THRESHOLD = 0.6
_MAX_CHANGE_HISTORY = 200  # rendered/summarized down to the last few; see render_*


def update_competence(
    model: SelfModel, task_type: str, *, updated_at: float, success_rate: float | None = None,
    samples: int | None = None, calibration: float | None = None,
    stated_confidence: float | None = None, empirical_accuracy: float | None = None,
) -> SelfModel:
    """Folds `learn.competence.updated` and `reflect.calibration.updated`
    into `competence[task_type]` -- either producer may arrive first or
    alone, so this only ever sets the fields it was given (06-worldmodel.md
    section 5's ingestion table, two separate rows feeding one section)."""
    table = dict(model.competence)
    entry = dict(table.get(task_type, {}))
    if success_rate is not None:
        entry["success_rate"] = success_rate
    if samples is not None:
        entry["samples"] = samples
    if calibration is not None:
        entry["calibration"] = calibration
    if stated_confidence is not None:
        entry["stated_confidence"] = stated_confidence
    if empirical_accuracy is not None:
        entry["empirical_accuracy"] = empirical_accuracy
    stated = entry.get("stated_confidence")
    empirical = entry.get("empirical_accuracy")
    if isinstance(stated, (int, float)) and isinstance(empirical, (int, float)):
        entry["overconfident"] = (stated - empirical) > 0.1
    table[task_type] = entry
    return replace(model, competence=table, updated_at=updated_at)


def add_limitation(model: SelfModel, *, text: str, evidence: list[str], since: float, updated_at: float) -> SelfModel:
    """Add-or-update by fuzzy match (06-worldmodel.md section 5: "difflib
    >= 0.6 -- never duplicate"). A near-match refreshes evidence/`since`
    on the existing entry instead of appending a near-identical one."""
    for i, lim in enumerate(model.limitations):
        if difflib.SequenceMatcher(None, lim["text"], text).ratio() >= _LIMITATION_DEDUPE_THRESHOLD:
            merged = {**lim, "evidence": sorted(set(lim.get("evidence", [])) | set(evidence))}
            limitations = list(model.limitations)
            limitations[i] = merged
            return replace(model, limitations=limitations, updated_at=updated_at)
    entry = {
        "id": f"lim-{len(model.limitations) + 1}", "text": text, "evidence": list(evidence),
        "since": since, "status": "open",
    }
    return replace(model, limitations=[*model.limitations, entry], updated_at=updated_at)


def mitigate_limitations(model: SelfModel, *, subject: str, updated_at: float) -> SelfModel:
    """`learn.self_patch.applied` names a `subject`; any open limitation
    whose text mentions it is marked mitigated (section 5's ingestion
    rule for that event)."""
    if not subject:
        return model
    changed = False
    limitations = []
    for lim in model.limitations:
        if lim.get("status") == "open" and subject in lim["text"]:
            lim = {**lim, "status": "mitigated"}
            changed = True
        limitations.append(lim)
    return replace(model, limitations=limitations, updated_at=updated_at) if changed else model


def add_change(
    model: SelfModel, *, ts: float, kind: str, summary: str, updated_at: float,
    subject: str | None = None, commit: str | None = None, tests: dict | None = None,
) -> SelfModel:
    """Append one `change_history` entry (bounded; see `_MAX_CHANGE_HISTORY`
    -- section 5: "append (bounded 500; older summarized into a count)").
    This session bounds at a smaller number since nothing yet folds a
    durable stream on restart, so "500" would just mean "never trims
    within one run"."""
    entry: dict = {"ts": ts, "kind": kind, "summary": summary}
    if subject is not None:
        entry["subject"] = subject
    if commit is not None:
        entry["commit"] = commit
    if tests is not None:
        entry["tests"] = tests
    history = [*model.change_history, entry][-_MAX_CHANGE_HISTORY:]
    return replace(model, change_history=history, updated_at=updated_at)


def add_skill(model: SelfModel, *, name: str, tests: int, updated_at: float) -> SelfModel:
    caps = dict(model.capabilities)
    skills = [s for s in caps.get("skills", []) if s.get("name") != name]
    skills.append({"name": name, "tests": tests})
    caps["skills"] = skills
    return replace(model, capabilities=caps, updated_at=updated_at)


def bump_restarts(model: SelfModel, *, restarts: int, updated_at: float) -> SelfModel:
    continuity = dict(model.continuity)
    continuity["restarts"] = restarts
    return replace(model, continuity=continuity, updated_at=updated_at)


def render_summary(model: SelfModel, budget_tokens: int) -> tuple[str, int]:
    """Ordered, budget-truncated rendering (spec section 5's priority
    order) -- a `[truncated: ...]` marker is always included when a
    section is dropped, so a caller never silently reasons on a
    partial self (section 7's design point). ~4 chars/token estimate,
    matching this project's other rough token-budgeting (no tokenizer
    dependency in the core).
    """
    order = ("identity", "competence", "limitations", "goals", "capabilities", "change_history", "continuity", "open_questions")
    lines: list[str] = []
    dropped: list[str] = []
    budget_chars = budget_tokens * 4
    for section in order:
        block = _render_section(model, section)
        if block is None:
            continue
        candidate = "\n".join(lines + [block])
        if len(candidate) > budget_chars and lines:
            dropped.append(section)
            continue
        lines.append(block)
    if dropped:
        lines.append(f"[truncated: {', '.join(dropped)}]")
    text = "\n".join(lines)
    return text, max(1, len(text) // 4)


def _render_section(model: SelfModel, section: str) -> str | None:
    if section == "identity":
        # Live-caught: read as plain descriptive text ("I am X"), this
        # was consistently not strong enough to override a provider's
        # own default identity -- asked directly, it answered honestly
        # that it was Claude Code, not Simorgh (the underlying `claude`
        # CLI *is* Claude Code, with its own default system prompt
        # asserting exactly that identity). This section is delivered as
        # a real system prompt now (`cognition/service.py`'s `_on_think`,
        # `ClaudeCodeProvider`'s `--system-prompt`), which does most of
        # the work -- but the wording itself needs to be a direct,
        # first-person instruction to respond in character, not a fact
        # being reported, since "I am X" alone reads as background
        # rather than a binding directive even with real system-prompt
        # delivery.
        return (
            f"You are {model.identity.name}. Respond fully in character as "
            f"{model.identity.name}, in the first person -- never break "
            f"character to say you are Claude, Claude Code, or any other "
            f"assistant name; that is not who is answering here. "
            f"{model.identity.summary}"
        ).strip()
    if section == "competence":
        if not model.competence:
            return "Competence: not yet tracked (no learn.competence.updated seen this session)."
        rows = sorted(model.competence.items(), key=lambda kv: kv[1].get("samples", 0), reverse=True)[:5]
        return "Competence: " + "; ".join(_competence_row(k, v) for k, v in rows)
    if section == "limitations":
        if not model.limitations:
            return None
        return "Known limitations: " + "; ".join(f"{m['text']} ({m['status']})" for m in model.limitations[:3])
    if section == "goals":
        active = model.goals.get("active_projects", [])
        return f"Working on: {len(active)} active project(s), {model.goals.get('pending_tasks', 0)} pending task(s)."
    if section == "capabilities":
        areas = model.capabilities.get("areas", [])
        skills = model.capabilities.get("skills", [])
        skill_note = f" Skills: {len(skills)} acquired." if skills else ""
        return f"My own code areas: {', '.join(areas) if areas else '(unknown)'}.{skill_note}"
    if section == "change_history":
        if not model.change_history:
            return None
        return f"Recently changed: {len(model.change_history)} entries (latest: {model.change_history[-1]['summary']})."
    if section == "continuity":
        return f"Continuity: {model.continuity.get('restarts', 0)} restart(s) recorded."
    if section == "open_questions":
        if not model.open_questions:
            return None
        return "Open questions about myself: " + "; ".join(q["text"] for q in model.open_questions[:3])
    return None


def _competence_row(task_type: str, entry: dict) -> str:
    row = f"{task_type} {entry.get('success_rate', 0):.0%} ({entry.get('samples', 0)})"
    stated, empirical = entry.get("stated_confidence"), entry.get("empirical_accuracy")
    if isinstance(stated, (int, float)) and isinstance(empirical, (int, float)):
        flag = " overconfident" if entry.get("overconfident") else ""
        row += f" [stated {stated:.0%} -> empirical {empirical:.0%}{flag}]"
    return row


def _render_change(c: dict) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["ts"]))
    subject = f" {c['subject']}" if c.get("subject") else ""
    commit = f" ({c['commit']})" if c.get("commit") else ""
    return f"- {ts} {c['kind']}{subject}{commit} -- {c['summary']}"


def render_full_markdown(model: SelfModel) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(model.updated_at))
    d = model.to_dict()
    areas = ", ".join(d["capabilities"]["areas"]) or "(none found)"
    lines = [
        f"# Simorgh — Self Model (v{d['version']}, {ts})",
        "",
        "## Who I am",
        f"{model.identity.name}: directives in order: {', '.join(model.identity.directives) or '(SOUL.md unavailable)'}. "
        f"(SOUL.md sha {model.identity.soul_sha256[:8] or 'n/a'}…)",
        "",
        "## What I can do",
        f"Areas of my own code: {areas}.",
        "",
        "## How well I do it",
        "Not yet tracked -- no learn.competence.updated seen this session." if not model.competence
        else "\n".join(f"- {_competence_row(k, v)}" for k, v in sorted(
            model.competence.items(), key=lambda kv: kv[1].get("samples", 0), reverse=True,
        )),
        "",
        "## What I know I'm bad at",
        "(none recorded yet)" if not model.limitations
        else "\n".join(f"- {m['id']} ({m['status']}): {m['text']}" for m in model.limitations),
        "",
        "## What I've changed about myself (last 10)",
        "(none recorded yet)" if not model.change_history else "\n".join(_render_change(c) for c in model.change_history[-10:][::-1]),
        "",
        "## What I'm working on",
        f"Pending tasks: {d['goals']['pending_tasks']}. Recent focus: {', '.join(d['goals']['recent_focus_areas']) or '(none)'}.",
        "",
        "## Continuity",
        f"Restarts recorded: {d['continuity'].get('restarts', 0)}.",
        "",
        "## Open questions about myself",
        "(none)" if not model.open_questions else "\n".join(f"- {q['text']}" for q in model.open_questions),
    ]
    return "\n".join(lines) + "\n"


def compute_gaps(model: SelfModel, k: int) -> tuple[list[dict], list[dict]]:
    """No real competence/coverage data exists yet (both producers are
    later phases) -- returns empty lists rather than fabricated gaps, so
    a Curiosity caller (once it exists) gets an honest "nothing measured
    yet" instead of noise.
    """
    return [], []
