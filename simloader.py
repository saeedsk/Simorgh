#!/usr/bin/env python3
"""The Sim loader: a bootloader for a program that edits its own source.

The creator, 2026-09-07: "at start up we should have an independent sim
loader module, it acts like boot loader in embedded systems, where this
sim loader code has simple but reliable logic ... at first run it would
checkout the latest and most recent label of sim project, set some
watchdog timer, and load and run sim. If sim boots up and can pass all
unit tests successfully, we accept this run and tag it ... if the code is
not reliable or the test cannot be passed, sim loader will switch to the
previous git release label ... until a stable code can be found (capped)
... the whole process should be visible to user."

That is the A/B-image pattern from embedded systems, and it works there
for one reason this file has to honour above all others: **the loader
never runs the code it is judging.** So:

- This file is stdlib only. It does not import `simorgh`. If the package
  is broken enough to fail at import, this still runs.
- Sim commits; the loader tags. A tag is a statement by the loader that
  it independently verified that commit. Sim cannot bless itself.
- Every decision is printed as it is made, and every rollback is written
  where Sim will read it on its next boot (`--notes`), so a regression
  it caused is something it can learn from rather than repeat.

Known-good tags are `sim-good-<n>`, monotonically numbered. The gate that
earns one is the unit suite plus the scored trial suite -- because this
week 2,600 passing tests sat on top of a system that could not write a
file, and the trial suite is the check that would have caught it.

Usage:

    python simloader.py run              boot the latest known-good, verify, run Sim
    python simloader.py bless            gate HEAD and, if green, tag it known-good
    python simloader.py status           what is tagged, what would roll back to what
    python simloader.py rollback         step back one known-good tag, deliberately

`run` is what sim.sh should call. Its loop: gate the checkout, and if the
gate fails, step back one tag and try again, up to `--max-rollbacks`.
Once the gate passes it hands off to Sim, with a start-up watchdog: if
Sim exits non-zero inside `--watchdog` seconds, that counts as a bad
image too.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TAG_PREFIX = "sim-good-"
_TAG = re.compile(rf"^{re.escape(TAG_PREFIX)}(\d+)$")
DEFAULT_NOTES = Path("~/.simorgh/loader").expanduser()


# ---------------------------------------------------------------- output
def say(line: str) -> None:
    print(f"[simloader] {line}", flush=True)


def rule(title: str) -> None:
    print(f"\n[simloader] ── {title} " + "─" * max(0, 60 - len(title)), flush=True)


# ------------------------------------------------------------------- git
def git(*args: str, cwd: Path, check: bool = False) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(done.stderr or done.stdout).strip()}")
    return done


def head(repo: Path) -> str:
    return git("rev-parse", "--short", "HEAD", cwd=repo, check=True).stdout.strip()


def is_dirty(repo: Path) -> bool:
    """Tracked changes only. An untracked file (a paper the creator
    dropped in `papers/`, a scratch script) is neither something a
    rollback can lose -- `git checkout <tag>` leaves untracked paths
    alone -- nor something Sim committed, so it must not block a bless
    or a rollback."""
    return bool(git("status", "--porcelain", "--untracked-files=no", cwd=repo).stdout.strip())


def untracked(repo: Path) -> list[str]:
    out = git("status", "--porcelain", "--untracked-files=all", cwd=repo).stdout
    return [line[3:] for line in out.splitlines() if line.startswith("?? ")]


def good_tags(repo: Path) -> list[tuple[int, str]]:
    """Every known-good tag, oldest first."""
    out = git("tag", "--list", f"{TAG_PREFIX}*", cwd=repo).stdout.split()
    found = []
    for tag in out:
        match = _TAG.match(tag)
        if match:
            found.append((int(match.group(1)), tag))
    return sorted(found)


def tag_of(repo: Path, tag: str) -> str:
    return git("rev-parse", "--short", f"{tag}^{{commit}}", cwd=repo, check=True).stdout.strip()


def next_tag(repo: Path) -> str:
    tags = good_tags(repo)
    return f"{TAG_PREFIX}{(tags[-1][0] + 1) if tags else 1:04d}"


# ------------------------------------------------------------------ gate
def run_gate(repo: Path, *, full: bool, timeout_s: float) -> tuple[bool, str]:
    """Is this checkout fit to run? Returns (ok, why)."""
    started = time.monotonic()
    rule("gate: unit suite")
    try:
        tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            cwd=repo, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return False, f"unit suite exceeded {timeout_s:.0f}s"
    tail = (tests.stdout.strip().splitlines() or [""])[-1]
    say(f"unit suite: {tail}  ({time.monotonic() - started:.0f}s)")
    if tests.returncode not in (0, 5):
        return False, f"unit suite failed: {tail}"
    if not full:
        return True, "unit suite green"

    rule("gate: scored trial suite")
    remaining = max(60.0, timeout_s - (time.monotonic() - started))
    try:
        trials = subprocess.run(
            [sys.executable, "-u", "tools/trial_suite.py"],
            cwd=repo, capture_output=True, text=True, timeout=remaining, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return False, f"trial suite exceeded {remaining:.0f}s"
    for line in trials.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL", "        -")) or "clean" in line:
            say(line.strip())
    if trials.returncode != 0:
        return False, "trial suite had failures"
    return True, "unit suite and trial suite green"


# ----------------------------------------------------------------- notes
def write_note(notes: Path, note: dict) -> None:
    """Where Sim reads what the loader did on its behalf. Append-only
    JSONL, one decision per line."""
    notes.mkdir(parents=True, exist_ok=True)
    note = {"ts": time.time(), **note}
    with open(notes / "decisions.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(note) + "\n")
    # The latest rollback, on its own, for a cheap read at boot.
    if note.get("kind") == "rollback":
        (notes / "last_rollback.json").write_text(json.dumps(note, indent=1), encoding="utf-8")


# ------------------------------------------------------------- commands
def cmd_status(repo: Path, notes: Path) -> int:
    rule("status")
    tags = good_tags(repo)
    say(f"repo: {repo}")
    say(f"HEAD: {head(repo)}{'  (dirty)' if is_dirty(repo) else ''}")
    stray = untracked(repo)
    if stray:
        say(f"untracked (ignored by the gate's dirty check): {', '.join(stray[:5])}{' ...' if len(stray) > 5 else ''}")
    if not tags:
        say("known-good tags: none yet -- run `bless` after a green gate")
        return 0
    for number, tag in tags[-5:]:
        say(f"  {tag}  ->  {tag_of(repo, tag)}")
    say(f"latest known-good: {tags[-1][1]}")
    if len(tags) > 1:
        say(f"would roll back to: {tags[-2][1]}")
    last = notes / "last_rollback.json"
    if last.exists():
        say(f"last rollback: {last.read_text().strip()[:200]}")
    return 0


def cmd_bless(repo: Path, notes: Path, *, full: bool, timeout_s: float) -> int:
    rule("bless")
    if is_dirty(repo):
        say("refusing: the working tree has uncommitted changes -- commit or stash them first")
        return 2
    commit = head(repo)
    for _number, tag in good_tags(repo):
        if tag_of(repo, tag) == commit:
            say(f"{commit} is already {tag}")
            return 0
    ok, why = run_gate(repo, full=full, timeout_s=timeout_s)
    if not ok:
        say(f"NOT blessed: {why}")
        write_note(notes, {"kind": "bless_refused", "commit": commit, "why": why})
        return 1
    tag = next_tag(repo)
    git("tag", "-a", tag, "-m", f"simloader: {why}", cwd=repo, check=True)
    say(f"blessed {commit} as {tag}  ({why})")
    write_note(notes, {"kind": "blessed", "commit": commit, "tag": tag, "why": why})
    return 0


def cmd_rollback(repo: Path, notes: Path, *, reason: str) -> int:
    rule("rollback")
    tags = good_tags(repo)
    if is_dirty(repo):
        say("refusing: the working tree has uncommitted changes; a rollback would discard them")
        return 2
    current = head(repo)
    older = [tag for _n, tag in tags if tag_of(repo, tag) != current]
    if not older:
        say("nothing older to roll back to")
        return 1
    target = older[-1]
    git("checkout", "-q", target, cwd=repo, check=True)
    say(f"rolled back {current} -> {target} ({tag_of(repo, target)}): {reason}")
    write_note(notes, {"kind": "rollback", "from": current, "to": target, "reason": reason})
    return 0


def cmd_run(repo: Path, notes: Path, *, full: bool, timeout_s: float, max_rollbacks: int,
            watchdog_s: float, sim_args: list[str]) -> int:
    rule("run")
    say(f"repo {repo}, HEAD {head(repo)}")
    tags = good_tags(repo)
    if not tags:
        say("no known-good tag exists yet; gating HEAD as-is")
    rollbacks = 0
    while True:
        ok, why = run_gate(repo, full=full, timeout_s=timeout_s)
        if ok:
            say(f"gate passed: {why}")
            commit = head(repo)
            if not any(tag_of(repo, t) == commit for _n, t in good_tags(repo)) and not is_dirty(repo):
                tag = next_tag(repo)
                git("tag", "-a", tag, "-m", f"simloader: {why}", cwd=repo, check=True)
                say(f"tagged {commit} as {tag}")
                write_note(notes, {"kind": "blessed", "commit": commit, "tag": tag, "why": why})
            break
        say(f"gate FAILED: {why}")
        write_note(notes, {"kind": "gate_failed", "commit": head(repo), "why": why})
        if rollbacks >= max_rollbacks:
            say(f"giving up after {rollbacks} rollback(s); a human needs to look at this")
            return 3
        if cmd_rollback(repo, notes, reason=why) != 0:
            say("could not roll back; stopping")
            return 3
        rollbacks += 1

    rule("handing off to Sim")
    started = time.monotonic()
    returncode = launch_sim(repo, notes, sim_args)
    ran_for = time.monotonic() - started
    if returncode != 0 and ran_for < watchdog_s:
        why = f"Sim exited {returncode} after {ran_for:.0f}s, inside the {watchdog_s:.0f}s watchdog"
        say(f"bad boot: {why}")
        write_note(notes, {"kind": "watchdog", "commit": head(repo), "why": why})
        if rollbacks < max_rollbacks and cmd_rollback(repo, notes, reason=why) == 0:
            say("rolled back; run `simloader.py run` again to boot the previous image")
        return 4
    say(f"Sim exited {returncode} after {ran_for:.0f}s")
    return returncode


def launch_sim(repo: Path, notes: Path, sim_args: list[str]) -> int:
    """Run Sim in the foreground until it exits. Its own function so a
    test can stand in for it without also standing in for git."""
    env = dict(os.environ, SIMORGH_LOADER_NOTES=str(notes))
    return subprocess.run([sys.executable, "-m", "simorgh", "run", *sim_args], cwd=repo, env=env).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boot Simorgh from a known-good tag, and keep it that way.")
    parser.add_argument("command", choices=("run", "bless", "status", "rollback"))
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--notes", default=str(DEFAULT_NOTES), help="where decisions are written for Sim to read")
    parser.add_argument("--full", action="store_true", help="gate with the trial suite too, not just unit tests")
    parser.add_argument("--timeout", type=float, default=1800.0, help="seconds the whole gate may take")
    parser.add_argument("--max-rollbacks", type=int, default=3)
    parser.add_argument("--watchdog", type=float, default=60.0, help="a non-zero exit inside this is a bad boot")
    parser.add_argument("--reason", default="requested by operator")
    parser.add_argument("sim_args", nargs="*", help="passed through to `python -m simorgh run`")
    args = parser.parse_args(argv)
    repo, notes = Path(args.repo).resolve(), Path(args.notes).expanduser()

    if args.command == "status":
        return cmd_status(repo, notes)
    if args.command == "bless":
        return cmd_bless(repo, notes, full=args.full, timeout_s=args.timeout)
    if args.command == "rollback":
        return cmd_rollback(repo, notes, reason=args.reason)
    return cmd_run(
        repo, notes, full=args.full, timeout_s=args.timeout, max_rollbacks=args.max_rollbacks,
        watchdog_s=args.watchdog, sim_args=args.sim_args,
    )


if __name__ == "__main__":
    sys.exit(main())
