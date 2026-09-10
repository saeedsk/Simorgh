"""Was this test already failing before the change?

`full_suite_ran` demands the whole suite, and until now it could not
say anything about the answer beyond "it passed" or "it did not". Once
the suite was red for ANY reason -- a flaky test, someone else's
half-finished commit, a missing optional dependency -- its objection
was unanswerable: it told the task to make the suite pass, the task
could not, and the revision budget burned down with a correct,
committed change sitting in the tree. Two observers watched exactly
that happen, on 2026-09-09 and 2026-09-10, and neither could fix it,
because every automatic escape they could see ("pass when the suite is
red", "trust the model's word") reintroduces the false pass the check
exists to prevent.

The escape that does not is attribution: not "is the suite green" but
"did THIS change break any of these". That is answerable, cheaply, and
without trusting anybody's word for it.

**Why this is not a full baseline suite run.** The obvious design is to
run the whole suite before the change and diff the results. It costs a
second ~90-second run for every task that touches Python, and a cache
of it is invalidated by every commit, by every uncommitted edit in the
tree, and by the clock (a date-dependent test). This module runs only
the node ids that actually failed -- typically a handful, and never
more than `contracts/pytestfailures._MAX_IDS` -- against the tree as it
was at the session's own `base_ref`. The cost is proportional to the
failures, not to the suite, there is nothing to cache and so nothing to
invalidate, and the question "was it red before I started" is answered
by measurement instead of by memory.

**Which way it errs.** Every unknown resolves to "the change is to
blame": no git, no `base_ref`, an unparseable marker, a capped list, a
node id that does not exist at the base revision, a baseline run that
times out or crashes. `None` from `attribute` means "no opinion", and
`fullsuiteran` treats no opinion exactly as it behaved before this
existed. The check can therefore still cost a revision it should not
have; it can never accept a change that broke the suite.

**Its one real blind spot**, stated plainly: the base revision is a
COMMIT, so a failure caused by an unrelated *uncommitted* edit that was
already in the tree when the session started is not visible at the base
and gets blamed on the change. That is the safe direction, and the
honest fix -- snapshotting the whole working tree at session start --
costs a copy per session and a lifetime to manage, which is not worth
paying for a case that only over-blames.

**Order-dependent failures.** A test that only fails as part of a full
run may pass when re-run alone at the base revision, and so be scored
as introduced. Again the safe direction, again documented rather than
guessed around: a check that occasionally over-blames costs a revision;
one that under-blames ships a broken suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from simorgh.contracts.pytestfailures import failing_nodeids

from ._files import REPO_ROOT

# A baseline run is a handful of tests, not a suite; if it has not
# finished in this long something is wrong and "no opinion" is the
# answer.
#
# The ceiling is not comfort, it is correctness. Orchestration waits
# `VERIFY_TIMEOUT_S == 300s` for the whole verdict and, on a timeout,
# ACCEPTS the task unverified (`session.py::_verify_then_finish`). A
# baseline run allowed to eat that budget would turn this check's own
# caution into the false pass it exists to prevent -- so it has to fit
# inside one verification round with every other check and the
# checklist's model calls still to come.
BASELINE_TIMEOUT_S = 90.0


def _repo_for(base_ref: str) -> Path | None:
    """A git repo that actually contains `base_ref`.

    Checked, not assumed. `_files.REPO_ROOT` is derived from this
    module's own location, which is right in production and wrong in a
    trial lab -- there `simorgh` is imported from the observer's
    checkout while the session's git history lives in the lab the
    process `chdir`ed into. Asking git whether the commit is there
    settles it without either module having to know which case it is
    in, and returning None when neither has it is the same "no opinion"
    every other unknown produces.
    """
    for root in (Path(os.getcwd()), REPO_ROOT):
        try:
            done = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{base_ref}^{{commit}}"],
                                  capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return root
    return None


def _export(root: Path, base_ref: str, dest: Path) -> bool:
    """The tracked tree at `base_ref`, unpacked into `dest`."""
    archive = dest.parent / "base.tar"
    try:
        with archive.open("wb") as handle:
            # Same exclusions `execution/tools.py::RunTestsTool` makes
            # for the same reason: `papers/` alone is 109 MB of PDFs no
            # test reads. Measured on this repo, the archive is 9 MB and
            # 0.13s with them out, against 118 MB with them in.
            done = subprocess.run(
                ["git", "-C", str(root), "archive", base_ref,
                 "--", ":(exclude)papers", ":(exclude)images", "."],
                stdout=handle, stderr=subprocess.PIPE, timeout=120)
        if done.returncode != 0:
            return False
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            # `git archive` writes only repo-relative regular entries, but
            # extraction is still filtered: an archive is untrusted input
            # and "it came from our own git" is not a reason to skip the
            # guard.
            tar.extractall(dest, filter="data")
        return True
    except (OSError, tarfile.TarError, subprocess.SubprocessError):
        return False
    finally:
        archive.unlink(missing_ok=True)


_PYTEST_USAGE_ERROR = 4


def _present_at_base(dest: Path, nodeids: tuple[str, ...]) -> tuple[str, ...] | None:
    """The subset of `nodeids` that the base tree can actually run.

    This exists because of how pytest treats an argument it cannot
    resolve: `pytest tests/a.py::test_old tests/new.py::test_new`, where
    the second was added by the change and does not exist at the base
    revision, is a USAGE error (exit 4) and runs NOTHING -- not the
    first one either. `_baseline`'s own docstring says such an id "is
    simply not in the returned set"; what actually happened was that
    every other failure came back unexamined and therefore blamed on the
    change too. Since this project's tasks are asked to land a
    regression test with every fix, "the change added a test" is the
    normal case, so the escape hatch this module exists to be was shut
    almost exactly when it was needed (observer, 2026-09-10).

    One extra `--collect-only` pass answers it for every id at once,
    which a retry loop around exit 4 could not: pytest names only the
    FIRST unresolvable argument before giving up.

    An id whose file will not even import at base collects nothing and
    so is dropped here -- it counts as introduced, the safe direction.
    """
    files = sorted({n.split("::", 1)[0] for n in nodeids})
    on_disk = [f for f in files if (dest / f).exists()]
    known = {n for n in nodeids if n.split("::", 1)[0] in set(on_disk) and "::" not in n}
    if not on_disk:
        return ()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "--collect-only", "--continue-on-collection-errors", *on_disk],
            capture_output=True, text=True, cwd=dest, timeout=BASELINE_TIMEOUT_S / 2,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    collected = {line.strip() for line in done.stdout.splitlines() if "::" in line}
    known.update(n for n in nodeids if n in collected)
    return tuple(n for n in nodeids if n in known)


def failing_at_base(base_ref: str, nodeids: tuple[str, ...]) -> frozenset[str] | None:
    """Which of `nodeids` ALSO fail at `base_ref`, or None for no opinion.

    A node id that does not exist at the base revision (a test the
    change itself added) is dropped by `_present_at_base` before the run
    and so is not in the returned set, which counts it as introduced --
    which is what it is. Dropping it before the run rather than letting
    pytest choke on it is the whole point: see that function.
    """
    if not base_ref or not nodeids:
        return None
    root = _repo_for(base_ref)
    if root is None:
        return None
    with tempfile.TemporaryDirectory(prefix="simorgh-baseline-") as workdir:
        dest = Path(workdir) / "repo"
        if not _export(root, base_ref, dest):
            return None
        started = time.monotonic()
        runnable = _present_at_base(dest, nodeids)
        if runnable is None:
            return None
        if not runnable:
            # Nothing that failed now even exists at the base revision:
            # every one of these failures is this change's own.
            return frozenset()
        # The collect pass comes out of the SAME budget, not on top of
        # it: `BASELINE_TIMEOUT_S` is sized against orchestration's
        # 300-second verification ceiling, past which a task is accepted
        # unverified -- so two runs that each get the whole ceiling
        # would turn this check's caution into the false pass it exists
        # to prevent.
        remaining = BASELINE_TIMEOUT_S - (time.monotonic() - started)
        if remaining <= 0:
            return None
        try:
            done = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 "--continue-on-collection-errors", *runnable],
                capture_output=True, text=True, cwd=dest, timeout=remaining,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode == _PYTEST_USAGE_ERROR:
            # An argument pytest still could not resolve: nothing ran,
            # so there is nothing to attribute and no opinion to give.
            # Never an empty set here -- that reads as "all of them are
            # new", which is a verdict this run did not earn.
            return None
        if done.returncode == 0:
            # Everything asked for ran and passed at the base revision:
            # every one of these failures is new.
            return frozenset()
        return frozenset(failing_nodeids(done.stdout)) & frozenset(nodeids)


def introduced(base_ref: str, nodeids: tuple[str, ...]) -> tuple[str, ...] | None:
    """The failures this change is answerable for, or None for no opinion.

    Empty tuple is a real answer, and the only one that lets a task off:
    every test that is red now was red before this session started.
    """
    already = failing_at_base(base_ref, nodeids)
    if already is None:
        return None
    return tuple(n for n in nodeids if n not in already)


def _stem(path: str) -> str:
    name = Path(path).name
    if name.endswith(".py"):
        name = name[:-3]
    return name[5:] if name.startswith("test_") else name


def owned_by(nodeids: tuple[str, ...], written: list[str]) -> tuple[str, ...]:
    """The still-failing tests this task cannot disown.

    "It was already red" is only an excuse when the redness has nothing
    to do with the job. A task asked to fix `tests/x/test_y.py` that
    leaves it just as red as it found it must not be waved through on
    the grounds that it was red first -- that is the second thing the
    scope of this work forbids, and it is the failure mode a naive
    "no new failures" rule walks straight into.

    Two ways a task owns a failure: it wrote the test file itself, or it
    wrote the module the test file is named after (`y.py` <-> `test_y.py`
    -- pytest's own convention and this repo's throughout). Both are
    cheap and neither can produce a false PASS; the worst a wrong guess
    here does is refuse an excuse.
    """
    written_paths = {p for p in written if p}
    written_stems = {_stem(p) for p in written_paths if p.lower().endswith(".py")}
    owned = []
    for nodeid in nodeids:
        path = nodeid.split("::", 1)[0]
        if path in written_paths or _stem(path) in written_stems:
            owned.append(nodeid)
    return tuple(owned)
