#!/usr/bin/env python3
"""modlock: module locks so several agents can change Simorgh at once.

The lock is a file in git (docs/modules/locks.toml).  Claiming a lock means
editing that file and committing it before touching the module; two agents
who claim the same module collide on the push, which is the point.

    python tools/modlock.py status                                   # who holds what, and what is stale
    python tools/modlock.py claim memory --by agent-7 --task "stage 5: fact store" [--hours 8]
    python tools/modlock.py release memory --by agent-7
    python tools/modlock.py check --by agent-7 [REF]                 # every changed file's module is free or mine

`check` is the pre-commit rule: it maps the working tree's changed files to
modules (the same mapping tools/modtest.py uses) and fails if any of them
is locked by someone else.  A lock past its `until` time is reported as
stale and treated as free.  Lockable names are the packages under
simorgh/, plus `simloader`, `tools`, `shared` (tests/simorgh/test_*.py)
and `docs`.

stdlib only.  tomllib reads the file; a tiny writer keeps it tidy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCKS = REPO / "docs" / "modules" / "locks.toml"
HEADER = """# Module locks for parallel agents.  See docs/AGENTS.md.
#
# Claim = add your entry here and COMMIT IT FIRST; release = remove it.
# `python tools/modlock.py claim|release|check|status` edits and reads this.
# A lock past `until` is stale and may be taken over.
"""

sys.path.insert(0, str(REPO / "tools"))
from modtest import changed_files, module_of, modules  # noqa: E402


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def load() -> dict[str, dict]:
    if not LOCKS.exists():
        return {}
    return dict(tomllib.loads(LOCKS.read_text()).get("locks", {}))


def save(locks: dict[str, dict]) -> None:
    lines = [HEADER]
    for name in sorted(locks):
        entry = locks[name]
        lines.append(f"\n[locks.{name}]")
        for key in ("by", "task", "since", "until"):
            if key in entry:
                val = str(entry[key]).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{val}"')
    LOCKS.parent.mkdir(parents=True, exist_ok=True)
    LOCKS.write_text("\n".join(lines) + "\n")


def stale(entry: dict) -> bool:
    until = entry.get("until")
    if not until:
        return False
    try:
        return dt.datetime.fromisoformat(str(until)) < now()
    except ValueError:
        return False


def lockable() -> set[str]:
    return set(modules()) | {"simloader", "tools", "shared", "docs"}


def cmd_status(_args) -> int:
    locks = load()
    if not locks:
        print("no locks held")
        return 0
    for name, e in sorted(locks.items()):
        flag = "  STALE" if stale(e) else ""
        print(f"{name:14} {e.get('by','?'):16} until {e.get('until','-')}  {e.get('task','')}{flag}")
    return 0


def cmd_claim(args) -> int:
    if args.module not in lockable():
        print(f"not a lockable module: {args.module}; one of {', '.join(sorted(lockable()))}", file=sys.stderr)
        return 2
    locks = load()
    held = locks.get(args.module)
    if held and held.get("by") != args.by and not stale(held):
        print(f"{args.module} is locked by {held.get('by')} until {held.get('until')}: {held.get('task','')}", file=sys.stderr)
        return 1
    t = now()
    locks[args.module] = {"by": args.by, "task": args.task, "since": t.isoformat(),
                          "until": (t + dt.timedelta(hours=args.hours)).isoformat()}
    save(locks)
    print(f"claimed {args.module} for {args.by} until {locks[args.module]['until']}; now commit docs/modules/locks.toml")
    return 0


def cmd_release(args) -> int:
    locks = load()
    held = locks.get(args.module)
    if not held:
        print(f"{args.module} is not locked")
        return 0
    if held.get("by") != args.by and not args.force:
        print(f"{args.module} is locked by {held.get('by')}, not {args.by} (use --force to take it over)", file=sys.stderr)
        return 1
    del locks[args.module]
    save(locks)
    print(f"released {args.module}; commit docs/modules/locks.toml")
    return 0


def cmd_check(args) -> int:
    locks = load()
    files = changed_files(args.ref)
    touched = sorted({m for m in (module_of(f) for f in files) if m})
    if any(f.startswith("docs/") for f in files):
        touched.append("docs")
    problems = []
    for m in touched:
        e = locks.get(m)
        if e and e.get("by") != args.by and not stale(e):
            problems.append(f"{m}: locked by {e.get('by')} until {e.get('until')} ({e.get('task','')})")
        elif args.strict and (not e or e.get("by") != args.by):
            problems.append(f"{m}: not locked by {args.by} (strict mode)")
    print(f"changed modules: {', '.join(touched) or '(none)'}")
    for p in problems:
        print("BLOCKED " + p)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="modlock", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    c = sub.add_parser("claim"); c.add_argument("module"); c.add_argument("--by", required=True); c.add_argument("--task", required=True)
    c.add_argument("--hours", type=float, default=8.0); c.set_defaults(fn=cmd_claim)
    r = sub.add_parser("release"); r.add_argument("module"); r.add_argument("--by", required=True); r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_release)
    k = sub.add_parser("check"); k.add_argument("ref", nargs="?", default=None); k.add_argument("--by", required=True)
    k.add_argument("--strict", action="store_true", help="also fail when a touched module is not locked by --by")
    k.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
