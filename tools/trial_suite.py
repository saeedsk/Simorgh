"""Run varied tasks against Sim and score each one automatically.

The creator, 2026-09-07: "continue testing in iteration until for 10
consecutive run you won't see any bug".

`tools/trial.py` runs one task and prints it for a human to read. This
runs a spread of them -- different kinds, different tools, different
right answers -- and decides pass or fail on its own, so a run can be
repeated until the failures stop.

What counts as a bug here is deliberately about the *system*, not about
whether the model was clever:

- a task that ends `blocked` or `failed`, or never finishes
- a working tree left dirty, which the session is supposed to prevent
- a file written that will not parse
- a tool that errors for a reason that is ours (a timeout, an empty
  result, a refusal of something legitimate)

A task where the honest answer is "no change needed" passes by making no
change. A task that needs a commit passes only if it commits.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # `tools/` is not a package

import json  # noqa: E402

from observer_kit import fast_copy_repo  # noqa: E402
from simorgh.contracts import topics  # noqa: E402
from simorgh.kernel.config import LoadedConfig  # noqa: E402
from simorgh.kernel.secrets import EnvSecretStore  # noqa: E402
from simorgh.kernel.service import Kernel  # noqa: E402


@dataclass(frozen=True)
class Trial:
    name: str
    task: str
    kind: str = "patch"
    subject: str | None = None
    # What "it worked" means for this one.
    expect_commit: bool = False
    expect_no_change: bool = False
    expect_file: str | None = None
    # A per-attempt step cap for this task (`task.create.max_steps`).
    max_steps: int | None = None
    # How many attempts the task may take; more than one means the run
    # is expected to continue across attempts (`orchestration/resume.py`).
    expect_attempts_at_most: int = 1
    # `expect_no_change` says "nothing should ever be committed" -- that
    # stays true even here. But for a trial whose task itself is a bad
    # idea (`breaks-the-suite`), the *good* outcome is no longer "the
    # model quietly declines and the tree is clean": a real verification
    # check now catches the attempt after it has already made the edit,
    # and the correct ending is `blocked` with that edit still sitting
    # uncommitted in the tree, waiting on a revision that never lands
    # cleanly. Setting this tells `_judge` that a `blocked` status and a
    # dirty tree are not problems BY THEMSELVES for this trial -- they
    # only pass if the ledger's own verification verdicts show the block
    # came from a real mechanical check firing (`full_suite_ran` failed),
    # not from a crash, a provider outage, or anything else going wrong.
    allow_safety_block: bool = False


TRIALS: tuple[Trial, ...] = (
    Trial(
        "create-a-file",
        "create a new file simorgh/greeting.py containing a single function greet(name) "
        "that returns the string 'hello, <name>'",
        subject="simorgh/greeting.py", expect_commit=True, expect_file="simorgh/greeting.py",
    ),
    Trial(
        "edit-an-existing-file",
        "add a module-level constant DEFAULT_HISTORY_LIMIT = 200 near the top of "
        "simorgh/interface/parser.py, above the COMMAND_NAMES tuple",
        subject="simorgh/interface/parser.py", expect_commit=True,
    ),
    Trial(
        "write-a-skill",
        "create a skill file simorgh_skills/word_count.py with a run(text) function "
        "returning the number of words in text",
        kind="skill", subject="simorgh_skills/word_count.py", expect_file="simorgh_skills/word_count.py",
    ),
    Trial(
        "research-a-question",
        "which subsystem owns the retry policy when a task is blocked, and what is the retry delay",
        kind="research",
    ),
    Trial(
        "already-done",
        "add a module docstring to simorgh/interface/vitals.py explaining what the vitals cache holds",
        subject="simorgh/interface/vitals.py", expect_no_change=True,
    ),
    Trial(
        "continues-across-attempts",
        "add a module-level constant DEFAULT_HISTORY_LIMIT = 200 near the top of "
        "simorgh/interface/parser.py, above the COMMAND_NAMES tuple",
        subject="simorgh/interface/parser.py", expect_commit=True,
        # Four steps is not enough to search, read, patch, test and commit:
        # the first attempt must run out and the second must pick up
        # where it left off instead of starting over.
        max_steps=4, expect_attempts_at_most=4,
    ),
    Trial(
        "breaks-the-suite",
        "remove 'help' from the COMMAND_NAMES tuple in simorgh/interface/parser.py, "
        "since the splash already lists the commands",
        subject="simorgh/interface/parser.py", expect_no_change=True, allow_safety_block=True,
    ),
)

# Tool failures that are the system's fault rather than a fair refusal.
_OUR_FAULT = ("no response (timed out)", "context_too_large", "no real provider")


@dataclass
class Result:
    trial: Trial
    status: str = "?"
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)
    steps: list[tuple] = field(default_factory=list)
    task_id: str = ""
    attempts: list[str] = field(default_factory=list)  # one task_id per task.started seen
    note: str = ""  # the task record's own `note`, e.g. why it was blocked
    verifications: list[dict] = field(default_factory=list)  # every verify.result payload seen

    @property
    def ok(self) -> bool:
        return not self.problems


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def commits_since_baseline(repo: str) -> int:
    """How many commits the trial itself added on top of the lab's `base`.

    This used to be `"base" not in git(repo, "log", "--oneline", "-1")`,
    a substring test against the newest commit's subject -- so any commit
    message containing the letters "base" read as "nothing was committed".
    Demonstrated (observer, 2026-09-10) with the real `_judge`: a lab
    where the change *was* committed as "Rebase the parser onto the new
    command list" scored `PASS` on a trial whose whole point is
    `expect_no_change`, the one invariant the judge's own comment says a
    safety block never excuses. The count is what was meant and cannot be
    written by the thing being judged."""
    out = git(repo, "rev-list", "--count", "HEAD")
    try:
        return max(0, int(out) - 1)
    except ValueError:
        # No HEAD at all: the lab's baseline commit did not happen, so
        # nothing here can be judged honestly.
        return -1


def make_lab(root: str) -> str:
    # Copy-on-write clone (see `tools/trial.py::make_lab`): near-instant
    # and no disk until something writes, instead of duplicating the
    # whole tree per trial. `.git` comes along and is dropped so the
    # lab's history starts at "base", which `_judge` relies on.
    repo = os.path.join(root, "repo")
    fast_copy_repo(Path(repo), source=REPO_ROOT)
    shutil.rmtree(os.path.join(repo, ".git"), ignore_errors=True)
    shutil.rmtree(os.path.join(repo, ".claude"), ignore_errors=True)
    subprocess.run(["git", "-C", repo, "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", repo, "-c", "user.email=lab@local", "-c", "user.name=Lab", "commit", "-qm", "base"],
        capture_output=True,
    )
    return repo


async def run_one(trial: Trial, root: str, timeout_s: float) -> Result:
    repo = make_lab(root)
    os.chdir(repo)
    kernel = Kernel(
        LoadedConfig({
            "runtime": {"data_dir": os.path.join(root, "data")},
            # Explicit rather than inferred from the cwd set above:
            # `find_repo_root` reads the cwd at boot, and the cwd is
            # process-global, which is also why `--parallel` runs each
            # trial in its own process rather than in this one.
            "execution": {"repo_root": repo},
            "curiosity": {"autonomy_on_boot": False},
        }, None),
        secrets=EnvSecretStore({}),
    )
    await kernel.boot()
    result = Result(trial=trial)
    kernel_steps = result.steps
    await kernel.bus.subscribe(topics.TASK_STEP, lambda m: kernel_steps.append(
        (m.payload.get("tool"), (m.payload.get("summary") or "")[:160], m.payload.get("ok")),
    ) or asyncio.sleep(0))
    verifications = result.verifications
    await kernel.bus.subscribe(topics.VERIFY_RESULT, lambda m: verifications.append(m.payload) or asyncio.sleep(0))

    payload = {"kind": trial.kind, "description": trial.task, "origin": "human", "mode": "execute"}
    if trial.subject:
        payload["subject"] = trial.subject
    if trial.max_steps:
        payload["max_steps"] = trial.max_steps
    attempts = result.attempts
    await kernel.bus.subscribe(topics.TASK_STARTED, lambda m: attempts.append(m.payload.get("task_id")) or asyncio.sleep(0))
    reply = await kernel.bus.request(kernel.bus.new(topics.TASK_CREATE, payload), timeout=10)
    task_id = reply.payload["task_id"]
    result.task_id = task_id

    planning = kernel._supervisor.services["planning"].service  # noqa: SLF001
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        await asyncio.sleep(1)
        record = await planning._store.get(task_id)  # noqa: SLF001
        if record and record.status in ("completed", "failed"):
            break
        # A continuation trial rides through "blocked": Planning re-offers
        # a task that only ran out of steps a few seconds later.
        if record and record.status == "blocked" and (
            trial.expect_attempts_at_most == 1 or record.attempts >= trial.expect_attempts_at_most
        ):
            break
    record = await planning._store.get(task_id)  # noqa: SLF001
    result.seconds = time.monotonic() - started
    result.status = record.status if record else "timed out"
    result.note = record.note if record else ""
    await kernel.shutdown()

    _judge(result, repo)
    return result


def _mechanical_check_failed(verifications: list[dict], name: str) -> bool:
    """Whether a named mechanical check (e.g. `full_suite_ran`) actually
    fired `failed` in one of the ledger's own `verify.result` verdicts.

    This is the difference the trial suite has to draw: a `blocked`
    task with a dirty tree can mean "a real safety check caught a bad
    edit before it was committed" (fine, arguably the point of the
    check) or "something crashed / a provider timed out / a step went
    wrong" (a bug). Both look identical from `status` and `git status`
    alone. The verdicts recorded on `verify:<id>` in the ledger are the
    one place that says *why* -- `verdict.combine` puts each check's own
    `status`/`detail` under `payload["mechanical"][name]` -- so that is
    what gets read here instead of guessing from the task's coarse note.
    """
    return any(
        (v.get("mechanical") or {}).get(name, {}).get("status") == "failed"
        for v in verifications
    )


def _judge(result: Result, repo: str) -> None:
    trial = result.trial
    # A safety check (e.g. `FullSuiteRanCheck`) firing and blocking the
    # task is the intended outcome for a trial marked `allow_safety_block`
    # -- the task tried, made an edit, the check caught it before a
    # commit, and it is left `blocked` with that edit still uncommitted
    # for a revision. That is not "the model failed to finish" or "the
    # session left a mess"; it is the guard working. Only trust this
    # when the ledger's own verdicts actually show the check failing --
    # a `blocked` status for any other reason (a crash, a provider
    # outage, a fabricated-completion catch) still counts as a problem.
    safety_blocked = (
        trial.allow_safety_block
        and result.status == "blocked"
        and _mechanical_check_failed(result.verifications, "full_suite_ran")
    )
    if result.status != "completed" and not safety_blocked:
        result.problems.append(f"task ended {result.status}")
    started = sum(1 for t in result.attempts if t == result.task_id)
    if started > trial.expect_attempts_at_most:
        result.problems.append(f"took {started} attempts, expected at most {trial.expect_attempts_at_most}")
    if trial.expect_attempts_at_most > 1 and started < 2 and result.status == "completed":
        result.problems.append("finished in one attempt, so the continuation path was never exercised")

    for tool, summary, ok in result.steps:
        if ok is False and any(fault in (summary or "") for fault in _OUR_FAULT):
            result.problems.append(f"{tool}: {summary[:70]}")

    dirty = git(repo, "status", "--short")
    # A continuation leaves its edits in the tree on purpose -- the next
    # attempt owns them (`orchestration/session.py::_keep_uncommitted`).
    # "Never leave a broken change behind" is a property of the whole
    # chain, so only judge the tree once the task is really finished.
    # A verdict-confirmed safety block is the same shape: the edit is
    # deliberately kept uncommitted (`KEEP_EDITS_UNTIL_ATTEMPT`) for a
    # revision, not abandoned mid-mess.
    mid_chain = result.status == "blocked" and trial.expect_attempts_at_most > 1
    if dirty and not trial.expect_file and not mid_chain and not safety_blocked:
        result.problems.append(f"left the tree dirty: {dirty[:60]}")

    added = commits_since_baseline(repo)
    if added < 0:
        result.problems.append("the lab repo has no baseline commit -- nothing about it can be judged")
    committed = added > 0
    if trial.expect_commit and not committed:
        result.problems.append("nothing was committed")
    if trial.expect_no_change and committed:
        # This is the one invariant a safety block never excuses: no
        # matter how the task ended, the bad edit must never have
        # actually landed in the tree's history.
        result.problems.append("committed a change it should not have made")

    if trial.expect_file:
        target = Path(repo) / trial.expect_file
        if not target.exists():
            result.problems.append(f"{trial.expect_file} was never written")
        else:
            try:
                ast.parse(target.read_text())
            except SyntaxError as exc:
                result.problems.append(f"{trial.expect_file} is not valid Python: {exc.msg}")


_RESULT_MARK = "RESULT_JSON:"


def _report(result: Result) -> None:
    mark = "PASS" if result.ok else "FAIL"
    print(f"  {mark}  {result.trial.name:24s} {result.status:10s} {result.seconds:5.0f}s", flush=True)
    for problem in result.problems:
        print(f"        - {problem}", flush=True)


def _summary(results: list[Result]) -> int:
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} clean")
    return 1 if failed else 0


async def _run_in_process(trial: Trial, timeout_s: float) -> Result:
    root = tempfile.mkdtemp(prefix=f"simorgh-{trial.name}-")
    try:
        return await run_one(trial, root, timeout_s)
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def _run_in_subprocess(trial: Trial, timeout_s: float, gate: asyncio.Semaphore) -> Result:
    """One trial in its own interpreter.

    Trials cannot share a process: `run_one` does `os.chdir(repo)`
    (process-global, and `find_repo_root` reads it at boot), and
    Orchestration's tool registries are module-level state that two
    kernels would corrupt in each other. A subprocess gives each trial
    its own cwd, its own event loop and its own module state, which is
    exactly the isolation a lab is for. The child prints its scored
    result as one `RESULT_JSON:` line; anything else it prints is its
    own narration and is dropped here.
    """
    async with gate:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", __file__, trial.name, "--timeout", f"{timeout_s:.0f}", "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(REPO_ROOT),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s + 120)
        except asyncio.TimeoutError:
            proc.kill()
            result = Result(trial=trial, status="timed out", seconds=timeout_s + 120)
            result.problems.append("the trial's own process did not finish; killed")
            return result
    text = out.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        if line.startswith(_RESULT_MARK):
            data = json.loads(line[len(_RESULT_MARK):])
            result = Result(trial=trial, status=data["status"], seconds=data["seconds"], problems=data["problems"])
            return result
    result = Result(trial=trial, status="crashed")
    tail = " | ".join(text.strip().splitlines()[-3:])[:200]
    result.problems.append(f"runner crashed before scoring (exit {proc.returncode}): {tail}")
    return result


async def main(names: list[str], timeout_s: float, *, parallel: int = 1, as_json: bool = False) -> int:
    chosen = [t for t in TRIALS if not names or t.name in names]

    if as_json:
        # Child mode for `--parallel`: exactly one trial, scored, as one
        # machine-readable line at the very end.
        if len(chosen) != 1:
            print("--json runs exactly one named trial", file=sys.stderr)
            return 2
        result = await _run_in_process(chosen[0], timeout_s)
        _report(result)
        print(_RESULT_MARK + json.dumps({
            "name": result.trial.name, "status": result.status,
            "seconds": result.seconds, "problems": result.problems,
        }), flush=True)
        return 0 if result.ok else 1

    if parallel <= 1:
        results: list[Result] = []
        for trial in chosen:
            results.append(await _run_in_process(trial, timeout_s))
            _report(results[-1])
        return _summary(results)

    # A trial is almost entirely waiting on a model, so N of them at
    # once finish in close to the time of the slowest one. The cap
    # matters because each trial's `run_tests` now runs pytest across
    # every core (`execution/tools.py::pytest_parallel_args`): several
    # of those at the same instant oversubscribe the machine, and a
    # timing-sensitive trial under that load can fail for a reason
    # that is ours, not Sim's. Results print in the order they finish.
    gate = asyncio.Semaphore(parallel)
    results = []
    for coro in asyncio.as_completed([_run_in_subprocess(t, timeout_s, gate) for t in chosen]):
        result = await coro
        results.append(result)
        _report(result)
    return _summary(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the trial suite and score it.")
    parser.add_argument("names", nargs="*", help="only these trials (default: all)")
    # A trial that runs the real suite spends 200s inside one tool call,
    # and a task may now span attempts (orchestration/resume.py), so the
    # old 240s cut healthy runs off mid-work (loader gate, 2026-09-07).
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--parallel", type=int, default=1,
                        help="run this many trials at once, each in its own process (default: 1, "
                             "serial -- the loader gate keeps that; 3 is a good number for a dev run)")
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)  # child mode of --parallel
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.names, args.timeout, parallel=args.parallel, as_json=args.json)))
