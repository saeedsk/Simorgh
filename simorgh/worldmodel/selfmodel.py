"""The Self Model -- **static this session** by explicit scope decision
(see the build directive and spec section 12): identity is real, loaded
and hashed from `docs/SOUL.md`; every other section (competence,
limitations, change_history, goals, continuity, open_questions) is an
honest, clearly-marked-empty placeholder, because their real producers
(Learning, Reflection, Planning) don't exist yet. The full event-sourced
`SelfModelProjection` -- folding `self:model` from `learn.*`/`reflect.*`/
`task.*` events -- is Phase 3 work (docs/blueprint/subsystems/06-worldmodel.md
section 5's ingestion-rules table). What's built now is the real,
final shape (schema, `self.summary`/`self.gaps` request/reply, the
`SELF.md` render) so Phase 3 only has to feed it, never redesign it.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
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
        return f"I am {model.identity.name}. {model.identity.summary}".strip()
    if section == "competence":
        if not model.competence:
            return "Competence: not yet tracked (Learning/Reflection not built this phase)."
        rows = sorted(model.competence.items(), key=lambda kv: kv[1].get("samples", 0), reverse=True)[:5]
        return "Competence: " + "; ".join(f"{k} {v.get('success_rate', 0):.0%} ({v.get('samples', 0)})" for k, v in rows)
    if section == "limitations":
        if not model.limitations:
            return None
        return "Known limitations: " + "; ".join(m["text"] for m in model.limitations[:3])
    if section == "goals":
        active = model.goals.get("active_projects", [])
        return f"Working on: {len(active)} active project(s), {model.goals.get('pending_tasks', 0)} pending task(s)."
    if section == "capabilities":
        areas = model.capabilities.get("areas", [])
        return f"My own code areas: {', '.join(areas) if areas else '(unknown)'}."
    if section == "change_history":
        if not model.change_history:
            return None
        return f"Recently changed: {len(model.change_history)} entries."
    if section == "continuity":
        return f"Continuity: {model.continuity.get('restarts', 0)} restart(s) recorded."
    if section == "open_questions":
        if not model.open_questions:
            return None
        return "Open questions about myself: " + "; ".join(q["text"] for q in model.open_questions[:3])
    return None


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
        "Not yet tracked -- Learning/Reflection are not built this phase." if not model.competence else str(model.competence),
        "",
        "## What I know I'm bad at",
        "(none recorded yet)" if not model.limitations else "\n".join(f"- {m['text']}" for m in model.limitations),
        "",
        "## What I've changed about myself",
        "(none recorded yet)" if not model.change_history else "\n".join(str(c) for c in model.change_history[:10]),
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
