"""Per-kind Profiles (16 section 5), loaded from the agent definitions
in `agents/*.md` (stage 4 item 7). The tools, limits and scaffold of each
agent -- and the incidents behind them -- live in those files now.
"""

from __future__ import annotations

from .api import Profile

import re
import tomllib
from pathlib import Path

#: Where the agent definitions live (stage 4 item 7): one Markdown file per
#: agent, TOML frontmatter between `+++` lines, the scaffold as its body.
#: `<!-- -->` notes in the body are for people and never reach the prompt.
#: Guardian protects the folder (`guardian/config.py`), like the code.
AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
#: Adopted lessons, one file per kind of work (`rules/<agent>.md`), put
#: after the agent's own body (stage 8 item 5). Protected like
#: `agents/`: the growth loop may propose a rule, and a person puts it
#: here. Until 2026-09-22 nothing read this folder, so an adopted
#: policy changed nothing Sim did.
RULES_DIR = Path(__file__).resolve().parents[2] / "rules"

_FIELDS = ("tools", "read_only", "max_steps", "max_revisions", "scaffold", "max_output_tokens", "verify")
_NOTES = re.compile(r"<!--.*?-->\n?", re.S)


class AgentFileError(ValueError):
    """An agent definition that cannot be read, said with its file."""


def parse(text: str, *, source: str = "") -> tuple[dict, str]:
    """`(frontmatter, body)` of one agent file."""
    if not text.startswith("+++\n"):
        raise AgentFileError(f"{source}: must start with a `+++` frontmatter block")
    head, sep, body = text[4:].partition("\n+++\n")
    if not sep:
        raise AgentFileError(f"{source}: the frontmatter block is not closed with `+++`")
    try:
        meta = tomllib.loads(head)
    except tomllib.TOMLDecodeError as exc:
        raise AgentFileError(f"{source}: {exc}") from exc
    unknown = set(meta) - set(_FIELDS) - {"name", "extends"}
    if unknown:
        # A key nothing reads is the unconnected wire this project keeps finding.
        raise AgentFileError(f"{source}: unknown keys {sorted(unknown)} (known: name, extends, {', '.join(_FIELDS)})")
    return meta, _NOTES.sub("", body).strip()


def rules_for(name: str, directory: Path = RULES_DIR) -> str:
    """The adopted lessons for agent `name`, as a block for its body,
    or "" when there are none."""
    path = Path(directory) / f"{name}.md"
    try:
        text = _NOTES.sub("", path.read_text(encoding="utf-8")).strip()
    except OSError:
        return ""
    return f"Lessons adopted for this kind of work:\n{text}" if text else ""


def load(directory: Path = AGENTS_DIR, rules: Path | None = RULES_DIR) -> dict[str, Profile]:
    """Every agent under `directory`, keyed by file name. `extends` takes
    another agent's fields and body, then overrides what it names; an
    agent's `rules/<name>.md`, when there is one, follows its body."""
    raw = {}
    for path in sorted(Path(directory).glob("*.md")):
        raw[path.stem] = parse(path.read_text(encoding="utf-8"), source=str(path))
    out: dict[str, Profile] = {}

    def build(key: str, seen: tuple = ()) -> Profile:
        if key in out:
            return out[key]
        if key in seen:
            raise AgentFileError(f"{key}: `extends` goes round in a circle ({' -> '.join(seen + (key,))})")
        if key not in raw:
            raise AgentFileError(f"no agent called {key!r} in {directory}")
        meta, body = raw[key]
        base = build(meta["extends"], seen + (key,)) if meta.get("extends") else None
        fields = {f: getattr(base, f) for f in _FIELDS} if base else {}
        fields.update({f: meta[f] for f in _FIELDS if f in meta})
        fields["tools"] = tuple(fields.get("tools") or ())
        missing = [f for f in ("tools", "read_only", "max_steps", "max_revisions", "scaffold") if f not in fields]
        if missing:
            raise AgentFileError(f"{key}: missing {missing}")
        body = body or (base.body if base else "")
        lessons = rules_for(key, rules) if rules is not None else ""
        if lessons and lessons not in body:
            body = f"{body}\n\n{lessons}" if body else lessons
        out[key] = Profile(name=str(meta.get("name") or (base.name if base else key)), body=body, **fields)
        return out[key]

    for key in raw:
        build(key)
    return out


AGENTS: dict[str, Profile] = load()
CHAT = AGENTS["chat"]
PATCH = AGENTS["patch"]
RESEARCH = AGENTS["research"]
PLAN = AGENTS["plan"]
SKILL = AGENTS["skill"]
# A SPOKEN chat turn: answered from what the model knows, quickly; a spoken
# request for work becomes a task (`start_task`). See agents/voice_chat.md.
VOICE_CHAT = AGENTS["voice_chat"]


def for_percept(channel: str) -> Profile:
    """The profile for a conversational percept on `channel`."""
    return VOICE_CHAT if channel == "voice" else CHAT


BY_KIND: dict[str, Profile] = {
    "chat": CHAT,
    "patch": PATCH,
    "research": RESEARCH,
    "project": PLAN,  # mode=plan sessions use the plan profile regardless of task kind
    "skill": SKILL,
}


def for_task(kind: str, mode: str) -> Profile:
    if mode == "plan":
        return PLAN
    return BY_KIND.get(kind, CHAT)


def for_claimed(kind: str, mode: str, *, origin: str = "", review_benchmark: bool = True) -> Profile:
    """The profile for a claimed task: `for_task`, with Verification
    switched off for a benchmark case when `[orchestration]
    review_benchmark` is false -- the one knob a wave needs to measure
    what the reviewer costs and gains."""
    profile = for_task(kind, mode)
    if origin == "benchmark" and not review_benchmark and profile.verify:
        from dataclasses import replace

        return replace(profile, verify=False)
    return profile
