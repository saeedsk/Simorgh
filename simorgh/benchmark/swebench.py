"""Scoring SWE-bench: apply the patch, run the tests, read the log.

The suite shipped `scorable=False` with a note saying a real evaluator
was the next piece of work, and `benchmark run swebench-verified`
refused rather than inventing a number. That refusal was right. This is
the evaluator, and the rule it is built on is the same one: **a case is
scored by running its tests, or it is not scored at all.** There is no
path here that guesses from the shape of a diff.

How a case is judged, which is SWE-bench's own definition:

- every test in `FAIL_TO_PASS` must pass after the patch (it failed
  before -- that is the bug being fixed);
- every test in `PASS_TO_PASS` must still pass (nothing else broke).

Both, or the case is unresolved.

The dataset variant used here carries `image`, `eval_script` and
`log_parser` per instance, so the harness does not have to reconstruct
any of that: run the image, apply the model's patch, run the script the
dataset gave us, and read the log with the parser it named.

**Verified on this machine before being trusted** (2026-09-10, arm64
under amd64 emulation): with the gold patch, astropy-12907 reports 15
passed and the two FAIL_TO_PASS tests among them; with no patch, the
same two fail and 13 pass. A harness that cannot tell those apart is
not measuring anything, so that is the check, not a unit test over a
canned string. It caught a real bug the unit tests could not: the eval
script's markers go to stderr and pytest's results to stdout, so
capturing the streams separately put every result outside the markers
and scored a known-good patch as unmeasurable.

One honest caveat, found the same day. Django's eval script runs the
whole test suite in one process, and on this machine that run is
order-polluted: seven `auth_tests.test_templates` tests error with
`TemplateDoesNotExist` under the full suite and pass when run alone,
before and after the patch. They are in django-10097's FAIL_TO_PASS, so
a gold patch scores unresolved here. That is an environment difference,
not a parser bug, and it is reported as a failure rather than hidden --
a Django result from this machine should be read with it in mind.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: Where Docker lives when it is not on PATH -- the same fallback
#: `execution/capabilities.py` already uses for its own probe.
_DOCKER_FALLBACK = "/Applications/Docker.app/Contents/Resources/bin/docker"

#: The eval images are published for amd64 only. On Apple Silicon they
#: run under emulation: slower, and correct -- proven by the gold-patch
#: check above, which is the only evidence that matters.
PLATFORM = "linux/amd64"


@dataclass(frozen=True)
class Verdict:
    """What running one instance's tests actually showed."""

    resolved: bool
    detail: str
    #: Named in the dataset, and what each did when we ran it.
    required_pass: tuple[str, ...] = ()
    required_keep: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()      # named by the dataset, absent from the log
    failed: tuple[str, ...] = ()
    #: Named by the dataset, present in the log, and the log does not
    #: say whether it passed: skipped, or a key two tests share. A test
    #: that never ran is not a test the patch broke.
    unmeasured: tuple[str, ...] = ()
    #: True when the harness could not run or could not read the result.
    #: Distinct from `resolved=False`, which means the tests ran and the
    #: patch did not fix the bug. Conflating them would turn "we could
    #: not measure this" into "the model was wrong".
    skipped: bool = False
    log_excerpt: str = ""


def docker_path() -> str:
    return shutil.which("docker") or (_DOCKER_FALLBACK if Path(_DOCKER_FALLBACK).exists() else "")


def available() -> tuple[bool, str]:
    """`(ok, why not)`. Never raises; the caller turns this into a
    refusal that names what to install or start."""
    docker = docker_path()
    if not docker:
        return False, "Docker is not installed, and SWE-bench is scored by running each "\
                      "instance's own test container"
    try:
        done = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, text=True, timeout=20,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker is installed but not usable ({exc!r})"
    if done.returncode != 0:
        return False, "the Docker daemon is not running"
    return True, ""


# -- log parsing -------------------------------------------------------------
#
# Each repo's test runner prints its own shape, and the dataset names
# which one to expect. Only the shapes verified against a real run are
# implemented; anything else is refused BY NAME rather than parsed on a
# guess, because a wrong parse is a wrong score and a wrong score is
# worse than no score.

_PYTEST_LINE = re.compile(r"^(?P<status>PASSED|FAILED|ERROR|SKIPPED)\s+(?P<rest>\S.*)$", re.M)
#: Some configurations print the status after the test id instead. The
#: id can contain spaces inside its parameter brackets, so this cannot
#: stop at the first one.
#: `[ \t]+`, never `\s+`: with `\s+` the gap could be the NEWLINE, so
#: a status-first line followed by another status-first line matched as
#: one "test id" ending in the next line's verdict.
_PYTEST_TRAILING = re.compile(
    r"^(?P<test>\S[^\n]*?::[^\n]+?)[ \t]+(?P<status>PASSED|FAILED|ERROR|SKIPPED)\b", re.M)
#: pytest's skip SUMMARY line, which names a file and a line rather than
#: a test: `SKIPPED [1] tests/test_toy.py:9: needs network`. Read as a
#: result it invents a test called "[1] tests/test_toy.py:9: ...".
_PYTEST_SKIP_COUNT = re.compile(r"^\[\d+\]\s")


def _nodeid(rest: str) -> str:
    """The test id out of the text after a status word.

    pytest appends `- <message>` to a failure line, and a parametrised
    id can contain both spaces and dashes inside its brackets, so the
    split has to respect bracket depth. Cutting at the first " - "
    turned `test_param[x - y]` into `test_param[x` -- and `judge` then
    reported that the dataset's test "never appeared in the log" and
    threw away a run that had measured it perfectly well (observer,
    2026-09-10)."""
    depth = 0
    for index, char in enumerate(rest):
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif depth == 0 and rest.startswith(" - ", index):
            return rest[:index].strip()
    return rest.strip()

#: Django's runner prints `<label> ... <verdict>`, where the label is
#: the test id `test_name (module.Class)` only when the test has NO
#: docstring; when it has one, the id is printed on its own line and
#: the label before the verdict is the docstring's first line. The
#: dataset names tests by whichever of those two the runner printed, so
#: the key is the text left of `...`, whatever that text is -- reading
#: the id instead would miss every documented test, and in Django's
#: suite most tests are documented.
_DJANGO_VERDICT = re.compile(r"^(?P<test>.+?)\s+\.\.\.\s*(?P<status>ok|OK|FAIL|ERROR|skipped\b.*)$")
#: The failure summary at the end of the run, which names the id even
#: for a documented test.
_DJANGO_SUMMARY = re.compile(r"^(?P<status>FAIL|ERROR):\s+(?P<test>\S+(?: \([\w.]+\))?)")

#: Two runs disagreeing about one key. Django names a documented test by
#: its docstring, and a docstring is not unique -- two classes sharing
#: one line means the last result written wins, so a namesake that
#: passed could mark a failing test as passed and the case as resolved
#: (observer, 2026-09-10). Unmeasurable is the only honest reading.
AMBIGUOUS = "AMBIGUOUS"

_GOOD = {"PASSED", "ok"}
_BAD = {"FAILED", "ERROR", "FAIL"}


def parse_pytest(log: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in _PYTEST_LINE.finditer(log):
        rest = match.group("rest")
        if _PYTEST_SKIP_COUNT.match(rest):
            continue        # a skip tally, not a test result
        out[_nodeid(rest)] = match.group("status")
    for match in _PYTEST_TRAILING.finditer(log):
        out.setdefault(match.group("test").strip(), match.group("status"))
    return out


def parse_django(log: str) -> dict[str, str]:
    """Django's runner, both shapes it prints.

    Verified against a real run of django-10097 (2026-09-10): 36,000
    lines, both the bare-id form and the docstring form present, and
    every name the dataset asks about found.
    """
    out: dict[str, str] = {}
    for line in log.split("\n"):
        line = line.strip()
        found = _DJANGO_VERDICT.match(line)
        if found:
            raw = found.group("status")
            status = ("SKIPPED" if raw.startswith("skipped")
                      else "PASSED" if raw in ("ok", "OK") else raw)
            key = found.group("test").strip()
            seen = out.get(key)
            # Two progress lines under one key that disagree: the key
            # names more than one test and nothing here can tell them
            # apart. Recorded as ambiguous rather than letting the last
            # line win, which is how a passing namesake could certify a
            # failing test.
            out[key] = AMBIGUOUS if (seen is not None and seen != status) else status
            continue
        summary = _DJANGO_SUMMARY.match(line)
        if summary:
            # A summary line names the test id, which IS unique, and is
            # the last word on that test: a subtest can report `ok` on
            # the progress line and still fail here.
            out[summary.group("test").strip()] = summary.group("status")
    return out


#: Dataset parser name -> ours. Everything in this table has been read
#: off a real run of that repo's tests.
PARSERS = {
    "parse_log_pytest": parse_pytest,
    "parse_log_astropy": parse_pytest,
    "parse_log_sympy": parse_pytest,
    "parse_log_sphinx": parse_pytest,
    "parse_log_matplotlib": parse_pytest,
    "parse_log_scikit": parse_pytest,
    "parse_log_xarray": parse_pytest,
    "parse_log_requests": parse_pytest,
    "parse_log_seaborn": parse_pytest,
    "parse_log_flask": parse_pytest,
    "parse_log_django": parse_django,
}


def parse_log(log: str, parser: str) -> tuple[dict[str, str], str]:
    """`(results, problem)`. An unknown parser is a refusal, not a
    guess: `pylint`'s runner prints a shape neither of ours reads, and
    scoring it with the wrong one would report failures that are really
    unrecognised lines."""
    handler = PARSERS.get(parser)
    if handler is None:
        return {}, (f"no log parser for {parser!r} yet -- this repo's test runner prints a shape "
                    f"neither the pytest nor the Django reader understands, and guessing at it "
                    f"would produce a score rather than a measurement")
    return handler(log), ""


def _names(value) -> tuple[str, ...]:
    """The dataset stores these as a JSON array, sometimes already
    decoded."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


def judge(log: str, instance: dict) -> Verdict:
    """SWE-bench's own definition, applied to one run's log."""
    results, problem = parse_log(log, str(instance.get("log_parser") or ""))
    if problem:
        return Verdict(False, problem, skipped=True, log_excerpt=log[-1500:])
    if not results:
        return Verdict(False, "the test log had no recognisable results -- the suite most likely "
                              "never ran (an install or import failure earlier in the log)",
                       skipped=True, log_excerpt=log[-1500:])

    required_pass = _names(instance.get("FAIL_TO_PASS"))
    required_keep = _names(instance.get("PASS_TO_PASS"))
    if not required_pass:
        # Nothing to measure is not a pass. `_names` returns () for a
        # row whose FAIL_TO_PASS is missing, empty, or in a shape it
        # cannot decode, and the success return below then reported
        # "all 0 fail-to-pass and 0 pass-to-pass test(s) pass" with
        # `resolved=True` -- a case certified without a single check,
        # from any drift in the dataset's shape (observer, 2026-09-10).
        return Verdict(False, "this case names no fail-to-pass tests, so nothing here decides "
                              "whether the bug was fixed -- reload the suite and check the row",
                       skipped=True, log_excerpt=log[-1500:])
    failed, missing, unmeasured = [], [], []
    for name in required_pass + required_keep:
        status = results.get(name)
        if status is None:
            missing.append(name)
        elif status in _BAD:
            failed.append(name)
        elif status not in _GOOD:
            # SKIPPED, or AMBIGUOUS. Neither says the patch worked and
            # neither says it broke anything.
            unmeasured.append(name)

    if missing:
        # A test the dataset names and the log never mentions means the
        # run did not do what we think it did. Reporting that as "the
        # patch failed" would blame the model for our own blind spot.
        return Verdict(False, f"{len(missing)} named test(s) never appeared in the log, "
                              f"e.g. {missing[0][:80]}",
                       required_pass=required_pass, required_keep=required_keep,
                       missing=tuple(missing), failed=tuple(failed), skipped=True,
                       log_excerpt=log[-1500:])
    if failed:
        # A real failure outranks an unmeasured test: the patch broke
        # something, and that is true whatever else could not be read.
        broke = [n for n in failed if n in required_keep]
        detail = (f"{len(failed)} test(s) still failing"
                  + (f", including {len(broke)} that passed before the patch" if broke else ""))
        return Verdict(False, detail, required_pass=required_pass, required_keep=required_keep,
                       failed=tuple(failed), unmeasured=tuple(unmeasured), log_excerpt=log[-1500:])
    if unmeasured:
        # Everything that ran was fine, and something the dataset names
        # did not run. Reporting that as a failure blamed the patch for
        # a test that was skipped; reporting it as a pass would certify
        # a case nobody checked.
        return Verdict(False, f"{len(unmeasured)} named test(s) neither passed nor failed "
                              f"(skipped, or a name the log gives to more than one test), "
                              f"e.g. {unmeasured[0][:80]}",
                       required_pass=required_pass, required_keep=required_keep,
                       unmeasured=tuple(unmeasured), skipped=True, log_excerpt=log[-1500:])
    return Verdict(True, f"all {len(required_pass)} fail-to-pass and {len(required_keep)} "
                         f"pass-to-pass test(s) pass",
                   required_pass=required_pass, required_keep=required_keep)



# -- running one instance ----------------------------------------------------
#
# Two container steps, and they are deliberately separate:
#
# 1. `materialize` copies `/testbed` out of the image so the system
#    under test edits a real checkout with its ordinary file tools,
#    rather than being asked to imagine a diff for code it cannot read.
# 2. `evaluate` applies the resulting patch inside a fresh container and
#    runs the dataset's own eval script there.
#
# Nothing is scored from the checkout copy: the patch is re-applied to a
# pristine container, so a system that edited test files, deleted the
# git history or wrote outside the tree cannot influence the result
# except through the diff it produced.

#: Everything between these two lines is the test run itself. The
#: script prints `git show` and the applied test patch first, and a diff
#: can contain lines that look exactly like test results -- scoring the
#: whole transcript would read the patch as evidence about the tests.
_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}")

_START = ">>>>> Start Test Output"
_END = ">>>>> End Test Output"


def test_output(log: str) -> str:
    """The test run, cut out of the eval script's whole transcript."""
    start = log.find(_START)
    if start < 0:
        return log
    end = log.find(_END, start)
    return log[start + len(_START):end if end > 0 else len(log)]


def _run(args: list[str], *, timeout: float) -> tuple[int, str]:
    """One command, its two streams merged.

    Merged rather than concatenated, and that is not a detail: the eval
    script's `set -x` writes its `>>>>> Start Test Output` marker to
    stderr while pytest writes results to stdout, so capturing them
    apart and joining them puts every result OUTSIDE the markers. The
    first live run of this evaluator scored a known-good gold patch as
    unmeasurable for exactly that reason."""
    try:
        done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL, errors="replace")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:.0f}s"
    except OSError as exc:
        return 125, repr(exc)
    return done.returncode, done.stdout or ""


def materialize(instance: dict, dest: Path, *, timeout: float = 900.0) -> str:
    """Copy the instance's `/testbed` to `dest`. Returns "" or why not.

    A copy, not a mount: the container is never given write access to
    anything of ours, and the checkout the system edits is a throwaway.
    """
    docker = docker_path()
    image = str(instance.get("image") or "")
    if not docker:
        return "Docker is not installed"
    if not image:
        return "the dataset row names no container image for this instance"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    code, out = _run([docker, "create", "--platform", PLATFORM, image, "true"], timeout=timeout)
    if code != 0:
        return f"could not create a container from {image}: {out.strip()[:400]}"
    # The id, not the last line: with the streams merged, Docker's own
    # "platform does not match" warning shares this output.
    ids = [line.strip() for line in out.splitlines() if _CONTAINER_ID.fullmatch(line.strip())]
    if not ids:
        return f"docker create printed no container id: {out.strip()[:300]}"
    container = ids[-1]
    try:
        code, out = _run([docker, "cp", f"{container}:/testbed/.", str(dest)], timeout=timeout)
    finally:
        _run([docker, "rm", "-f", container], timeout=120.0)
    if code != 0:
        shutil.rmtree(dest, ignore_errors=True)
        return f"could not copy the checkout out of {image}: {out.strip()[:400]}"
    return ""


def diff_of(checkout: Path, *, timeout: float = 120.0) -> tuple[str, str]:
    """`(patch, problem)` -- what the system changed in the checkout.

    Source files only. A model that "fixes" a case by editing its tests
    is not fixing anything, and SWE-bench restores the test files before
    running anyway, so a test edit in the diff is dropped here where it
    is visible rather than silently undone later.
    """
    git = shutil.which("git")
    if not git:
        return "", "git is not installed, and the patch is read as a diff of the checkout"
    code, out = _run([git, "-C", str(checkout), "add", "-A"], timeout=timeout)
    if code != 0:
        return "", f"could not stage the checkout: {out.strip()[:300]}"
    code, out = _run([git, "-C", str(checkout), "diff", "--cached", "--binary",
                      "--", ".", ":(exclude)tests", ":(exclude)*/tests/*", ":(exclude)test_*.py"],
                     timeout=timeout)
    if code != 0:
        return "", f"could not read the checkout's diff: {out.strip()[:300]}"
    return out, ""


def evaluate(instance: dict, patch: str, *, timeout: float = 3600.0,
             log_path: Path | None = None) -> tuple[Verdict, str]:
    """Apply `patch` in a fresh container, run the dataset's eval script,
    judge the log. Returns `(verdict, log)`."""
    docker = docker_path()
    image = str(instance.get("image") or "")
    script = str(instance.get("eval_script") or "")
    if not docker:
        return Verdict(False, "Docker is not installed", skipped=True), ""
    if not image or not script:
        return Verdict(False, "the dataset row carries no image or eval script for this instance",
                       skipped=True), ""
    if not patch.strip():
        # Not `skipped`: the run happened and produced nothing to test.
        # Calling this unmeasurable would hide the most common failure.
        return Verdict(False, "the system produced no patch"), ""

    with tempfile.TemporaryDirectory(prefix="swebench-") as raw:
        stage = Path(raw)
        (stage / "patch.diff").write_text(patch if patch.endswith("\n") else patch + "\n")
        (stage / "eval.sh").write_text(script)
        # `git apply` first because it is exact; `patch` after because a
        # model's diff often has the right content and imprecise line
        # numbers, and SWE-bench's own harness does the same.
        runner = (
            "set -o pipefail\n"
            "cd /testbed\n"
            "git apply -v /eval/patch.diff "
            "|| patch --batch --fuzz=5 -p1 -i /eval/patch.diff "
            "|| { echo 'SIMORGH_PATCH_FAILED'; exit 90; }\n"
            "bash /eval/eval.sh\n"
        )
        (stage / "run.sh").write_text(runner)
        code, log = _run([docker, "run", "--rm", "--platform", PLATFORM,
                          "-v", f"{stage}:/eval:ro", image, "bash", "/eval/run.sh"],
                         timeout=timeout)

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(log)
        except OSError:
            pass

    if "SIMORGH_PATCH_FAILED" in log:
        # A patch that does not apply is a wrong answer, not an
        # unmeasurable one: the system was asked for a change to this
        # tree and produced one that does not fit it.
        return Verdict(False, "the patch did not apply to the repository",
                       log_excerpt=log[-1500:]), log
    if code == 124:
        return Verdict(False, f"the test run {log}", skipped=True, log_excerpt=log[-1500:]), log
    return judge(test_output(log), instance), log


__all__ = ["PARSERS", "PLATFORM", "Verdict", "available", "diff_of", "docker_path", "evaluate",
           "judge", "materialize", "parse_django", "parse_log", "parse_pytest", "test_output"]
