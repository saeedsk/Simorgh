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

Since 2026-09-20 the history half IS a fold (stage 6 item 1). Every
mutator here was left a pure function of `(SelfModel, fields) ->
SelfModel` against the day somebody wired the replay, and that is
what `REPLAYABLE` and `replay()` below are: `service.py` writes each
applied change to `self:changes` and folds the stream back at boot,
so competence, limitations, the patches landed and the skills
acquired survive a restart. They did not before -- Sim woke up every
morning having forgotten what it had learnt it was bad at.

What is deliberately NOT replayed is the derived half: capabilities
and goals. The tool registry announces itself at every boot and the
task store is read, so replaying those would recompute what is
already known, and worse, could resurrect a tool that has since gone.
A fold is for what happened; a rescan is for what is.
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
    #: Per tool, from `action.result`: how often it works and how long
    #: it takes (stage 6 item 1). Keyed by tool name.
    #:
    #: NOT `capabilities["tools"]`, which is the registry -- which
    #: tools EXIST -- and is rescanned at every boot. This is how
    #: they BEHAVE, which is history and cannot be rescanned. The
    #: two were briefly both called `tools` and the fold test caught
    #: it: one of them must never be replayed and the other must.
    tool_stats: dict = field(default_factory=dict)
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
            "tool_stats": self.tool_stats,
            "limitations": self.limitations, "change_history": self.change_history,
            "goals": self.goals, "continuity": self.continuity, "open_questions": self.open_questions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SelfModel | None":
        """Rebuild a SelfModel from `to_dict()` output. Returns None on any
        malformed input (missing keys, bad types) so callers fall back to
        the empty/static model rather than crash on a corrupt snapshot --
        honest degraded continuity, like load_identity's missing-SOUL floor."""
        try:
            identity = Identity(
                name=data["identity"]["name"],
                soul_sha256=data["identity"]["soul_sha256"],
                directives=tuple(data["identity"]["directives"]),
                summary=data["identity"]["summary"],
            )
            return cls(
                version=int(data["version"]),
                updated_at=float(data["updated_at"]),
                identity=identity,
                capabilities=dict(data.get("capabilities", {})),
                competence=dict(data.get("competence", {})),
                tool_stats=dict(data.get("tool_stats", {})),
                limitations=list(data.get("limitations", [])),
                change_history=list(data.get("change_history", [])),
                goals=dict(data.get("goals", {})),
                continuity=dict(data.get("continuity", {})),
                open_questions=list(data.get("open_questions", [])),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def from_dict(cls, data: dict) -> SelfModel | None:
        """Rebuild a SelfModel from `to_dict()` output. Returns None on any
        malformed input (missing keys, bad types) so callers fall back to
        the empty/static model rather than crash on a corrupt snapshot --
        honest degraded continuity, like load_identity's missing-SOUL floor."""
        try:
            identity = Identity(
                name=data["identity"]["name"],
                soul_sha256=data["identity"]["soul_sha256"],
                directives=tuple(data["identity"]["directives"]),
                summary=data["identity"]["summary"],
            )
            return cls(
                version=int(data["version"]),
                updated_at=float(data["updated_at"]),
                identity=identity,
                capabilities=dict(data.get("capabilities", {})),
                competence=dict(data.get("competence", {})),
                tool_stats=dict(data.get("tool_stats", {})),
                limitations=list(data.get("limitations", [])),
                change_history=list(data.get("change_history", [])),
                goals=dict(data.get("goals", {})),
                continuity=dict(data.get("continuity", {})),
                open_questions=list(data.get("open_questions", [])),
            )
        except (KeyError, TypeError, ValueError):
            return None


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


#: How many recent durations to keep per tool. A p95 from 64 samples
#: is rough and the summary says "over N" for exactly that reason;
#: keeping every duration Sim has ever measured would make the self
#: model grow without bound for a number nobody reads to three
#: decimal places.
TOOL_SAMPLES = 64


def _quantile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[index])


def observe_tool(model: SelfModel, *, tool: str, ok: bool, duration_ms: float,
                 updated_at: float) -> SelfModel:
    """Fold one `action.result` into what Sim knows about its tools
    (stage 6 item 1: per-tool p(ok) and latency quantiles).

    Counted for every result, refused ones included -- a tool that
    Guardian stops half the time is a tool Sim should plan around
    differently, and hiding that behind "only the calls that ran"
    would make the number flattering rather than useful.

    `p_ok` is the plain rate rather than a Beta posterior, and the
    sample count is carried beside it so nobody reads 1/1 as 100%.
    The posterior belongs with the per-(task type, strategy) work that
    is still open in this item; a tool's success rate has thousands of
    samples where a task type has tens, which is why the cheap number
    is enough here and is not there.
    """
    name = str(tool or "").strip()
    if not name:
        return model
    table = dict(model.tool_stats)
    entry = dict(table.get(name, {}))
    runs = int(entry.get("runs", 0)) + 1
    good = int(entry.get("ok", 0)) + (1 if ok else 0)
    recent = [float(x) for x in entry.get("recent_ms", [])]
    if duration_ms and duration_ms > 0:
        recent.append(float(duration_ms))
        recent = recent[-TOOL_SAMPLES:]
    ordered = sorted(recent)
    entry.update({
        "runs": runs, "ok": good, "p_ok": round(good / runs, 4),
        "recent_ms": recent,
        "p50_ms": round(_quantile(ordered, 0.5), 1),
        "p95_ms": round(_quantile(ordered, 0.95), 1),
    })
    table[name] = entry
    return replace(model, tool_stats=table, updated_at=updated_at)


def slow_or_unreliable(model: SelfModel, *, min_runs: int = 5, p_ok_below: float = 0.8,
                       p95_over_ms: float = 10_000.0) -> list[dict]:
    """The tools worth knowing about before planning with them.

    `min_runs` exists because the interesting failure of a number like
    this is a tool that failed once, on its first call, and is then
    reported as 0% forever.
    """
    out = []
    for name, entry in sorted(model.tool_stats.items()):
        runs = int(entry.get("runs", 0))
        if runs < min_runs:
            continue
        unreliable = float(entry.get("p_ok", 1.0)) < p_ok_below
        slow = float(entry.get("p95_ms", 0.0)) > p95_over_ms
        if unreliable or slow:
            out.append({"tool": name, "runs": runs, "p_ok": entry.get("p_ok"),
                        "p95_ms": entry.get("p95_ms"), "slow": slow, "unreliable": unreliable})
    return out


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


def update_goals(
    model: SelfModel, *, updated_at: float, task_id: str, kind: str = "", status: str,
    description: str = "", area: str | None = None,
) -> SelfModel:
    """Fold `task.created/completed/failed/blocked` into `goals`
    (06-worldmodel.md section 5's `task.*` -> goals row). Live-caught
    (post-cutover review): the World Model never consumed any `task.*`
    event, so `pending_tasks` was a constant 0 -- asked "show your tasks"
    in chat right after `propose` had created one, Sim answered from this
    line and said its queue was empty. `status`: `pending` adds/keeps the
    task; `completed`/`failed` removes it; `blocked` keeps it (still
    outstanding). `kind == "project"` tasks are also tracked as active
    projects while pending. Idempotent: replaying the same event is a
    no-op that returns `model` unchanged."""
    goals = dict(model.goals)
    pending: dict = dict(goals.get("_pending", {}))
    projects = [p for p in goals.get("active_projects", []) if p.get("project_id") != task_id]
    was = pending.get(task_id)
    if status == "completed" or status == "failed":
        if was is None and len(projects) == len(goals.get("active_projects", [])):
            return model
        pending.pop(task_id, None)
    else:  # pending | blocked -- outstanding either way
        entry = {"kind": kind or (was or {}).get("kind", ""), "status": status,
                 "description": description or (was or {}).get("description", "")}
        if was == entry:
            return model
        pending[task_id] = entry
        if entry["kind"] == "project":
            projects.append({"project_id": task_id, "goal": entry["description"], "status": status})
    focus = list(goals.get("recent_focus_areas", []))
    if area and (not focus or focus[-1] != area):
        focus = ([*focus, area])[-5:]
    goals.update(_pending=pending, pending_tasks=len(pending), active_projects=projects, recent_focus_areas=focus)
    return replace(model, goals=goals, updated_at=updated_at)


#: The mutations that are HISTORY rather than a derived view, by name,
#: as `(model, args, now) -> model`.
#:
#: The difference decides what is worth replaying at boot. Capabilities
#: and goals are re-derived from the world every time Sim starts -- the
#: tool registry announces itself, the task store is read -- so
#: replaying them would be recomputing what is already known. What
#: somebody learnt about Sim's competence, what it found it could not
#: do, the patches it landed and the skills it acquired are things that
#: HAPPENED, and a restart used to lose all of them: the module
#: docstring has said "not yet a fold of a durable stream" since it was
#: written, and every mutator below was left a pure function so that
#: sentence could one day be deleted (stage 6 item 1).
def restore_tools(model: SelfModel, table: dict, *, updated_at: float) -> SelfModel:
    """Put a persisted tool table back (stage 6 item 1).

    The aggregates only. `recent_ms` is deliberately not carried
    across a restart: it is a buffer for computing quantiles, the
    quantiles themselves ARE carried, and persisting 64 floats per
    tool for every tool in the registry would put a kilobyte of
    sample noise into the self stream on every snapshot for a number
    nobody reads to three decimal places.

    The cost is honest and small: after a restart the quantiles are
    the ones last measured and stay there until 64 fresh calls have
    replaced them, which is a few minutes of ordinary use.
    """
    keep = ("runs", "ok", "p_ok", "p50_ms", "p95_ms")
    out = dict(model.tool_stats)
    for name, entry in (table or {}).items():
        if not isinstance(entry, dict):
            continue
        kept = {k: entry[k] for k in keep if k in entry}
        if kept:
            out[str(name)] = {**out.get(str(name), {}), **kept, "recent_ms": []}
    return replace(model, tool_stats=out, updated_at=updated_at)


def tools_snapshot(model: SelfModel) -> dict:
    """What `restore_tools` takes: the aggregates, without the buffer."""
    keep = ("runs", "ok", "p_ok", "p50_ms", "p95_ms")
    return {name: {k: entry[k] for k in keep if k in entry}
            for name, entry in model.tool_stats.items()}


REPLAYABLE: dict = {
    "competence": lambda m, a, now: update_competence(
        m, str(a["task_type"]), updated_at=now, success_rate=a.get("success_rate"),
        samples=a.get("samples"), calibration=a.get("calibration"),
        stated_confidence=a.get("stated_confidence"), empirical_accuracy=a.get("empirical_accuracy")),
    "limitation": lambda m, a, now: add_limitation(
        m, text=str(a["text"]), evidence=list(a.get("evidence") or ()),
        since=float(a.get("since") or now), updated_at=now),
    "change": lambda m, a, now: add_change(
        m, ts=float(a.get("ts") or now), kind=str(a["kind"]), updated_at=now, subject=str(a.get("subject") or ""),
        commit=a.get("commit"), tests=a.get("tests"), summary=str(a.get("summary") or "")),
    "mitigate": lambda m, a, now: mitigate_limitations(m, subject=str(a["subject"]), updated_at=now),
    "skill": lambda m, a, now: add_skill(m, name=str(a["name"]), tests=int(a.get("tests") or 0), updated_at=now),
    "tool_stats": lambda m, a, now: restore_tools(m, dict(a.get("tool_stats") or {}), updated_at=now),
}


def replay(model: SelfModel, rule: str, args: dict, *, now: float) -> SelfModel:
    """One recorded change, applied. An unknown rule is ignored rather
    than fatal: an old stream written by a newer Sim must still load."""
    mutate = REPLAYABLE.get(rule)
    return model if mutate is None else mutate(model, dict(args or {}), now)


def render_summary(model: SelfModel, budget_tokens: int) -> tuple[str, int]:
    """Ordered, budget-truncated rendering (spec section 5's priority
    order) -- a `[truncated: ...]` marker is always included when a
    section is dropped, so a caller never silently reasons on a
    partial self (section 7's design point). ~4 chars/token estimate,
    matching this project's other rough token-budgeting (no tokenizer
    dependency in the core).
    """
    order = ("identity", "substrate", "competence", "tool_stats", "limitations", "goals", "capabilities",
             "change_history", "continuity", "open_questions")
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
    if section == "substrate":
        # What is actually doing the thinking. Second only to identity,
        # because "which model are you?" is a question about who is
        # answering, and Sim had no way to answer it: `capabilities
        # ["providers"]` was declared with the self model and filled by
        # nobody (live-caught by the creator, 2026-09-07).
        providers = model.capabilities.get("providers") or []
        if not providers:
            return None
        active = next((p for p in providers if p.get("selected")), None)
        others = [p for p in providers if p is not active]
        line = "Thinking with: "
        line += _provider_row(active) if active else "(no provider selected yet)"
        if others:
            line += ". Also configured: " + ", ".join(_provider_row(p) for p in others)
        return line + "."
    if section == "competence":
        if not model.competence:
            return "Competence: not yet tracked (no learn.competence.updated seen this session)."
        rows = sorted(model.competence.items(), key=lambda kv: kv[1].get("samples", 0), reverse=True)[:5]
        return "Competence: " + "; ".join(_competence_row(k, v) for k, v in rows)
    if section == "tool_stats":
        # Only the ones worth saying something about. A list of every
        # tool at 99% would be a wall of text the model reads past,
        # and this section exists so that "web_fetch fails a third of
        # the time" reaches the thing doing the planning.
        rough = slow_or_unreliable(model)
        if not rough:
            return None
        return "Tools to plan around: " + "; ".join(
            f"{r['tool']} {r['p_ok']:.0%} over {r['runs']}"
            + (f", p95 {r['p95_ms'] / 1000:.1f}s" if r["slow"] else "")
            for r in rough[:4])
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


def _provider_row(entry: dict) -> str:
    name, model = entry.get("name", "?"), entry.get("model", "")
    row = f"{name} ({model})" if model else name
    return row if entry.get("available", True) else row + " [unavailable]"


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
    """`(gaps, unexplored)`: the `k` task types of weakest measured
    competence, and the `k` capability areas no task type has been
    measured in.

    A gap's `score` is the success rate minus a pessimism term that
    shrinks with sample count (`1/sqrt(samples+1)`), so a type measured
    twice at 100% ranks below one measured thirty times at 85%: it is
    the least *known*, not only the least successful, that is worth
    exploring. Until 2026-09-19 this returned two empty lists, so
    Curiosity's gap drive saw a constant (2026-09-18 evaluation, C1/C2).
    """
    import math

    gaps: list[dict] = []
    for task_type, entry in (model.competence or {}).items():
        rate = entry.get("success_rate") if isinstance(entry, dict) else None
        samples = int((entry or {}).get("samples") or 0) if isinstance(entry, dict) else 0
        if rate is None or samples <= 0:
            continue
        score = float(rate) - 1.0 / math.sqrt(samples + 1)
        gaps.append({"competence": f"{float(rate):.0%} over {samples}", "task_type": task_type,
                     "score": round(score, 4), "samples": samples})
    gaps.sort(key=lambda g: (g["score"], g["task_type"]))
    measured = {tt.split(":", 1)[1] for tt in (model.competence or {}) if ":" in tt}
    unexplored: list[dict] = []
    for area in model.capabilities.get("areas", []) or []:
        name = area if isinstance(area, str) else (area.get("name") or area.get("area") or "")
        if name and name not in measured:
            unexplored.append({"area": name, "modules": [], "tasks_ever": 0})
    return gaps[:k], unexplored[:k]
