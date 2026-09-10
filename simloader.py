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
import importlib.util
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


def pytest_parallel_args() -> list[str]:
    """`-n auto` when pytest-xdist is installed, else nothing.

    The unit gate ran the 3000-test suite serially: 250s on a quiet
    machine, 670s under load, and the creator watched it print nothing
    for a minute at a time. Split across 12 cores it takes 57s with the
    identical pass/fail result -- real processes, not threads, since the
    GIL makes threads useless for CPU-bound assertions. Optional on
    purpose: this file is stdlib-only and must gate a checkout on a
    machine that never installed the extra.
    """
    return ["-n", "auto"] if importlib.util.find_spec("xdist") else []


# Only for the "this will take a while" line; nothing depends on it.
EXPECTED_UNIT_S = 90 if pytest_parallel_args() else 720
_TAG = re.compile(rf"^{re.escape(TAG_PREFIX)}(\d+)$")
# Notes default to a directory *inside the repo being gated*, not the
# invoking process's real `$HOME`. This used to be
# `Path("~/.simorgh/loader").expanduser()` -- fine for the real checkout,
# but a bootloader run against an independent sandbox copy of the repo
# still has the operator's real `$HOME`, so every unqualified `bless`
# there wrote straight into that person's actual
# `~/.simorgh/loader/decisions.jsonl`, corrupting the real audit trail
# with sandbox-only decisions (observer, 2026-09-08 -- reproduced live:
# a sandbox run with no `--notes` resolved to `/Users/<real-user>/.simorgh/loader`).
# `--repo` already resolves correctly per-checkout (it defaults to this
# file's own directory), so anchoring notes there instead makes the
# escape structurally impossible: a sandbox's `simloader.py` can only
# ever write under that sandbox's own repo tree. Untracked, so rollback's
# `git checkout <tag>` never touches it (see `is_dirty`'s docstring).
NOTES_DIRNAME = ".simorgh_loader"


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
    # Only a run of progress characters at the start of a line is a
    # result row. Matching bare `[.FEsxX]` anywhere counted ordinary
    # prose: the pytest-asyncio deprecation warning alone reported
    # "33 tests, 1 failing" before a single test had run, and a real run
    # claimed 2996 tests / 23 failing against an actual 2865 / 2
    # (observer, 2026-09-08). A progress line that invents numbers is
    # worse than no progress line.
    _ROW = re.compile(r"^[.FEsxX]{2,}", re.M)

    def __init__(self, started: float) -> None:
        super().__init__(started)
        self.tests = 0
        self.failed = 0
        self._buffer = ""

    def __init_subclass__(cls) -> None:  # pragma: no cover -- documentation
        ...

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            for match in self._PCT.finditer(line):
                self.fraction = int(match.group(1)) / 100
            row = self._ROW.match(line)
            if not row:
                continue
            marks = row.group(0)
            self.tests += len(marks)
            self.failed += marks.count("F") + marks.count("E")
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
    """Every known-good tag that resolves to a real commit, oldest first.

    A `sim-good-*` tag that does not name a commit -- deleted underneath
    us, pointing at a tree, or left dangling by a repair -- used to be
    counted anyway: `status` announced it as "latest known-good" with a
    blank commit beside it, and `rollback` picked it as a target and died
    with an uncaught `RuntimeError: git checkout -q sim-good-0001: fatal:
    Cannot switch branch to a non-commit`, straight out of `cmd_run`,
    with no note written and no guidance printed (observer, 2026-09-10).
    A tag the loader cannot check out is not a known-good image."""
    out = git("tag", "--list", f"{TAG_PREFIX}*", cwd=repo).stdout.split()
    found = []
    for tag in out:
        match = _TAG.match(tag)
        if match and tag_of(repo, tag):
            found.append((int(match.group(1)), tag))
    return sorted(found)


def broken_tags(repo: Path) -> list[str]:
    """`sim-good-*` tags that name nothing checkout-able -- for `status`,
    so a tag being ignored is visible rather than merely absent."""
    out = git("tag", "--list", f"{TAG_PREFIX}*", cwd=repo).stdout.split()
    return sorted(tag for tag in out if _TAG.match(tag) and not tag_of(repo, tag))


# Untracked files that can change what the test run does. `papers/x.pdf`
# and a scratch shell script cannot; a `.py`, a `conftest.py` or a pytest
# config file is read by the very suite that decides whether a commit is
# fit to be tagged.
_UNTRACKED_CODE = re.compile(r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg)$|\.(py|pth)$")


def untracked_code(repo: Path) -> list[str]:
    """Untracked files the gate would import but the commit does not have.

    Demonstrated live (observer, 2026-09-10): a commit whose test imports
    `helper.py`, with `helper.py` left untracked. `bless` ran the suite
    against the working tree -- "1 passed" -- and tagged the commit
    `sim-good-0001`. A clean checkout of that exact tag then fails to
    collect at all. The tag is a statement that the loader verified that
    commit, and the loader had verified a different tree."""
    return [path for path in untracked(repo)
            if _UNTRACKED_CODE.search(path) and "__pycache__" not in path
            and not path.startswith(NOTES_DIRNAME + "/")]


def tag_of(repo: Path, tag: str) -> str:
    """The commit a tag names, or "" if the tag has gone.

    Was `check=True`, so a tag deleted between listing and resolving
    raised `RuntimeError: Needed a single revision` out of the rollback
    path (observer, 2026-09-08)."""
    done = git("rev-parse", "--short", f"{tag}^{{commit}}", cwd=repo)
    return done.stdout.strip() if done.returncode == 0 else ""


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
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *pytest_parallel_args(), "tests"],
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
        unit_ok, unit_why, ran = unit_verdict(tests.returncode, tests.stdout, baseline=read_baseline(notes))
        if not unit_ok:
            # Name them. "9 failed" alone sent the human off to re-run
            # the whole suite to learn which nine (2026-09-07). `ERROR `
            # is what a collection failure looks like -- exactly the
            # import-broken case, which was the one printing no file
            # name at all (observer, 2026-09-08).
            failed = [line.strip() for line in tests.stdout.splitlines()
                      if line.startswith(("FAILED ", "ERROR "))]
            for line in failed[:12]:
                say(line)
            if len(failed) > 12:
                say(f"... and {len(failed) - 12} more (full output: {notes / 'last_unit.txt' if notes else 'not kept'})")
            return False, f"unit suite failed: {unit_why} ({tail})"
        write_baseline(notes, ran)
        if not full:
            return True, f"unit suite green ({unit_why})"

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


_COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")


def unit_summary(text: str) -> dict[str, int]:
    """The counts pytest itself printed, from its own summary line.

    The exit code is a single byte under the control of the code being
    judged; the summary line is what pytest says happened. Reading both
    is the only way to notice they disagree."""
    for line in reversed(text.strip().splitlines()):
        found = _COUNT.findall(line)
        if not found:
            continue
        counts: dict[str, int] = {}
        for number, word in found:
            counts["error" if word.startswith("error") else word] = int(number)
        return counts
    return {}


def unit_verdict(code: int, text: str, *, baseline: int | None) -> tuple[bool, str, int]:
    """Did the unit suite actually pass? Returns (ok, why, tests_that_ran).

    Three separate attacks on the gate were demonstrated live (observer,
    2026-09-10), each of which ended with `[simloader] blessed ... (unit
    suite green)`:

    - deleting every test file, or a `conftest.py` with
      `collect_ignore_glob = ["*"]`, or a `pytest.ini` whose `addopts`
      select nothing: pytest exits **5**, "no tests ran", which the gate
      accepted as green. Exit 5 was allowed so an empty checkout would
      not wedge the loader; the cost was that the cheapest way to pass
      the gate became deleting the tests.
    - a `conftest.py` with `pytest_sessionfinish` setting
      `session.exitstatus = 0`: the loader printed `unit suite: 1
      failed, 1 passed` and blessed the commit on the next line. The
      evidence was already on screen and nothing read it.
    - `pytest_collection_modifyitems` adding a blanket `skip` marker:
      "2 skipped", exit 0, blessed.

    So: the exit code must be 0, the summary must not report a failure
    or an error, and tests must actually have RUN -- more than zero, and
    not far below what the last green gate on this machine saw. The
    baseline is stored next to the notes and moves with each green gate,
    so deleting a tenth of the suite still passes and gutting it does
    not."""
    counts = unit_summary(text)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    ran = counts.get("passed", 0) + failed + counts.get("xfailed", 0) + counts.get("xpassed", 0)
    if code not in (0, 5):
        return False, f"pytest exited {code}", ran
    if failed:
        # Exit 0 and "N failed" on the same run: a conftest hook can
        # write the exit code, so believe the transcript, not the byte.
        return False, f"pytest exited {code} but reported {failed} failed/errored", ran
    if ran <= 0:
        return False, "no tests actually ran -- the suite was empty, ignored, or entirely skipped", ran
    if baseline and ran < baseline * 0.9:
        return False, f"only {ran} tests ran; the last green gate ran {baseline} -- the suite shrank by more than a tenth", ran
    return True, f"{ran} tests ran, none failed", ran


def read_baseline(notes: Path | None) -> int | None:
    if notes is None:
        return None
    try:
        return int(json.loads((notes / "unit_baseline.json").read_text())["tests"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_baseline(notes: Path | None, tests: int) -> None:
    if notes is None or tests <= 0:
        return
    try:
        notes.mkdir(parents=True, exist_ok=True)
        (notes / "unit_baseline.json").write_text(json.dumps({"tests": tests, "ts": time.time()}))
    except OSError as exc:  # noqa: BLE001 -- never lose a boot to bookkeeping
        say(f"could not record the unit baseline ({exc!r}); continuing")


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
    JSONL, one decision per line.

    Never fatal. An unwritable notes directory used to raise
    `PermissionError` and kill a boot whose gate had already PASSED
    (observer, 2026-09-08) -- losing the system to a bookkeeping failure
    is exactly backwards."""
    try:
        _write_note(notes, note)
    except OSError as exc:
        say(f"could not write the note ({exc!r}); continuing")


def _write_note(notes: Path, note: dict) -> None:
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
    stray_code = untracked_code(repo)
    if stray_code:
        say(f"untracked CODE -- the gate would run it, no tag can be earned while it is here: {', '.join(stray_code[:5])}")
    for tag in broken_tags(repo):
        say(f"ignoring {tag}: it does not name a commit")
    baseline = read_baseline(notes)
    if baseline:
        say(f"last green gate ran {baseline} tests; a run below {int(baseline * 0.9)} is refused")
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
    stray_code = untracked_code(repo)
    if stray_code:
        say("refusing: the gate would run against code this commit does not contain --")
        for path in stray_code[:8]:
            say(f"  {path}  (untracked)")
        say("commit them or move them aside; a tag has to mean the commit was verified")
        return 2
    commit = head(repo)
    existing = next((tag for _n, tag in good_tags(repo) if tag_of(repo, tag) == commit), None)
    if existing is not None and not full:
        say(f"{commit} is already {existing}")
        return 0
    if existing is not None:
        # `--full` on an already-tagged commit used to return 0 here
        # without running anything, which reads on screen exactly like
        # the full gate passing. It had not run: the tag came from the
        # unit suite alone, and the trial suite -- the gate that has
        # actually caught every real blocker in this project -- was
        # skipped in silence (2026-09-08).
        say(f"{commit} is already {existing}, but that tag is from the unit suite alone")
        say("running the trial suite now; the tag stays as it is either way")
    ok, why = run_gate(repo, full=full, timeout_s=timeout_s, notes=notes)
    if existing is not None:
        if ok:
            say(f"trial suite green for {existing}  ({why})")
            write_note(notes, {"kind": "full_gate_passed", "commit": commit, "tag": existing, "why": why})
            return 0
        say(f"the full gate FAILED for {existing}: {why}")
        say(f"{existing} still stands -- it was earned by the unit suite, which still passes")
        write_note(notes, {"kind": "full_gate_failed", "commit": commit, "tag": existing, "why": why})
        return 1
    if not ok:
        say(f"NOT blessed: {why}")
        write_note(notes, {"kind": "bless_refused", "commit": commit, "why": why})
        return 1
    tag = next_tag(repo)
    git("tag", "-a", tag, "-m", f"simloader: {why}", cwd=repo, check=True)
    say(f"blessed {commit} as {tag}  ({why})")
    write_note(notes, {"kind": "blessed", "commit": commit, "tag": tag, "why": why})
    return 0


def previous_tag(repo: Path, tags: list[tuple[int, str]], current: str) -> str | None:
    """The known-good tag strictly BELOW where we are now.

    The old rule was "any tag whose commit is not HEAD, take the last" --
    which is the NEWEST such tag. From the oldest tag it therefore rolled
    *forward*, straight back into the image the gate had just rejected,
    and `cmd_run` ping-ponged between two tags until it burned
    `--max-rollbacks` (found by an observer, 2026-09-08). This is the one
    mechanism whose whole job is stepping back to safety; it must never
    step forward.
    """
    if not tags:
        return None
    here = next((n for n, tag in tags if tag_of(repo, tag) == current), None)
    if here is None:
        # Not sitting on a tag: fall back to the newest tag that is an
        # ancestor of HEAD, else the newest tag at all.
        ancestors = [(n, tag) for n, tag in tags if is_ancestor(repo, tag, current)]
        return (ancestors or tags)[-1][1]
    below = [tag for n, tag in tags if n < here]
    return below[-1] if below else None


def is_ancestor(repo: Path, tag: str, commit: str) -> bool:
    return git("merge-base", "--is-ancestor", f"{tag}^{{commit}}", commit, cwd=repo).returncode == 0


def cmd_rollback(repo: Path, notes: Path, *, reason: str) -> int:
    rule("rollback")
    tags = good_tags(repo)
    if is_dirty(repo):
        say("refusing: the working tree has uncommitted changes; a rollback would discard them")
        return 2
    current = head(repo)
    target = previous_tag(repo, tags, current)
    if target is None:
        say("nothing older to roll back to")
        return 1
    done = git("checkout", "-q", target, cwd=repo)
    if done.returncode != 0:
        # A rollback that cannot happen is a thing to report, not a
        # traceback out of the boot path.
        say(f"could not check out {target}: {(done.stderr or done.stdout).strip()}")
        write_note(notes, {"kind": "rollback_failed", "from": current, "to": target, "reason": reason})
        return 2
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
            stray_code = untracked_code(repo)
            if stray_code:
                # Booting is fine -- this tree just passed. Tagging is
                # not: the tag would name a commit that lacks these.
                say(f"not tagging: the gate ran with untracked code ({', '.join(stray_code[:3])}"
                    f"{' ...' if len(stray_code) > 3 else ''}) that {commit} does not contain")
                write_note(notes, {"kind": "tag_withheld", "commit": commit, "untracked": stray_code[:20]})
            elif not any(tag_of(repo, t) == commit for _n, t in good_tags(repo)) and not is_dirty(repo):
                tag = next_tag(repo)
                git("tag", "-a", tag, "-m", f"simloader: {why}", cwd=repo, check=True)
                say(f"tagged {commit} as {tag}")
                write_note(notes, {"kind": "blessed", "commit": commit, "tag": tag, "why": why})
            break
        say(f"gate FAILED: {why}")
        write_note(notes, {"kind": "gate_failed", "commit": head(repo), "why": why})
        if rollbacks >= max_rollbacks:
            rule("giving up")
            say(f"the gate failed after {rollbacks} rollback(s), and I am not going to keep trying.")
            say(f"HEAD is {head(repo)}, which did NOT pass. Nothing here is blessed.")
            tags = good_tags(repo)
            if tags:
                say(f"last known-good tag: {tags[-1][1]} ({tag_of(repo, tags[-1][1])})")
                say(f"  git checkout {tags[-1][1]}     # go back to it by hand")
            say(f"  {notes / 'last_unit.txt'}   # what the suite actually said")
            say("  SIMORGH_NO_LOADER=1 ./sim.sh    # boot without the gate, to debug")
            write_note(notes, {"kind": "gave_up", "commit": head(repo), "rollbacks": rollbacks, "why": why})
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
    parser.add_argument("--notes", default=None,
                         help=f"where decisions are written for Sim to read "
                              f"(default: <repo>/{NOTES_DIRNAME})")
    parser.add_argument("--full", action="store_true", help="gate with the trial suite too, not just unit tests")
    parser.add_argument("--timeout", type=float, default=5400.0, help="seconds the whole gate may take")
    parser.add_argument("--max-rollbacks", type=int, default=3)
    parser.add_argument("--watchdog", type=float, default=60.0, help="a non-zero exit inside this is a bad boot")
    parser.add_argument("--reason", default="requested by operator")
    parser.add_argument("sim_args", nargs="*", help="passed through to `python -m simorgh run`")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    notes = Path(args.notes).expanduser() if args.notes else repo / NOTES_DIRNAME

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
