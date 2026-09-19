#!/usr/bin/env python3
"""modtest: run the tests that matter for the module(s) you touched.

The full suite is for the nightly bless and for landing a change to the
substrate.  Day to day, an agent working on one module runs that module's
tests plus the shared tests that pin the rules every module lives under.

    python tools/modtest.py memory                 # module tier: tests/simorgh/memory + shared pins
    python tools/modtest.py memory voice           # several modules
    python tools/modtest.py --changed              # modules derived from `git diff` (working tree vs HEAD)
    python tools/modtest.py --changed main         # ... vs a ref
    python tools/modtest.py --tier contract memory # only the files CONTRACT.md lists under "## Contract tests"
    python tools/modtest.py --tier core            # simloader's core gate (what a boot runs, ~45 s)
    python tools/modtest.py --tier full            # everything except tests marked `live`
    python tools/modtest.py --list --changed       # show what would run, run nothing
    python tools/modtest.py memory -- -k recall -x # anything after `--` goes to pytest

Tiers, smallest first:
  contract  the 3-8 files a module's CONTRACT.md names: the interface pins (seconds)
  module    tests/simorgh/<module> for each module, plus the shared pins (tens of seconds)
  core      simloader.gate_selection(): what every boot gates on (about 45 s on 12 cores)
  full      tests/ minus `live` (minutes; before a bless, nightly, or after a contracts change)

Path -> module mapping: simorgh/<m>/... and tests/simorgh/<m>/... -> m;
tests/simorgh/test_*.py -> shared; simloader.py -> simloader; tools/ -> tools;
docs and markdown -> nothing.  Touching a substrate module (bus, ledger, telemetry,
kernel, contracts) also pulls in the integration files the boot gate
runs, because every other module sits on them.

stdlib only, like simloader.py, so it runs on a bare checkout.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests" / "simorgh"
SUBSTRATE = {"bus", "ledger", "kernel", "contracts", "telemetry"}

# Tests every module change must keep green: the import rule, the config
# rule, and session isolation are properties of the whole tree.
SHARED_PINS = (
    "tests/simorgh/test_module_boundaries.py",
    "tests/simorgh/test_every_subsystem_reads_its_config.py",
)
# What a substrate change additionally has to prove.
SUBSTRATE_PINS = (
    "tests/simorgh/test_session_isolation.py",
    "tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py",
    "tests/simorgh/integration/test_guardian_execution_action_path.py",
    "tests/simorgh/integration/test_cli_end_to_end.py",
)
SPECIAL = {
    "simloader": ("tests/simorgh/test_simloader.py",),
    "tools": ("tests/tools",),
    "shared": SHARED_PINS + ("tests/simorgh/test_session_isolation.py",),
}


def modules() -> list[str]:
    return sorted(p.name for p in (REPO / "simorgh").iterdir()
                  if p.is_dir() and (p / "__init__.py").exists() and not p.name.startswith("__"))


def module_of(path: str) -> str | None:
    parts = Path(path).parts
    if not parts:
        return None
    if parts[0] == "simorgh" and len(parts) > 2:
        return parts[1]
    if parts[0] == "tests" and len(parts) > 1 and parts[1] == "simorgh":
        if len(parts) > 3:
            return parts[2]
        return "shared" if len(parts) == 3 and parts[2].startswith("test_") else None
    if parts[0] == "tests" and len(parts) > 1 and parts[1] == "tools":
        return "tools"
    if parts[0] == "tools":
        return "tools"
    if parts[0] == "simloader.py":
        return "simloader"
    return None


def changed_files(ref: str | None) -> list[str]:
    cmds = [["git", "diff", "--name-only", ref] if ref else ["git", "diff", "--name-only"],
            ["git", "diff", "--name-only", "--cached"],
            ["git", "ls-files", "--others", "--exclude-standard"]]
    seen: list[str] = []
    for cmd in cmds:
        out = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        for line in out.stdout.splitlines():
            line = line.strip()
            if line and line not in seen:
                seen.append(line)
    return seen


def contract_tests(module: str) -> list[str]:
    """Paths named under '## Contract tests' in simorgh/<module>/CONTRACT.md."""
    doc = REPO / "simorgh" / module / "CONTRACT.md"
    if not doc.exists():
        return []
    text = doc.read_text(errors="ignore")
    m = re.search(r"^## Contract tests\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return []
    found: list[str] = []
    for hit in re.findall(r"tests/[\w./-]+\.py", m.group(1)):
        if (REPO / hit).exists() and hit not in found:
            found.append(hit)
    return found


def selection(mods: list[str], tier: str) -> list[str]:
    paths: list[str] = []

    def add(p: str) -> None:
        if p not in paths and (REPO / p).exists():
            paths.append(p)

    if tier == "contract":
        for m in mods:
            ct = contract_tests(m)
            if not ct:
                print(f"[modtest] {m}: CONTRACT.md names no contract tests; using the module tier for it", file=sys.stderr)
                ct = [f"tests/simorgh/{m}"]
            for p in ct:
                add(p)
        for p in SHARED_PINS:
            add(p)
        return paths

    for m in mods:
        if m in SPECIAL:
            for p in SPECIAL[m]:
                add(p)
            continue
        add(f"tests/simorgh/{m}")
    if any(m not in SPECIAL for m in mods):
        for p in SHARED_PINS:
            add(p)
    if SUBSTRATE & set(mods):
        for p in SUBSTRATE_PINS:
            add(p)
    return paths


def core_selection() -> list[str]:
    sys.path.insert(0, str(REPO))
    import simloader  # stdlib-only; lives at the repo root
    return simloader.gate_selection(REPO, all_tests=False)


def main(argv: list[str]) -> int:
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="modtest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*", help="module names (directories under simorgh/), or simloader, tools, shared")
    ap.add_argument("--changed", nargs="?", const="HEAD", metavar="REF", help="derive modules from git diff against REF (default HEAD) plus the working tree")
    ap.add_argument("--tier", choices=("contract", "module", "core", "full"), default="module")
    ap.add_argument("--list", action="store_true", help="print the selection and exit")
    ap.add_argument("--live", action="store_true", help="include tests marked live (network, Docker, browser, this machine's tools)")
    ap.add_argument("--serial", action="store_true", help="no xdist even when installed")
    args = ap.parse_args(argv)

    mods = list(args.modules)
    if args.changed is not None:
        files = changed_files(None if args.changed == "HEAD" else args.changed)
        derived = sorted({m for m in (module_of(f) for f in files) if m})
        if not derived and args.tier in ("contract", "module"):
            print("[modtest] no source or test changes found; nothing to run (use --tier core or full to run anyway)")
            return 0
        mods = sorted(set(mods) | set(derived))
        print(f"[modtest] changed files map to modules: {', '.join(mods) or '(none)'}")

    known = set(modules()) | set(SPECIAL)
    unknown = [m for m in mods if m not in known]
    if unknown:
        print(f"[modtest] unknown module(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}", file=sys.stderr)
        return 2

    if args.tier == "core":
        sel = core_selection()
    elif args.tier == "full":
        sel = ["tests"]
    else:
        if not mods:
            ap.error("name at least one module, or use --changed, or --tier core|full")
        sel = selection(mods, args.tier)
    if not sel:
        print("[modtest] nothing selected")
        return 0

    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if "-m" not in sel:
        # The contract and module tiers skip `slow` too (docs/testing.md);
        # core and full run everything but `live`.
        markers = [] if args.live else ["not live"]
        if args.tier in ("contract", "module"):
            markers.append("not slow")
        if markers:
            cmd += ["-m", " and ".join(markers)]
    try:
        import xdist  # noqa: F401
        parallel = not args.serial and (args.tier in ("core", "full") or len(sel) >= 6 or any(not p.endswith(".py") for p in sel))
    except ImportError:
        parallel = False
    if parallel:
        cmd += ["-n", "auto"]
    cmd += sel + extra

    print("[modtest] " + " ".join(cmd[2:]))
    if args.list:
        return 0
    started = time.monotonic()
    rc = subprocess.call(cmd, cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    print(f"[modtest] tier={args.tier} modules={','.join(mods) or '-'} exit={rc} in {time.monotonic() - started:.1f}s")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
