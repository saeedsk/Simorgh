"""Agent Skills: parse `SKILL.md` folders (docs/plans/agent-skills-design.md).

The open Agent Skills format: a skill is a folder holding `SKILL.md` --
YAML frontmatter with at least `name` and `description`, then Markdown
instructions -- plus any scripts or reference files it bundles. Only the
name and description ride in every task (`catalog_text`); the body is read
when a task asks for the skill (`load_body`).

Pure and stdlib-only, like the rest of `contracts`: PyYAML is used when it
is installed, and a small reader covers the frontmatter skills actually use
(scalars, quoted strings, inline `[a, b]` lists and `- item` lists).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
MAX_DESCRIPTION = 1024
MAX_BODY_CHARS = 12_000


@dataclass(frozen=True)
class SkillCard:
    name: str
    description: str
    source: str
    path: Path
    allowed_profiles: tuple[str, ...] = ()
    sha256: str = ""
    meta: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class InvalidSkill:
    path: Path
    reason: str


def _scalar(value: str):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(v) for v in value[1:-1].split(",") if v.strip()]
    return value


def _read_frontmatter(text: str) -> dict:
    try:
        import yaml  # optional third party

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 -- malformed YAML: fall back to the simple reader
        pass
    data: dict = {}
    key = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(_scalar(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if pair:
            key = pair.group(1)
            data[key] = _scalar(pair.group(2)) if pair.group(2).strip() else []
    return data


def split_frontmatter(text: str) -> tuple[dict, str] | None:
    """`(frontmatter, body)`, or None when the file does not open with a
    `---` block."""
    match = re.match(r"^﻿?---\s*\n(.*?)\n---\s*(?:\n|$)(.*)$", text, re.S)
    if not match:
        return None
    return _read_frontmatter(match.group(1)), match.group(2)


def parse_skill(skill_md: Path, *, source: str) -> SkillCard | InvalidSkill:
    try:
        raw = skill_md.read_bytes()
    except OSError as exc:
        return InvalidSkill(skill_md, f"unreadable: {exc}")
    text = raw.decode("utf-8", errors="replace")
    parts = split_frontmatter(text)
    if parts is None:
        return InvalidSkill(skill_md, "no frontmatter: SKILL.md must open with a --- block")
    front, _body = parts
    name = str(front.get("name") or "").strip()
    description = " ".join(str(front.get("description") or "").split())
    if not NAME_RE.match(name):
        return InvalidSkill(skill_md, f"invalid name {name!r}: lowercase letters, digits and hyphens, at most 64")
    if not description:
        return InvalidSkill(skill_md, "missing description")
    if len(description) > MAX_DESCRIPTION:
        return InvalidSkill(skill_md, f"description longer than {MAX_DESCRIPTION} characters")
    profiles = front.get("allowed_profiles") or front.get("allowed-profiles") or ()
    if isinstance(profiles, str):
        profiles = [p.strip() for p in profiles.split(",") if p.strip()]
    return SkillCard(
        name=name, description=description, source=source, path=skill_md.parent,
        allowed_profiles=tuple(str(p) for p in profiles), sha256=hashlib.sha256(raw).hexdigest(),
        meta={k: v for k, v in front.items() if k not in ("name", "description")},
    )


def discover_skills(roots: list[tuple[str, Path]]) -> tuple[list[SkillCard], list[InvalidSkill]]:
    """Every `SKILL.md` under each `(source, root)`, first root winning a
    name clash. Invalid skills are returned with a reason, never raised."""
    cards: dict[str, SkillCard] = {}
    invalid: list[InvalidSkill] = []
    for source, root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            parsed = parse_skill(skill_md, source=source)
            if isinstance(parsed, InvalidSkill):
                invalid.append(parsed)
            elif parsed.name in cards:
                invalid.append(InvalidSkill(skill_md, f"duplicate name {parsed.name!r}; {cards[parsed.name].path} is used"))
            else:
                cards[parsed.name] = parsed
    return sorted(cards.values(), key=lambda c: c.name), invalid


def catalog_text(cards: list[SkillCard], *, profile: str = "", max_chars: int = 3000) -> str:
    """The skills a task may ask for, one line each, within `max_chars`."""
    lines: list[str] = []
    used = 0
    for card in cards:
        if card.allowed_profiles and profile and profile not in card.allowed_profiles:
            continue
        line = f"- {card.name}: {card.description}"
        if used + len(line) + 1 > max_chars:
            lines.append(f"- ... ({len(cards) - len(lines)} more not listed)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def load_body(card: SkillCard, *, max_chars: int = MAX_BODY_CHARS) -> str:
    """The skill's instructions (the Markdown after its frontmatter)."""
    parts = split_frontmatter((card.path / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    body = (parts[1] if parts else "").strip()
    return body if len(body) <= max_chars else body[:max_chars] + "\n\n[... cut; read the rest of SKILL.md with read_file]"


__all__ = ["InvalidSkill", "SkillCard", "catalog_text", "discover_skills", "load_body", "parse_skill", "split_frontmatter"]
