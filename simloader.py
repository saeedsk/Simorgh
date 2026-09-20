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
# On a terminal the loader draws like the rest of Sim: a card, `⏺` section
# titles, one icon per outcome, a moving bar (the creator, 2026-09-14:
# "make the sim loader more modern and visually appealing"). Anywhere else
# -- a log, a pipe, NO_COLOR -- it prints the plain `[simloader]` lines it
# always has, so nothing that reads its output has to change.
_KINDS = {
    "info": ("⎿", "2"), "note": ("·", "2"), "ok": ("✓", "32"), "fail": ("✗", "31"),
    "warn": ("↺", "33"), "step": ("▸", "36"),
}
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _fancy() -> bool:
    return _LIVE and "NO_COLOR" not in os.environ


def paint(code: str, text: str, *, fancy: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if fancy else text


def format_say(line: str, kind: str = "info", *, fancy: bool) -> str:
    if not fancy:
        return f"[simloader] {line}"
    icon, code = _KINDS.get(kind, _KINDS["info"])
    body = line if kind not in ("info", "note") else paint("2", line, fancy=True)
    return f"  {paint(code, icon, fancy=True)} {body}"


def format_rule(title: str, *, fancy: bool, width: int = 64) -> str:
    if not fancy:
        return f"\n[simloader] ── {title} " + "─" * max(0, 60 - len(title))
    label = title[:1].upper() + title[1:]
    tail = "─" * max(2, width - len(label) - 4)
    return f"\n{paint('1;36', '⏺', fancy=True)} {paint('1', label, fancy=True)} {paint('2', tail, fancy=True)}"


def say(line: str, kind: str = "info") -> None:
    _live_clear()
    print(format_say(line, kind, fancy=_fancy()), flush=True)


def rule(title: str) -> None:
    _live_clear()
    print(format_rule(title, fancy=_fancy()), flush=True)


def format_card(rows: list[tuple[str, str]], *, fancy: bool, title: str = "Simorgh loader") -> str:
    """The run's opening card: what is being booted, from where."""
    if not fancy:
        return "\n".join(f"[simloader] {key} {value}" for key, value in rows)
    body = max([len(title) + 2] + [6 + len(value) for _key, value in rows])
    top = "╭─ " + paint("1;35", title, fancy=True) + " " + "─" * (body - len(title) - 1) + "╮"
    lines = [top]
    for key, value in rows:
        lines.append("│ " + paint("2", key.ljust(6), fancy=True) + value.ljust(body - 6) + " │")
    lines.append("╰" + "─" * (body + 2) + "╯")
    return "\n".join(lines)


def card(rows: list[tuple[str, str]]) -> None:
    _live_clear()
    print(("\n" if _fancy() else "") + format_card(rows, fancy=_fancy()), flush=True)


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


def fancy_bar(fraction: float, width: int = 28) -> str:
    fraction = min(1.0, max(0.0, fraction))
    filled = int(fraction * width)
    head = "╸" if filled < width else ""
    rest = width - filled - len(head)
    return paint("32", "━" * filled + head, fancy=True) + paint("2", "━" * rest, fancy=True)


def format_progress(*, label: str, fraction: float, elapsed: float, detail: str = "",
                    expected_s: float | None = None, fancy: bool) -> str:
    if not fancy:
        line = f"[simloader] {bar(fraction)} {fraction * 100:3.0f}%  {label}  {_mmss(elapsed)}"
        return line + (f"  {detail}" if detail else "")
    spin = paint("36", _SPINNER[int(elapsed * 10) % len(_SPINNER)], fancy=True)
    parts = [f"{spin} {paint('1', label, fancy=True)}", fancy_bar(fraction), paint("1", f"{fraction * 100:3.0f}%", fancy=True)]
    if detail:
        parts.append(detail)
    timing = _mmss(elapsed)
    if expected_s and expected_s > elapsed:
        timing += f" · ~{_mmss(expected_s - elapsed)} left"
    parts.append(paint("2", timing, fancy=True))
    return "  " + "  ".join(parts)


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

    def __init__(self, started: float, expected_s: float | None = None) -> None:
        self.started = started
        self.expected_s = expected_s
        self.detail = ""
        self.fraction = 0.0
        self._last_plain = 0.0

    def feed(self, chunk: str) -> None:  # pragma: no cover -- overridden
        ...

    def render(self) -> None:
        elapsed = time.monotonic() - self.started
        line = format_progress(label=self.label, fraction=self.fraction, elapsed=elapsed, detail=self.detail,
                               expected_s=self.expected_s, fancy=_fancy())
        if _LIVE:
            _live(line)
        elif elapsed - self._last_plain >= _HEARTBEAT_S:
            self._last_plain = elapsed
            print(line, flush=True)


class PytestProgress(Progress):
    """pytest -q writes dots and a `[ 42%]` at each line's end."""

    label = "tests"
    _PCT = re.compile(r"\[\s*(\d{1,3})%\]")
    # Only a run of progress characters at the start of a line is a
    # result row. Matching bare `[.FEsxX]` anywhere counted ordinary
    # prose: the pytest-asyncio deprecation warning alone reported
    # "33 tests, 1 failing" before a single test had run, and a real run
    # claimed 2996 tests / 23 failing against an actual 2865 / 2
    # (observer, 2026-09-08). A progress line that invents numbers is
    # worse than no progress line.
    _ROW = re.compile(r"^[.FEsxX]{2,}", re.M)

    def __init__(self, started: float, expected_s: float | None = None) -> None:
        super().__init__(started, expected_s)
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
                say(plain, "ok" if plain.startswith("PASS") else "fail")
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
# The gate's tests: what Sim needs to boot, think, act safely and change
# its own code. The feature suites (cameras, the TV, home automation,
# energy, mail, voice, benchmarks, the v1 code) are not here, and neither
# is any test marked `live` -- a real network service, Docker or a
# browser. A boot must not fail, or take eight minutes, because the house
# is offline or one integration changed (the creator, 2026-09-14: "limit
# the testing to most fundamental tests"). `--all-tests` runs everything.
CORE_TESTS = (
    "tests/simorgh/contracts", "tests/simorgh/bus", "tests/simorgh/ledger", "tests/simorgh/kernel",
    "tests/simorgh/guardian", "tests/simorgh/cognition", "tests/simorgh/memory", "tests/simorgh/orchestration",
    "tests/simorgh/planning", "tests/simorgh/verification", "tests/simorgh/execution",
    "tests/simorgh/interface/test_parser.py", "tests/simorgh/interface/test_dispatch.py",
    "tests/simorgh/interface/test_command_table.py", "tests/simorgh/interface/test_service.py",
    "tests/simorgh/interface/test_tui.py",
    # The WHOLE directory since 2026-09-20, not the five it used to be.
    # Those five passed while twenty-seven others failed, and four
    # blesses went out over a Guardian race that reported a successful
    # action as denied and over an Initiative whose delivery paths had
    # both been dead since stage 6. The argument for five was eight
    # minutes; the directory is 41 seconds because it carries no `live`
    # test, so the argument no longer holds.
    "tests/simorgh/integration",
    "tests/simorgh/test_module_boundaries.py", "tests/simorgh/test_simloader.py",
)
CORE_IGNORE = tuple(f"tests/simorgh/domains/{domain}"
                    for domain in ("home", "media", "energy", "pim", "knowledge", "security"))


def gate_selection(repo: Path, *, all_tests: bool) -> list[str]:
    """pytest's arguments for what the gate runs. Paths this checkout does
    not have are dropped -- a rollback lands on older trees -- and with
    none left the gate falls back to every test rather than to none."""
    paths = [p for p in CORE_TESTS if (repo / p).exists()]
    if all_tests or not paths:
        return ["tests"]
    return ["-m", "not live", *paths, *(f"--ignore={p}" for p in CORE_IGNORE if (repo / p).exists())]


def run_gate(repo: Path, *, full: bool, timeout_s: float, notes: Path | None = None,
             allow_skip: bool = False, all_tests: bool = False) -> tuple[bool, str]:
    """Is this checkout fit to run? Returns (ok, why).

    With `allow_skip`, pressing `s` at the terminal abandons the gate and
    boots anyway -- a `run` convenience, never offered to `bless`."""
    started = time.monotonic()
    scope = "all" if all_tests else "core"
    rule("gate: unit suite" if all_tests else "gate: core tests")
    last = _baseline_record(notes, scope)
    took = f" -- {last['seconds']:.0f}s last time" if isinstance(last.get("seconds"), (int, float)) else ""
    say(("running every test" if all_tests else "running the core tests (--all-tests runs every one)") + took, "note")
    with SkipWatch(allow_skip) as skip:
        if skip.enabled:
            say("press s to skip the gate and boot anyway (nothing will be tagged known-good)", "note")
        try:
            code, unit_out = stream(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *pytest_parallel_args(),
                 *gate_selection(repo, all_tests=all_tests)],
                cwd=repo, timeout_s=timeout_s, progress=PytestProgress(started, last.get("seconds") if isinstance(last.get("seconds"), (int, float)) else None),
                skip=skip,
            )
        except GateSkipped:
            say("skipped the unit suite at your request -- this checkout is UNVERIFIED", "warn")
            return True, f"{SKIP_SENTINEL} during the unit suite"
        except subprocess.TimeoutExpired:
            return False, f"unit suite exceeded {timeout_s:.0f}s"
        tests = subprocess.CompletedProcess(args=[], returncode=code, stdout=unit_out, stderr="")
        tail = (tests.stdout.strip().splitlines() or [""])[-1]
        say(f"tests: {tail}  ({time.monotonic() - started:.0f}s)",
            "fail" if re.search(r"\\b\\d+ (failed|errors?)\\b", tail) else "ok")
        if notes is not None:
            notes.mkdir(parents=True, exist_ok=True)
            (notes / "last_unit.txt").write_text(tests.stdout)
        unit_ok, unit_why, ran = unit_verdict(tests.returncode, tests.stdout, baseline=read_baseline(notes, scope))
        if not unit_ok:
            # Name them. "9 failed" alone sent the human off to re-run
            # the whole suite to learn which nine (2026-09-07). `ERROR `
            # is what a collection failure looks like -- exactly the
            # import-broken case, which was the one printing no file
            # name at all (observer, 2026-09-08).
            failed = [line.strip() for line in tests.stdout.splitlines()
                      if line.startswith(("FAILED ", "ERROR "))]
            for line in failed[:12]:
                say(line, "fail")
            if len(failed) > 12:
                say(f"... and {len(failed) - 12} more (full output: {notes / 'last_unit.txt' if notes else 'not kept'})", "fail")
            return False, f"unit suite failed: {unit_why} ({tail})"
        write_baseline(notes, ran, scope, seconds=time.monotonic() - started)

        evals_ok, evals_why = run_evals(repo, notes)
        if not evals_ok:
            return False, evals_why

        house_ok, house_why = run_house(repo, notes)
        if not house_ok:
            return False, house_why
        evals_why = f"{evals_why}; {house_why}"
        if not full:
            return True, f"unit suite green ({unit_why}); {evals_why}"

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
            say("skipped the trial suite at your request -- the unit suite passed, the trials did not run", "warn")
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
        say(f"full trial output: {notes / 'last_trials.txt'}", "note")
    if trials.returncode != 0:
        return False, "trial suite had failures"
    return True, "unit suite and trial suite green"


def run_house(repo: Path, notes: Path | None) -> tuple[bool, str]:
    """A few minutes of Sim actually living, before a commit is blessed
    (stage 11 item 11).

    The unit suite certifies shape and the household evals certify that
    what the family said reaches the prompt. Neither can show that a
    tool Initiative proposes exists, that a child is refused the front
    door, or that a memory survives a restart -- those need a booted
    Sim, driven, for long enough to get it wrong. Four blesses on
    2026-09-20 passed over a Guardian race and a delivery path that had
    been dead since stage 6; this is the gate that would have caught
    both.

    Free: the floor provider, a fake house, a fake microphone. About
    three minutes, which is the reason it is five scenarios and not
    eleven.
    """
    rule("gate: the house")
    say("five scenarios against a booted Sim -- a misheard name, a camera at night, a child at the "
        "door, a memory across a restart, the terminal -- about three minutes, no model, no money")
    try:
        proc = subprocess.run([sys.executable, "-u", "-m", "simorgh.evals", "house", "--fast"],
                              cwd=repo, capture_output=True, text=True, timeout=900)
    except (subprocess.TimeoutExpired, OSError) as exc:
        say(f"the house did not run ({exc}); the unit suite still decides", "warn")
        return True, "the house did not run"
    summary = next((line for line in proc.stdout.splitlines() if line.startswith("house:")), "")
    for line in proc.stdout.splitlines():
        if line.strip().startswith(("failed", "skipped")):
            say(line.strip(), "fail" if line.strip().startswith("failed") else "note")
    if notes is not None:
        notes.mkdir(parents=True, exist_ok=True)
        (notes / "last_house.txt").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    if not summary:
        say("the house produced no report; the unit suite still decides", "warn")
        return True, "the house produced no report"
    say(summary)
    if proc.returncode != 0:
        return False, f"the house refused this commit: {summary}"
    return True, summary


def last_household(notes: Path | None) -> dict | None:
    """The most recent recorded `household` report, or None.

    Stdlib only, by hand: `simorgh.evals.runner.last` does exactly this,
    and importing it here would break the one rule this file has.
    """
    if notes is None:
        return None
    path = notes / "evals.jsonl"
    if not path.exists():
        return None
    found = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("suite") == "household":
            found = row
    return found


def run_evals(repo: Path, notes: Path | None) -> tuple[bool, str]:
    """The free eval suite, and whether it got worse (stage 4 item 9).

    The unit suite certifies shape: it passes on a Sim that has stopped
    remembering what the family told it, which is exactly the failure
    that kept reaching the creator. `household` measures that, in about
    eight seconds, with no model and no money, so every bless can afford
    it.

    A drop against the last recorded run refuses the bless. A failure
    with nothing to compare against only warns: the first run of a new
    suite establishes the baseline, and refusing every bless until
    somebody hand-edits a file is how a gate gets switched off.
    """
    rule("gate: household evals")
    # The loader never imports `simorgh` -- that is the whole point of it
    # (see the module docstring) -- so it reads the eval record itself
    # rather than through the package it is judging.
    before = last_household(notes)
    cmd = [sys.executable, "-u", "-m", "simorgh.evals", "run", "household", "--repeats", "1", "--json"]
    if notes is not None:
        cmd += ["--record", str(notes)]
    try:
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        say(f"the evals did not run ({exc}); the unit suite still decides", "warn")
        return True, "evals did not run"
    try:
        # The report is indented JSON, so the last LINE of it is "}".
        text = proc.stdout
        report = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, IndexError):
        say("the evals produced no report; the unit suite still decides", "warn")
        return True, "evals produced no report"
    passed, total = int(report.get("passed", 0)), int(report.get("total", 0))
    say(f"household: {passed}/{total} probes ({report.get('seconds')} s)")
    for failure in report.get("failures") or []:
        say(f"{failure.get('case')}: {failure.get('why')}", "fail")
    was = int((before or {}).get("passed", -1))
    if before is not None and passed < was:
        return False, f"household evals fell from {was} to {passed} of {total}"
    if passed < total and before is None:
        say("no earlier household run to compare against; recorded as the baseline", "warn")
    return True, f"household evals {passed}/{total}"


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


# One count per selection: the core gate runs about half the suite, so
# measured against a whole-suite count it would read as "the suite shrank
# by more than a tenth" and fail every time. The old unit_baseline.json
# counted the whole suite and is left alone.
BASELINE_FILES = {"core": "unit_baseline-core.json", "all": "unit_baseline-all.json"}


def _baseline_record(notes: Path | None, scope: str) -> dict:
    if notes is None:
        return {}
    try:
        data = json.loads((notes / BASELINE_FILES[scope]).read_text())
    except (OSError, ValueError, KeyError):
        return {}
    return data if isinstance(data, dict) else {}


def read_baseline(notes: Path | None, scope: str = "core") -> int | None:
    try:
        return int(_baseline_record(notes, scope)["tests"])
    except (KeyError, ValueError, TypeError):
        return None


def write_baseline(notes: Path | None, tests: int, scope: str = "core", *, seconds: float | None = None) -> None:
    if notes is None or tests <= 0:
        return
    try:
        notes.mkdir(parents=True, exist_ok=True)
        (notes / BASELINE_FILES[scope]).write_text(json.dumps({"tests": tests, "seconds": seconds, "ts": time.time()}))
    except OSError as exc:  # noqa: BLE001 -- never lose a boot to bookkeeping
        say(f"could not record the unit baseline ({exc!r}); continuing", "warn")


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
        say(f"could not write the note ({exc!r}); continuing", "warn")


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
        say("refusing: the working tree has uncommitted changes -- commit or stash them first", "fail")
        return 2
    stray_code = untracked_code(repo)
    if stray_code:
        say("refusing: the gate would run against code this commit does not contain --", "fail")
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
            say(f"trial suite green for {existing}  ({why})", "ok")
            write_note(notes, {"kind": "full_gate_passed", "commit": commit, "tag": existing, "why": why})
            return 0
        say(f"the full gate FAILED for {existing}: {why}", "fail")
        say(f"{existing} still stands -- it was earned by the unit suite, which still passes")
        write_note(notes, {"kind": "full_gate_failed", "commit": commit, "tag": existing, "why": why})
        return 1
    if not ok:
        say(f"NOT blessed: {why}", "fail")
        write_note(notes, {"kind": "bless_refused", "commit": commit, "why": why})
        return 1
    tag = next_tag(repo)
    git("tag", "-a", tag, "-m", f"simloader: {why}", cwd=repo, check=True)
    say(f"blessed {commit} as {tag}  ({why})", "ok")
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
        say("refusing: the working tree has uncommitted changes; a rollback would discard them", "fail")
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
        say(f"could not check out {target}: {(done.stderr or done.stdout).strip()}", "fail")
        write_note(notes, {"kind": "rollback_failed", "from": current, "to": target, "reason": reason})
        return 2
    say(f"rolled back {current} -> {target} ({tag_of(repo, target)}): {reason}", "warn")
    write_note(notes, {"kind": "rollback", "from": current, "to": target, "reason": reason})
    return 0


# What Sim exits with when it wants to come back up on the current
# on-disk source rather than being done for good -- the `restart` REPL
# command, via `system.restart` and `kernel/cli.py::_cmd_run`. Keep this
# literal in sync with that file's own `RESTART_EXIT_CODE`; it cannot be
# imported from here (this loader is deliberately stdlib-only and never
# imports `simorgh` -- see the module docstring).
RESTART_EXIT_CODE = 75

# The last checkout the gate passed. The suite takes minutes, and a boot
# (or a `restart`) of source the gate has already judged learns nothing
# from judging it again (the creator, 2026-09-14: "do it once for any git
# head and skip it if git head has not changed and there is no
# uncommitted file").
GREEN_FILE = "last_green.json"


def source_fingerprint(repo: Path) -> str:
    """The commit the gate would be judging, or "" when the working tree
    is not exactly that commit -- a tracked change, or untracked code the
    suite would import -- so no earlier verdict can stand for it."""
    if is_dirty(repo) or untracked_code(repo):
        return ""
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def record_green(repo: Path, notes: Path, *, full: bool, all_tests: bool = False) -> None:
    commit = source_fingerprint(repo)
    if not commit:
        return
    try:
        notes.mkdir(parents=True, exist_ok=True)
        (notes / GREEN_FILE).write_text(json.dumps({"commit": commit, "full": full, "all_tests": all_tests, "ts": time.time()}))
    except OSError as exc:
        say(f"could not remember this green gate ({exc!r}); the next boot runs it again", "warn")


def already_verified(repo: Path, notes: Path, *, full: bool, all_tests: bool = False) -> str:
    """Why this checkout needs no gate, or "" when it does: the tree is
    clean, HEAD is the commit the gate last passed, and that pass covered
    at least what is asked for now (a unit-only pass does not stand in
    for `--full`)."""
    commit = source_fingerprint(repo)
    if not commit:
        return ""
    try:
        last = json.loads((notes / GREEN_FILE).read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(last, dict) or last.get("commit") != commit or (full and not last.get("full")) \
            or (all_tests and not last.get("all_tests")):
        return ""
    covered = "every test" if last.get("all_tests") else "the core tests"
    if last.get("full"):
        covered += " and the trial suite"
    return f"{commit[:7]} already passed {covered} and nothing has changed since"


def cmd_run(repo: Path, notes: Path, *, full: bool, timeout_s: float, max_rollbacks: int,
            watchdog_s: float, sim_args: list[str], force_gate: bool = False, all_tests: bool = False,
            reload_loader=None) -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip()
    where = str(repo).replace(str(Path.home()), "~", 1)
    if _fancy():
        card([("repo", where), ("HEAD", f"{head(repo)}  {branch if branch != 'HEAD' else '(detached)'}"),
              ("gate", "every test" if all_tests else "core tests" + (" + trial suite" if full else ""))])
    else:
        rule("run")
        say(f"repo {repo}, HEAD {head(repo)}")
    tags = good_tags(repo)
    if not tags:
        say("no known-good tag exists yet; gating HEAD as-is", "note")
    rollbacks = 0
    restarts = 0
    while True:
        while True:
            verified = "" if force_gate else already_verified(repo, notes, full=full, all_tests=all_tests)
            if verified:
                say(f"gate not needed: {verified} (--force-gate runs it anyway)", "ok")
                write_note(notes, {"kind": "gate_reused", "commit": head(repo), "why": verified})
                break
            ok, why = run_gate(repo, full=full, timeout_s=timeout_s, notes=notes, allow_skip=True, all_tests=all_tests)
            if ok and SKIP_SENTINEL in why:
                say(f"gate {why}; booting unverified, and nothing is being tagged", "warn")
                write_note(notes, {"kind": "gate_skipped", "commit": head(repo), "why": why})
                break
            if ok:
                say(f"gate passed: {why}", "ok")
                record_green(repo, notes, full=full, all_tests=all_tests)
                commit = head(repo)
                stray_code = untracked_code(repo)
                if stray_code:
                    # Booting is fine -- this tree just passed. Tagging is
                    # not: the tag would name a commit that lacks these.
                    say(f"not tagging: the gate ran with untracked code ({', '.join(stray_code[:3])}"
                        f"{' ...' if len(stray_code) > 3 else ''}) that {commit} does not contain", "warn")
                    write_note(notes, {"kind": "tag_withheld", "commit": commit, "untracked": stray_code[:20]})
                elif not any(tag_of(repo, t) == commit for _n, t in good_tags(repo)) and not is_dirty(repo):
                    tag = next_tag(repo)
                    git("tag", "-a", tag, "-m", f"simloader: {why}", cwd=repo, check=True)
                    say(f"tagged {commit} as {tag}", "ok")
                    write_note(notes, {"kind": "blessed", "commit": commit, "tag": tag, "why": why})
                break
            say(f"gate FAILED: {why}", "fail")
            write_note(notes, {"kind": "gate_failed", "commit": head(repo), "why": why})
            if rollbacks >= max_rollbacks:
                rule("giving up")
                say(f"the gate failed after {rollbacks} rollback(s), and I am not going to keep trying.", "fail")
                say(f"HEAD is {head(repo)}, which did NOT pass. Nothing here is blessed.", "fail")
                tags = good_tags(repo)
                if tags:
                    say(f"last known-good tag: {tags[-1][1]} ({tag_of(repo, tags[-1][1])})")
                    say(f"  git checkout {tags[-1][1]}     # go back to it by hand")
                say(f"  {notes / 'last_unit.txt'}   # what the suite actually said")
                say("  SIMORGH_NO_LOADER=1 ./sim.sh    # boot without the gate, to debug")
                write_note(notes, {"kind": "gave_up", "commit": head(repo), "rollbacks": rollbacks, "why": why})
                return 3
            if cmd_rollback(repo, notes, reason=why) != 0:
                say("could not roll back; stopping", "fail")
                return 3
            rollbacks += 1

        rule("starting Sim" if not restarts else f"starting Sim (restart #{restarts})")
        started = time.monotonic()
        returncode = launch_sim(repo, notes, sim_args)
        ran_for = time.monotonic() - started
        if returncode == RESTART_EXIT_CODE:
            # Sim asked to come back up on whatever is on disk *now* --
            # gate it again (a `restart` is exactly how new code from this
            # session reaches a running Sim) and hand off again, rather
            # than returning to sim.sh, which the creator would have to
            # notice and re-run by hand.
            restarts += 1
            say(f"Sim asked to restart (after {ran_for:.0f}s) -- re-gating the current checkout", "step")
            write_note(notes, {"kind": "restart", "commit": head(repo), "restarts": restarts})
            if reload_loader is not None:
                # This process holds the loader as it was when it started;
                # re-entering through sim.sh brings in the loader's own new
                # code and sim.sh's checks (live, 2026-09-14: a `restart`
                # would have gated with the old whole-suite loader). Only
                # returns if the exec failed -- then loop as before.
                reload_loader()
            continue
        if returncode != 0 and ran_for < watchdog_s:
            why = f"Sim exited {returncode} after {ran_for:.0f}s, inside the {watchdog_s:.0f}s watchdog"
            say(f"bad boot: {why}", "fail")
            write_note(notes, {"kind": "watchdog", "commit": head(repo), "why": why})
            if rollbacks < max_rollbacks and cmd_rollback(repo, notes, reason=why) == 0:
                say("rolled back; run `simloader.py run` again to boot the previous image", "warn")
            return 4
        say(f"Sim exited {returncode} after {ran_for:.0f}s", "note")
        return returncode


#: How long Sim gets to stop on its own after a Ctrl-C before the loader
#: kills it. Sim's own watchdog hard-exits at stop_grace_s + 10 (25 s by
#: default), so this is only the backstop behind it.
STOP_GRACE_S = 30.0


def launch_sim(repo: Path, notes: Path, sim_args: list[str], *, argv: list[str] | None = None,
               grace_s: float | None = None) -> int:
    """Run Sim in the foreground until it exits. Its own function so a
    test can stand in for it without also standing in for git.

    Not `subprocess.run`: on KeyboardInterrupt it waits 0.25 s and then
    SIGKILLs the child, so a terminal Ctrl-C -- which reaches Sim too,
    through the process group -- killed Sim a quarter of a second into
    its orderly shutdown: no final state, no ledger flush, stop_grace_s
    and Sim's own Stopper never mattered (2026-09-18 evaluation, B16).
    Now: a first Ctrl-C waits up to `grace_s` for Sim to exit on its
    own; a second one, or the grace running out, kills it. SIGTERM to
    the loader is forwarded to Sim."""
    env = dict(os.environ, SIMORGH_LOADER_NOTES=str(notes))
    cmd = argv if argv is not None else [sys.executable, "-m", "simorgh", "run", *sim_args]
    grace = STOP_GRACE_S if grace_s is None else grace_s
    proc = subprocess.Popen(cmd, cwd=repo, env=env)
    import signal

    try:
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: proc.send_signal(signal.SIGTERM))
    except ValueError:  # not the main thread (a test harness): no forwarding
        previous = None
    try:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            try:
                return proc.wait(timeout=grace)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                proc.kill()
                return proc.wait()
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boot Simorgh from a known-good tag, and keep it that way.")
    parser.add_argument("command", choices=("run", "bless", "status", "rollback"))
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--notes", default=None,
                         help=f"where decisions are written for Sim to read "
                              f"(default: <repo>/{NOTES_DIRNAME})")
    parser.add_argument("--full", action="store_true", help="gate with the trial suite too, not just unit tests")
    parser.add_argument("--all-tests", action="store_true",
                        help="gate with every test, not only the core ones")
    parser.add_argument("--force-gate", action="store_true",
                        help="run the gate even when this exact source already passed it")
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
    invoked = list(sys.argv[1:] if argv is None else argv)
    if "run" in invoked:
        invoked.remove("run")

    def reload_loader() -> None:
        script = repo / "sim.sh"
        if script.is_file():
            command = ["bash", str(script), *invoked]
            executable = shutil.which("bash") or "/bin/bash"
        else:
            command = [sys.executable, str(Path(__file__).resolve()), "run", *invoked]
            executable = sys.executable
        say("reloading the loader itself, so a change to it applies too", "step")
        try:
            os.execv(executable, command)
        except OSError as exc:
            say(f"could not reload the loader ({exc!r}); re-gating with this one", "warn")

    return cmd_run(
        repo, notes, full=args.full, timeout_s=args.timeout, max_rollbacks=args.max_rollbacks,
        watchdog_s=args.watchdog, sim_args=args.sim_args, force_gate=args.force_gate, all_tests=args.all_tests,
        reload_loader=reload_loader)


if __name__ == "__main__":
    sys.exit(main())
