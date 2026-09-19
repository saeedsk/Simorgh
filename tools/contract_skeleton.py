#!/usr/bin/env python3
"""contract_skeleton: draft a module's CONTRACT.md from the code.

The tables a contract needs are facts the tree already holds: which
topics a package subscribes to and publishes (grep for `topics.X` next to
a subscribe/publish call), which ledger streams it names, which config
keys its dataclass declares and which of them are read, which test files
exist, how big it is.  This writes those tables so a person (or an agent)
only has to write the prose: Purpose, Invariants, Working on this module.

    python tools/contract_skeleton.py memory            # print the draft
    python tools/contract_skeleton.py memory --write    # write simorgh/memory/CONTRACT.md if absent
    python tools/contract_skeleton.py --all --write     # every module without a CONTRACT.md

The draft marks every prose section `TODO` so a half-finished contract is
visibly half-finished.  Detection is textual and generous; check the
tables against the code before trusting them.  stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_NAME = re.compile(r"\btopics\.([A-Z_][A-Z0-9_]+)\b")
_PUB = re.compile(r"publish|request\(|request_or_error|Message\.new|reply\(|reply_to|produces|_emit|emit\(|announce")
_SUB = re.compile(r"subscribe\s*\(|consumes|_on_[a-z_]+|case\s+topics\.|==\s*topics\.")
_STREAM = re.compile(r'''["']([a-z][a-z0-9_]*:[a-z0-9_:<>{}.\-]*)["']''')

LAYERS = {"bus": 0, "ledger": 0, "kernel": 0, "telemetry": 0, "contracts": "shared", "cognition": 2, "memory": 2, "worldmodel": 2,
          "planning": 3, "guardian": 3, "execution": 3, "verification": 3, "learning": 4, "reflection": 4,
          "curiosity": 4, "persona": 5, "benchmark": 5, "voice": 5, "interface": 5, "orchestration": "X"}
PROTECTED = {"guardian", "execution", "contracts", "kernel"}


def _topics():
    from simorgh.contracts import topics as T
    return {n: v for n, v in vars(T).items() if n.isupper() and isinstance(v, str) and "." in v
            and n not in ("DOMAINS", "SUBSYSTEMS", "WILDCARD_ALL")}


def _schema_symbol(value: str) -> str:
    """The `contracts/messages/<file>.py` symbol that defines a topic."""
    for path in (REPO / "simorgh/contracts/messages").glob("*.py"):
        text = path.read_text(errors="replace")
        for m in re.finditer(r"^(\w+)\s*=\s*define\(t\.([A-Z_]+)", text, re.M):
            if _topics().get(m.group(2)) == value:
                return f"messages/{path.stem}.py::{m.group(1)}"
    return "-"


def scan(module: str) -> dict:
    consts = _topics()
    pkg = REPO / "simorgh" / module
    files = sorted(p for p in pkg.rglob("*.py") if "__pycache__" not in p.parts)
    sub: dict[str, set[str]] = {}
    pub: dict[str, set[str]] = {}
    streams: dict[str, set[str]] = {}
    loc = 0
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        lines = path.read_text(errors="replace").split("\n")
        loc += len(lines)
        for i, line in enumerate(lines):
            for m in _NAME.finditer(line):
                if m.group(1) not in consts:
                    continue
                value = consts[m.group(1)]
                window = "\n".join(lines[max(0, i - 6): i + 2])
                if _SUB.search(window):
                    sub.setdefault(value, set()).add(rel)
                if _PUB.search(window):
                    pub.setdefault(value, set()).add(rel)
            for m in _STREAM.finditer(line):
                s = m.group(1)
                if len(s) < 60 and not s.startswith(("http:", "https:", "file:")):
                    streams.setdefault(s, set()).add(rel)
    # who else reads the streams this module names
    readers: dict[str, set[str]] = {}
    for s in streams:
        base = s.split("<", 1)[0].split("{", 1)[0]
        if len(base) < 4:
            continue
        for path in (REPO / "simorgh").rglob("*.py"):
            if module in path.parts or "__pycache__" in path.parts:
                continue
            if base in path.read_text(errors="replace"):
                readers.setdefault(s, set()).add(path.relative_to(REPO).as_posix())
    tests = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "tests/simorgh" / module).rglob("test_*.py")) \
        if (REPO / "tests/simorgh" / module).exists() else []
    return {"files": [p.relative_to(REPO).as_posix() for p in files], "loc": loc, "sub": sub, "pub": pub,
            "streams": streams, "readers": readers, "tests": tests, "config": _config(module)}


def _config(module: str) -> list[tuple[str, str, bool]]:
    """(field, default, read_somewhere) for the module's Config dataclass."""
    path = REPO / "simorgh" / module / "config.py"
    if not path.exists():
        return []
    tree = ast.parse(path.read_text())
    out = []
    pkg_text = "\n".join(p.read_text(errors="replace") for p in (REPO / "simorgh" / module).rglob("*.py")
                         if p.name != "config.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in ("Config", "RuntimeConfig", "VerificationConfig"):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    name = item.target.id
                    default = ast.unparse(item.value) if item.value is not None else "-"
                    read = bool(re.search(rf"\.{re.escape(name)}\b", pkg_text)) or bool(
                        re.search(rf"[\"']{re.escape(name)}[\"']", pkg_text))
                    out.append((name, default[:60], read))
    return out


def render(module: str, info: dict) -> str:
    layer = LAYERS.get(module, "?")
    lines = [f"# {module} -- contract", "",
             f"One-line status: layer {layer} · {info['loc']:,} lines · {len(info['tests'])} test files · lock: `{module}` in docs/modules/locks.toml",
             "", "## Purpose", "", "TODO: 3-6 sentences: what this module owns, what it must never do, the one design decision that shapes it.", "",
             "## Files", "", "| File | For |", "|---|---|"]
    for f in info["files"]:
        lines.append(f"| `{f}` | TODO |")
    lines += ["", "## Consumes", "", "| Topic | Schema | Where | Does |", "|---|---|---|---|"]
    for t in sorted(info["sub"]):
        lines.append(f"| `{t}` | `{_schema_symbol(t)}` | {', '.join(sorted(info['sub'][t]))} | TODO |")
    lines += ["", "## Produces", "", "| Topic | Schema | Where | When |", "|---|---|---|---|"]
    for t in sorted(info["pub"]):
        lines.append(f"| `{t}` | `{_schema_symbol(t)}` | {', '.join(sorted(info['pub'][t]))} | TODO |")
    lines += ["", "## Ledger streams", "", "| Stream | Named in | Also read by | Retention |", "|---|---|---|---|"]
    for s in sorted(info["streams"]):
        lines.append(f"| `{s}` | {', '.join(sorted(info['streams'][s]))} | {', '.join(sorted(info['readers'].get(s, ()))) or '-'} | see ledger/compaction.py DEFAULT_RETENTION |")
    lines += ["", "## Config", "", f"`[{module}]` in simorgh.toml; dataclass in `simorgh/{module}/config.py`.", "",
              "| Key | Default | Read in the package |", "|---|---|---|"]
    for name, default, read in info["config"]:
        lines.append(f"| `{name}` | `{default}` | {'yes' if read else 'NO (declared, never read)'} |")
    lines += ["", "## Public Python surface", "",
              "TODO: the `Service` class; any `api.py` types other packages import via contracts; module-level singletons (risks).", "",
              "## Invariants", "", "TODO: the rules that must hold, as testable sentences; include contracts/topics.py policy entries naming this module.", "",
              "## Contract tests", "", "The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract " + module + "`.", ""]
    for t in info["tests"]:
        lines.append(f"- `{t}` -- TODO: what it pins")
    lines += ["", "## Known issues (2026-09-18 evaluation)", "",
              "TODO: catalogue ids from docs/reviews/2026-09-18/architecture-evaluation.md section 13 that name this module.", "",
              "## Planned changes (roadmap)", "", "TODO: stage numbers from docs/plan/ and what changes here.", "",
              "## Working on this module", "",
              f"Lock it first (`python tools/modlock.py claim {module} --by <you> --task \"...\"`), commit the lock, edit only `simorgh/{module}/`, `tests/simorgh/{module}/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py {module}` before committing; commit subject `{module}: <what changed>`."]
    if module in PROTECTED:
        lines.append(f"\nThis package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing CONTRACT.md")
    args = ap.parse_args(argv)
    mods = args.modules
    if args.all:
        mods = sorted(p.name for p in (REPO / "simorgh").iterdir() if p.is_dir() and (p / "__init__.py").exists())
    if not mods:
        ap.error("name a module or pass --all")
    for m in mods:
        text = render(m, scan(m))
        target = REPO / "simorgh" / m / "CONTRACT.md"
        if args.write:
            if target.exists() and not args.force:
                print(f"{target.relative_to(REPO)}: exists, left alone")
                continue
            target.write_text(text)
            print(f"wrote {target.relative_to(REPO)} ({text.count(chr(10))} lines)")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
