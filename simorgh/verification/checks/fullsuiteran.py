"""`full_suite_ran`: a patch that changes code has to be checked against
the WHOLE suite, not whatever slice the model chose to run.

`IsolatedSuiteCheck` was supposed to be this gate. It never fires for a
real orchestration-driven patch task: `applies()` requires
`req.subject.get("candidate")`/`.get("code")`, and
`orchestration/session.py::_put_verify_subject` never populates either
-- only Learning's `PatchPipeline` does, and that pipeline has never
been reachable from a real task (its drafting tools were never built;
see `simorgh/learning/README.md`'s own open question). So the one check
built to answer "does the patched suite still pass" has been silently
absent from every real patch verification since it was written.

Two trials found the practical consequence on 2026-09-08, the same day
sandbox trials got fast enough to actually run to completion instead of
timing out first: `breaks-the-suite` and `already-done` both committed
a change after `run_tests` on a NARROWED target -- one file, or a
single test -- satisfied "run the tests" literally, without the change
having been checked against anything it might have broken elsewhere.

This is not a resurrection of `IsolatedSuiteCheck` or the Learning
pipeline -- that needs real Cognition-backed drafting tools that do not
exist yet, and forcing a cutover now would break every real patch task
(2026-09-08 investigation, wave 6). This is the narrow, free, mechanical
half of the same guarantee: before a patch/self_patch task's answer is
trusted, at least one `run_tests` step in its log must have targeted
the WHOLE suite (not a subdirectory or file) and passed.

The objection that could not be answered, and the fix (2026-09-10).
Twice -- two observers, two independent live runs -- a task did exactly
what it was asked, ran the whole suite on being told to, found the
suite already red for a reason of its own, and was failed for it again
and again until its revision budget was gone, with a correct, committed
change in the tree. This check could not attribute a suite failure to
the change under review, so once the suite was red for ANY reason its
objection was unanswerable: it asked for something the task could not
deliver and had nothing else to say.

The fix is not "pass when the suite is red" -- that reintroduces
exactly the false pass this check exists to prevent. It is attribution:
`_baseline` re-runs ONLY the tests that actually failed against the
tree at the session's own `base_ref` and asks which of them were
already failing there. A change is answerable for the ones that pass
without it, and for nothing else. A pre-existing failure on a file this
task wrote (or on the test file named after it) is still no excuse --
"it was already red" must never pass a task that was supposed to fix
exactly that.

Every unknown -- no `base_ref`, no git, an unparseable or capped
failure list, a baseline run that will not complete -- resolves to "the
change is to blame", which is the behaviour this check had before any
of it existed. It can still cost a revision it should not have. It can
never accept a change that broke the suite.
"""

from __future__ import annotations

import ast
import asyncio

from simorgh.contracts.checkout import (ContainerCheckout, changed_sources, container_run, covers,
                                        find_enclosing, suggest_target)
from simorgh.contracts.pytestfailures import parse_marker
from simorgh.contracts.scratch import is_scratch

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from . import _baseline
from ._files import REPO_ROOT, written_paths
from .didanything import WRITE_TOOLS, write_steps

# Kinds whose product is a change to real source. `skill` is excluded --
# a skill's own test is `apply_skill`'s sandbox smoke run, a different
# and already-real gate; a `research` task changes nothing to break.
_CHANGE_KINDS = frozenset({"patch", "self_patch"})
# What `orchestration/session.py::_propose_and_await` prefixes onto a
# `run_tests` step's own summary/detail.
_TARGET_MARKER = "[ran target="
# A target string that means "the whole suite," matched loosely: the
# default (empty, becomes "tests"), the literal "tests" directory, or a
# leading "tests/" is still the whole tree if nothing narrower follows
# -- but "tests/simorgh/guardian" or "tests/x/test_y.py" is a slice.
_WHOLE_SUITE_TARGETS = frozenset({"tests", "tests/", "'tests'", "'tests/'"})
# `execution/tools.py::RunTestsTool` deliberately reports `ok=True` when
# pytest's own exit code is 5 ("no tests collected") -- added
# 2026-09-07 so a brand-new file with no tests yet does not block a
# commit -- and appends this exact string to its output whenever that
# happens. Live-probed 2026-09-09: a `run_tests` call whose target
# textually matches `_WHOLE_SUITE_TARGETS` can still report `ok=True`
# with this marker present if the whole `tests/` tree happens to
# collect zero test items (e.g. a self_patch that guts every test
# file) -- "ran and passed" would otherwise be true of a run that
# checked nothing at all.
_NO_TESTS_COLLECTED_MARKER = "no tests cover this target yet -- nothing was run"


def _steps(req: VerifyRequest) -> list[dict]:
    steps = req.subject.get("steps")
    return (
        [s for s in steps if isinstance(s, dict) and s.get("phase") == "act"]
        if isinstance(steps, list) else []
    )


def _ran_whole_suite_and_passed(steps: list[dict]) -> bool:
    for step in steps:
        if step.get("tool") != "run_tests" or not step.get("ok"):
            continue
        summary = str(step.get("summary") or "")
        if not summary.startswith(_TARGET_MARKER):
            # A run_tests step recorded before this fix, or truncated
            # past the marker -- cannot tell what it ran. Treated as NOT
            # the whole suite, the safer direction: this check only ever
            # costs a revision it should not have, never lets a real
            # regression through silently.
            continue
        target = summary[len(_TARGET_MARKER):].split("]", 1)[0].strip()
        if target in _WHOLE_SUITE_TARGETS and _NO_TESTS_COLLECTED_MARKER not in summary:
            return True
    return False


def _ran_whole_suite_and_failed(steps: list[dict]) -> bool:
    """The whole suite ran and did not pass.

    Worth telling apart from "never ran", because the advice is the
    opposite. Without it the check told a task that had just run the
    entire suite that `run_tests` "was called on a narrower target than
    the whole suite, or never called at all" -- both halves false, and
    no move left but to run it again (observer, 2026-09-10)."""
    for step in steps:
        if step.get("tool") != "run_tests" or step.get("ok"):
            continue
        summary = str(step.get("summary") or "")
        if not summary.startswith(_TARGET_MARKER):
            continue
        if summary[len(_TARGET_MARKER):].split("]", 1)[0].strip() in _WHOLE_SUITE_TARGETS:
            return True
    return False


def _whole_suite_failure_ids(steps: list[dict]) -> tuple[str, ...] | None:
    """The node ids of the LAST failing whole-suite run, or None.

    None means the run named none that survived to here -- an older
    step, a crash with no short summary, or more failures than the
    marker carries. Every caller treats that as "cannot attribute".
    """
    for step in reversed(steps):
        if step.get("tool") != "run_tests" or step.get("ok"):
            continue
        summary = str(step.get("summary") or "")
        if not summary.startswith(_TARGET_MARKER):
            continue
        if summary[len(_TARGET_MARKER):].split("]", 1)[0].strip() not in _WHOLE_SUITE_TARGETS:
            continue
        return parse_marker(summary)
    return None


async def _attribution(req: VerifyRequest, steps: list[dict]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """`(introduced, owned)` for a red whole-suite run, or None.

    `introduced` are the tests that pass at the session's base revision
    and fail now -- the ones this change is answerable for. `owned` are
    tests that were already failing but sit on files this task wrote or
    is named after, which no "it was already red" excuse covers.

    None is "no opinion", and the check then behaves exactly as it did
    before this existed. See `_baseline` for the full list of unknowns
    that resolve here, and why every one of them errs towards blaming
    the change.
    """
    base_ref = req.subject.get("base_ref")
    if not isinstance(base_ref, str) or not base_ref:
        return None
    written = written_paths(req)
    if not written:
        # Without knowing what this task wrote, `owned_by` cannot refuse
        # the excuse to a task that was supposed to fix the very test
        # still failing -- and an excuse granted blind is exactly the
        # false pass this whole check exists to prevent.
        return None
    nodeids = _whole_suite_failure_ids(steps)
    if not nodeids:
        return None
    # Blocking git + pytest work; this coroutine runs inside the
    # verification service's own loop, and holding it for a baseline run
    # would stall every other check and every heartbeat with it.
    new = await asyncio.to_thread(_baseline.introduced, base_ref, nodeids)
    if new is None:
        return None
    already = tuple(n for n in nodeids if n not in set(new))
    return new, _baseline.owned_by(already, written)


def _touched_python(req: VerifyRequest) -> bool:
    """Whether this task wrote any Python at all.

    The whole point of this check is "your change might have broken
    something else, and only the suite can tell you". A task whose only
    product is a `.html` page cannot break the Python suite, and there
    is nothing for the suite to say about it -- `js_syntax`, `render`
    and `trailing_narration` are its real gates. Demanding a suite run
    anyway is how the second 95120 trial blocked with a correct page
    uncommitted (live, 2026-09-09).

    A `.py` under `workspace/` is the same case one directory over.
    That is scratch: gitignored, imported by no test, invisible to
    review, and incapable of breaking the suite. Demanding a 4,600-test
    run before a throwaway script may be written cost a real task its
    whole revision budget -- Sim built the script, ran the suite, the
    suite failed for reasons of its own, and the task was abandoned
    holding a correct artefact (observer, 2026-09-10).

    Unknown is Python: when the request carries no `written_paths` at
    all (an older producer, a blocked session), this stays true and the
    check behaves exactly as it did before -- the conservative reading,
    since a missed suite run is the bug this check exists to catch.
    """
    paths = written_paths(req)
    if not paths:
        return True
    return any(p.lower().endswith(".py") and not is_scratch(p) for p in paths)


def _container_runs(steps: list[dict]) -> list[tuple[bool, str, str]]:
    """`(ok, target, image)` for every `run_tests` that ran inside a
    checkout's own container (`contracts/checkout.py`)."""
    found = []
    for step in steps:
        if step.get("tool") != "run_tests":
            continue
        run = container_run(str(step.get("summary") or ""))
        if run is not None:
            found.append((bool(step.get("ok")), run[0], run[1]))
    return found


def _repo_target(summary: str) -> str:
    """The repo-relative target a `run_tests` step was called with, from
    the `[ran target='...']` prefix `orchestration/session.py` puts on
    its summary; "" when the prefix is missing."""
    if not summary.startswith(_TARGET_MARKER):
        return ""
    raw = summary[len(_TARGET_MARKER):].split("]", 1)[0].strip()
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw.strip("'\"")
    return value if isinstance(value, str) else ""


def _coverage(steps: list[dict]) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, str], str]:
    """`(changed, uncovered, hints, problem)` for the passing container
    runs in `steps`, judged against the checkout's own git.

    `changed` is every Python source file the checkout differs from its
    manifest's base commit by; `uncovered` the ones no passing run could
    have exercised (`contracts.checkout.covers`); `hints` a checkout-
    relative target per uncovered file. `problem` is set, and the other
    three empty, when the question cannot be answered -- the checkout is
    no longer on disk, carries no manifest, or git will not say. That is
    the one place this errs towards the OLD answer rather than towards
    blame: a run whose checkout cannot be read happened in a tree the
    verifier can no longer see, and every real session verifies while
    its checkout is still there (`benchmark/runner.py` removes it only
    after the task ends).
    """
    passed_by_checkout: dict[Path, list[str]] = {}
    problem = ""
    for step in steps:
        if step.get("tool") != "run_tests" or not step.get("ok"):
            continue
        summary = str(step.get("summary") or "")
        run = container_run(summary)
        if run is None:
            continue
        repo_target = _repo_target(summary)
        enclosing = find_enclosing(REPO_ROOT, repo_target) if repo_target else None
        if enclosing is None:
            problem = problem or f"the checkout for {run[0]!r} could not be found on disk"
            continue
        passed_by_checkout.setdefault(enclosing[0], []).append(run[0])
    if not passed_by_checkout:
        return (), (), {}, problem or "no passing container run names a checkout"
    changed_all: list[str] = []
    uncovered: list[str] = []
    hints: dict[str, str] = {}
    for checkout, targets in passed_by_checkout.items():
        manifest = ContainerCheckout.read(checkout)
        if manifest is None:
            return (), (), {}, f"{checkout.name} carries no readable manifest"
        changed = changed_sources(checkout, manifest.diff_base)
        if changed is None:
            return (), (), {}, f"git would not say what changed in {checkout.name}"
        try:
            prefix = checkout.relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            prefix = checkout.as_posix()
        for path in changed:
            shown = f"{prefix}/{path}"
            changed_all.append(shown)
            if not any(covers(target, path, checkout=checkout) for target in targets):
                uncovered.append(shown)
                hints[shown] = f"{prefix}/{suggest_target(checkout, path)}"
    return tuple(changed_all), tuple(uncovered), hints, ""


class FullSuiteRanCheck:
    name = "full_suite_ran"
    # Free in every case but one: reading the step log costs nothing,
    # and only a red WHOLE-suite run pays for a baseline (`_baseline`,
    # bounded by `BASELINE_TIMEOUT_S`). "cheap" rather than "free" so
    # the service's cheapest-first ordering runs the genuinely free
    # checks ahead of it -- if one of those is going to fail anyway, it
    # short-circuits before anything here spawns a pytest.
    cost = "cheap"

    def applies(self, req: VerifyRequest) -> bool:
        steps = _steps(req)
        # Same completeness gate as `DidAnythingCheck`: a retry's own
        # step log is not the whole session's history, and a task whose
        # earlier attempt already ran the whole suite must not be failed
        # here for an attempt that only commits.
        #
        # And the same "nothing to test" exemption `DidAnythingCheck`
        # already grants an honest no-op: if no write tool ran ANYWHERE
        # in the (complete) log, there is nothing this task could have
        # broken, and `DidAnythingCheck` is the one that owns judging
        # whether skipping the write was correct. Without this, a
        # legitimate "the file already has what was asked for; no
        # change needed" answer would be told to go run a suite it had
        # no reason to run.
        return (
            req.subject.get("kind") in _CHANGE_KINDS
            and bool(steps)
            and req.subject.get("complete_log", True)
            and bool(write_steps(steps))
            and _touched_python(req)
        )

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        steps = _steps(req)
        in_container = _container_runs(steps)
        if in_container:
            # The change lives in somebody else's project (a materialised
            # SWE-bench checkout under `workspace/`), and `run_tests` ran
            # THAT project's tests inside THAT project's image. This suite
            # -- Simorgh's -- has nothing to say about it, and demanding it
            # anyway is what happened on 2026-09-10: told "no run_tests
            # call in this session at all", Sim ran the whole Simorgh
            # suite from inside an astropy task, it failed on a machine-
            # specific security check, and the case was lost to a suite
            # that could not possibly have covered the change. A targeted
            # run in the project's own container is the proportionate
            # bar: that project's whole suite takes an hour under
            # emulation, and the scorer itself runs a named subset.
            passed = [r for r in in_container if r[0]]
            if passed:
                _ok, target, image = passed[-1]
                ran = f"the project's own tests ran inside its container ({image}: {target}) and passed"
                evidence: dict = {"container_runs": [list(r) for r in in_container]}
                # Passing is not enough on its own. Live, 2026-09-10: Sim
                # changed one module, ran an unrelated test file, that
                # file passed, and a change that broke 28 tests in the
                # module it had edited was accepted. Every source file
                # the checkout differs from its base by has to sit under
                # something a passing run could have exercised -- read
                # from the checkout's own git, so an edit made with
                # `run_shell` counts the same as one made with a tool
                # that reports `file_write` (`contracts.checkout`).
                changed, uncovered, hints, problem = await asyncio.to_thread(_coverage, steps)
                evidence.update({"changed": list(changed), "uncovered": list(uncovered)})
                if problem:
                    evidence["coverage"] = problem
                    return CheckResult(status="passed", detail=f"{ran}; whether that run covered the change "
                                                                f"could not be checked: {problem}", evidence=evidence)
                if not changed:
                    return CheckResult(status="passed", detail=f"{ran}; the checkout has no source change to cover",
                                       evidence=evidence)
                if not uncovered:
                    return CheckResult(status="passed", detail=f"{ran}, covering {', '.join(changed[:6])}",
                                       evidence=evidence)
                targets = sorted(set(hints.values()))
                detail = (f"{ran} -- but that run could not have exercised {', '.join(uncovered[:6])}, which this "
                          f"task changed; the change is not checked until a test that covers it passes")
                return CheckResult(
                    status="failed", detail=detail, evidence=evidence,
                    feedback=Feedback(
                        mechanical_errors=(detail,),
                        revise_hint=(f"call run_tests on the tests nearest what you changed -- "
                                     f"{' or '.join(targets[:3])} -- or on a test file that imports it, "
                                     "and make it pass; a passing run of an unrelated file proves nothing "
                                     "about this change"),
                        retryable=True,
                    ),
                )
            _ok, target, image = in_container[-1]
            detail = (f"the project's own tests ran inside its container ({image}: {target}) and FAILED "
                      f"-- the change is not checked until they pass")
            return CheckResult(
                status="failed", detail=detail,
                evidence={"container_runs": [list(r) for r in in_container]},
                feedback=Feedback(
                    mechanical_errors=(detail,),
                    revise_hint=("read the failures in that run_tests output, fix the change, and run the "
                                 "same target again -- not Simorgh's own suite, which does not cover this project"),
                    retryable=True,
                ),
            )
        if _ran_whole_suite_and_passed(steps):
            return CheckResult(status="passed", detail="the whole suite ran and passed")
        ran_something = any(s.get("tool") == "run_tests" for s in steps)
        suite_failed = _ran_whole_suite_and_failed(steps)
        hint = ("call run_tests with no target (or target='tests') to run the whole suite, "
                "confirm it passes, then commit")
        evidence: dict = {}
        if suite_failed:
            # The whole point of the attribution work: "the suite is
            # red" is not by itself an objection this task can answer.
            # Once the suite is red for a reason that predates the
            # session, demanding a green suite is demanding something
            # the task cannot deliver, and the only thing that used to
            # happen next was the revision budget burning down with a
            # correct, committed change in the tree (two observers,
            # 2026-09-09 and 2026-09-10).
            verdict = await _attribution(req, steps)
            if verdict is not None:
                introduced, owned = verdict
                evidence = {"introduced": list(introduced), "already_failing_and_owned": list(owned),
                            "base_ref": req.subject.get("base_ref")}
                if not introduced and not owned:
                    return CheckResult(
                        status="passed",
                        detail=("the whole suite ran and failed, but every failing test also fails at "
                                f"{str(req.subject.get('base_ref'))[:12]} -- this change introduced none of them"),
                        evidence=evidence,
                    )
                if introduced:
                    detail = ("the whole suite was run and this change made tests fail that pass without "
                              f"it: {', '.join(introduced[:10])}")
                    hint = ("these tests pass at the revision this session started from and fail with your "
                            f"change: {', '.join(introduced[:10])}. Fix the change (or revert it); the rest "
                            "of the suite's failures are not yours and you do not need to fix them")
                else:
                    detail = ("the whole suite was run and tests covering the files this task wrote are "
                              f"still failing: {', '.join(owned[:10])}")
                    hint = (f"{', '.join(owned[:10])} were failing before this session and are still "
                            "failing, and they cover what this task wrote -- they are the work, not "
                            "unrelated noise. Read those failures and address them")
                return CheckResult(
                    status="failed", detail=detail, evidence=evidence,
                    feedback=Feedback(mechanical_errors=(detail,), revise_hint=hint, retryable=True),
                )
            detail = ("the whole suite was run and it FAILED -- the change is not checked until "
                      "the suite passes")
            hint = ("the whole suite already ran and did not pass. Read the failures in that "
                    "run_tests output and fix them; running the same target again will not "
                    "change the answer")
        elif ran_something:
            detail = ("run_tests was called on a narrower target than the whole suite -- "
                      "this change was never checked against anything it might have broken elsewhere")
        else:
            detail = "no run_tests call in this session at all -- this change was never checked against anything"
        return CheckResult(
            status="failed", detail=detail,
            evidence={"steps_with_run_tests": sum(1 for s in steps if s.get("tool") == "run_tests"),
                      "whole_suite_failed": suite_failed, **evidence},
            feedback=Feedback(
                mechanical_errors=(detail,),
                revise_hint=hint,
                retryable=True,
            ),
        )
