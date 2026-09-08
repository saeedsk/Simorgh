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
import queue
import re
import select
import shutil
import subprocess
import sys
import termios
import threading
import tty
import time
from pathlib import Path

TAG_PREFIX = "sim-good-"
# Only for the "this will take a while" line; nothing depends on it.
EXPECTED_UNIT_S = 240
_TAG = re.compile(rf"^{re.escape(TAG_PREFIX)}(\d+)$")
DEFAULT_NOTES = Path("~/.simorgh/loader").expanduser()


# ---------------------------------------------------------------- output
def say(line: str) -> None:
    _live_clear()
    print(f"[simloader] {line}", flush=True)


def rule(title: str) -> None:
    _live_clear()
    print(f"\n[simloader] ── {title} " + "─" * max(0, 60 - len(title)), flush=True)


# A gate is minutes of silence otherwise. The creator, 2026-09-07:
# "simloader is now not showing any activity for past 60 seconds, this
# is not good, user doesn't understand what is happening". So one line,
# redrawn in place, that always moves: a bar, a percentage, a count, and
# the elapsed seconds. Redirected output (a log, a pipe) gets periodic
# ordinary lines instead -- escape codes in a file help nobody.
_LIVE = sys.stdout.isatty() and os.environ.get("SIMORGH_LOADER_PLAIN") != "1"
_live_drawn = False
_HEARTBEAT_S = 15.0


def _live_clear() -> None:
    global _live_drawn
    if _LIVE and _live_drawn:
        sys.stdout.write("\r\x1b[2K")
        sys.stdout.flush()
        _live_drawn = False


def _live(text: str) -> None:
    global _live_drawn
    if not _LIVE:
        return
    width = shutil.get_terminal_size((80, 24)).columns
    sys.stdout.write("\r\x1b[2K" + text[: max(0, width - 1)])
    sys.stdout.flush()
    _live_drawn = True


def bar(fraction: float, width: int = 24) -> str:
    fraction = min(1.0, max(0.0, fraction))
    filled = int(round(fraction * width))
    return "█" * filled + "░" * (width - filled)


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


SKIP_KEYS = ("s", "S")
SKIP_SENTINEL = "skipped by the operator"


class GateSkipped(Exception):
    """A human pressed the skip key: boot Sim without finishing the gate."""


class SkipWatch:
    """Watches the terminal for the skip key while the gate runs.

    The creator, 2026-09-07: "in simloader allow user to bypass the test
    by pressing key and let sim to load". The gate is minutes long, and
    someone who knows this checkout is fine should not have to wait for
    it or edit a config to say so. A skip is deliberate, announced, and
    recorded -- and it never produces a known-good tag: only a gate that
    actually ran can bless a commit."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled and sys.stdin is not None and sys.stdin.isatty()
        self._saved = None

    def __enter__(self) -> "SkipWatch":
        if self.enabled:
            try:
                self._saved = termios.tcgetattr(sys.stdin.fileno())
                tty.setcbreak(sys.stdin.fileno())
            except Exception:  # noqa: BLE001 -- no controlling terminal: just never skip
                self.enabled = False
        return self

    def __exit__(self, *exc) -> None:
        if self._saved is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved)
            except Exception:  # noqa: BLE001
                pass
            self._saved = None

    def pressed(self) -> bool:
        if not self.enabled:
            return False
        try:
            while select.select([sys.stdin], [], [], 0)[0]:
                key = sys.stdin.read(1)
                if not key:
                    return False
                if key in SKIP_KEYS:
                    return True
        except Exception:  # noqa: BLE001
            self.enabled = False
        return False


class Progress:
    """Draws one moving line for a subprocess, and keeps its output.

    `feed(chunk)` is called with whatever the child just wrote; the
    subclass pulls whatever it can out of it (a pytest percentage, a
    trial's PASS line) and returns the text to show. `tick()` redraws on
    a timer so the line moves even while the child is silent."""

    label = "working"

    def __init__(self, started: float) -> None:
        self.started = started
        self.detail = ""
        self.fraction = 0.0
        self._last_plain = 0.0

    def feed(self, chunk: str) -> None:  # pragma: no cover -- overridden
        ...

    def render(self) -> None:
        elapsed = time.monotonic() - self.started
        line = f"[simloader] {bar(self.fraction)} {self.fraction * 100:3.0f}%  {self.label}  {_mmss(elapsed)}"
        if self.detail:
            line += f"  {self.detail}"
        if _LIVE:
            _live(line)
        elif elapsed - self._last_plain >= _HEARTBEAT_S:
            self._last_plain = elapsed
            print(line, flush=True)


class PytestProgress(Progress):
    """pytest -q writes dots and a `[ 42%]` at each line's end."""

    label = "unit suite"
    _PCT = re.compile(r"\[\s*(\d{1,3})%\]")
    _DOTS = re.compile(r"[.FEsxX]")

    def __init__(self, started: float) -> None:
        super().__init__(started)
        self.tests = 0
        self.failed = 0

    def feed(self, chunk: str) -> None:
        for match in self._PCT.finditer(chunk):
            self.fraction = int(match.group(1)) / 100
        self.tests += len(self._DOTS.findall(self._PCT.sub("", chunk)))
        self.failed += chunk.count("F") + chunk.count("E")
        self.detail = f"{self.tests} tests" + (f", {self.failed} failing" if self.failed else "")


class TrialProgress(Progress):
    """The trial suite prints one PASS/FAIL line per trial, and a task's
    own narration in between -- the most recent step is the detail."""

    label = "trial suite"

    def __init__(self, started: float, total: int) -> None:
        super().__init__(started)
        self.total = max(1, total)
        self.done = 0
        self._buffer = ""

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            plain = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            if plain.startswith(("PASS", "FAIL")):
                self.done += 1
                self.fraction = self.done / self.total
                say(f"  {plain}")
            elif plain.startswith("→"):
                self.detail = f"trial {self.done + 1}/{self.total}: {plain[1:].strip()[:60]}"
            elif plain.startswith(("🔧", "🔍", "🎓", "💬", "🗂")):
                self.detail = f"trial {self.done + 1}/{self.total}: {plain[1:].strip()[:60]}"


def stream(argv: list[str], *, cwd: Path, timeout_s: float, progress: Progress,
           skip: "SkipWatch | None" = None) -> tuple[int, str]:
    """Run `argv`, drawing `progress` as it goes. Returns (code, output).

    Reads raw bytes rather than lines: pytest's dots arrive without a
    newline for a whole screen at a time, so a line-based read shows
    nothing for minutes -- which is exactly the silence being fixed."""
    child = subprocess.Popen(
        argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, bufsize=0,
    )
    # A reader thread, not a read in this loop: a silent child would
    # otherwise block the read for as long as it stays silent, so
    # neither the timeout nor the moving line would fire -- which is the
    # symptom being fixed.
    chunks: "queue.Queue[str | None]" = queue.Queue()

    def _read() -> None:
        try:
            while True:
                chunk = child.stdout.read(256)  # type: ignore[union-attr]
                if not chunk:
                    break
                chunks.put(chunk)
        finally:
            chunks.put(None)

    reader = threading.Thread(target=_read, name="simloader-reader", daemon=True)
    reader.start()
    out: list[str] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(argv, timeout_s)
            if skip is not None and skip.pressed():
                raise GateSkipped()
            try:
                chunk = chunks.get(timeout=0.5)
            except queue.Empty:
                progress.render()  # the line moves even while the child is quiet
                continue
            if chunk is None:
                break
            out.append(chunk)
            progress.feed(chunk)
            progress.render()
        code = child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        _live_clear()
    return code, "".join(out)


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
def run_gate(repo: Path, *, full: bool, timeout_s: float, notes: Path | None = None,
             allow_skip: bool = False) -> tuple[bool, str]:
    """Is this checkout fit to run? Returns (ok, why).

    With `allow_skip`, pressing `s` at the terminal abandons the gate and
    boots anyway -- a `run` convenience, never offered to `bless`."""
    started = time.monotonic()
    rule("gate: unit suite")
    say(f"running the whole test suite -- takes about {EXPECTED_UNIT_S // 60} minutes on this machine")
    with SkipWatch(allow_skip) as skip:
        if skip.enabled:
            say("press s to skip the gate and boot anyway (nothing will be tagged known-good)")
        try:
            code, unit_out = stream(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                cwd=repo, timeout_s=timeout_s, progress=PytestProgress(started), skip=skip,
            )
        except GateSkipped:
            say("skipped the unit suite at your request -- this checkout is UNVERIFIED")
            return True, f"{SKIP_SENTINEL} during the unit suite"
        except subprocess.TimeoutExpired:
            return False, f"unit suite exceeded {timeout_s:.0f}s"
        tests = subprocess.CompletedProcess(args=[], returncode=code, stdout=unit_out, stderr="")
        tail = (tests.stdout.strip().splitlines() or [""])[-1]
        say(f"unit suite: {tail}  ({time.monotonic() - started:.0f}s)")
        if notes is not None:
            notes.mkdir(parents=True, exist_ok=True)
            (notes / "last_unit.txt").write_text(tests.stdout)
        if tests.returncode not in (0, 5):
            # Name them. "9 failed" alone sent the human off to re-run the
            # whole suite to learn which nine (2026-09-07).
            failed = [line.strip() for line in tests.stdout.splitlines() if line.startswith("FAILED ")]
            for line in failed[:12]:
                say(line)
            if len(failed) > 12:
                say(f"... and {len(failed) - 12} more (full output: {notes / 'last_unit.txt' if notes else 'not kept'})")
            return False, f"unit suite failed: {tail}"
        if not full:
            return True, "unit suite green"

        rule("gate: scored trial suite")
        total = trial_count(repo)
        say(f"{total} real tasks against a throwaway copy of the repo, one at a time -- several minutes, and it calls the model")
        remaining = max(60.0, timeout_s - (time.monotonic() - started))
        trial_started = time.monotonic()
        try:
            code, trial_out = stream(
                [sys.executable, "-u", "tools/trial_suite.py", "--timeout", f"{min(900.0, remaining):.0f}"],
                cwd=repo, timeout_s=remaining, progress=TrialProgress(trial_started, total), skip=skip,
            )
        except GateSkipped:
            say("skipped the trial suite at your request -- the unit suite passed, the trials did not run")
            return True, f"{SKIP_SENTINEL} during the trial suite"
        except subprocess.TimeoutExpired:
            return False, f"trial suite exceeded {remaining:.0f}s"
    trials = subprocess.CompletedProcess(args=[], returncode=code, stdout=trial_out, stderr="")
    for line in trials.stdout.splitlines():
        if line.strip().startswith("- ") or "clean" in line:
            say(line.strip())
    if notes is not None:
        # The whole narration, so a refused bless can be diagnosed
        # without re-running the trial: the first real one refused on
        # three "blocked" trials and this summary alone could not say why.
        notes.mkdir(parents=True, exist_ok=True)
        (notes / "last_trials.txt").write_text(trials.stdout)
        say(f"full trial output: {notes / 'last_trials.txt'}")
    if trials.returncode != 0:
        return False, "trial suite had failures"
    return True, "unit suite and trial suite green"


def trial_count(repo: Path) -> int:
    """How many trials the suite will run, read from its source rather
    than imported -- the loader never imports the package it boots."""
    try:
        text = (repo / "tools" / "trial_suite.py").read_text()
    except OSError:
        return 6
    body = text.partition("TRIALS: tuple[Trial, ...] = (")[2].partition("\n)")[0]
    return body.count("Trial(") or 6


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
    ok, why = run_gate(repo, full=full, timeout_s=timeout_s, notes=notes)
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
        ok, why = run_gate(repo, full=full, timeout_s=timeout_s, notes=notes, allow_skip=True)
        if ok and SKIP_SENTINEL in why:
            say(f"gate {why}; booting unverified, and nothing is being tagged")
            write_note(notes, {"kind": "gate_skipped", "commit": head(repo), "why": why})
            break
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
    parser.add_argument("--timeout", type=float, default=5400.0, help="seconds the whole gate may take")
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
