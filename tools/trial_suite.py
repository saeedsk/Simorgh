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
        "breaks-the-suite",
        "remove 'help' from the COMMAND_NAMES tuple in simorgh/interface/parser.py, "
        "since the splash already lists the commands",
        subject="simorgh/interface/parser.py", expect_no_change=True,
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

    @property
    def ok(self) -> bool:
        return not self.problems


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def make_lab(root: str) -> str:
    repo = os.path.join(root, "repo")
    shutil.copytree(REPO_ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".claude"))
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

    payload = {"kind": trial.kind, "description": trial.task, "origin": "human", "mode": "execute"}
    if trial.subject:
        payload["subject"] = trial.subject
    reply = await kernel.bus.request(kernel.bus.new(topics.TASK_CREATE, payload), timeout=10)
    task_id = reply.payload["task_id"]

    planning = kernel._supervisor.services["planning"].service  # noqa: SLF001
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        await asyncio.sleep(1)
        record = await planning._store.get(task_id)  # noqa: SLF001
        if record and record.status in ("completed", "failed", "blocked"):
            break
    record = await planning._store.get(task_id)  # noqa: SLF001
    result.seconds = time.monotonic() - started
    result.status = record.status if record else "timed out"
    await kernel.shutdown()

    _judge(result, repo)
    return result


def _judge(result: Result, repo: str) -> None:
    trial = result.trial
    if result.status != "completed":
        result.problems.append(f"task ended {result.status}")

    for tool, summary, ok in result.steps:
        if ok is False and any(fault in (summary or "") for fault in _OUR_FAULT):
            result.problems.append(f"{tool}: {summary[:70]}")

    dirty = git(repo, "status", "--short")
    if dirty and not trial.expect_file:
        result.problems.append(f"left the tree dirty: {dirty[:60]}")

    committed = "base" not in git(repo, "log", "--oneline", "-1")
    if trial.expect_commit and not committed:
        result.problems.append("nothing was committed")
    if trial.expect_no_change and committed:
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


async def main(names: list[str], timeout_s: float) -> int:
    chosen = [t for t in TRIALS if not names or t.name in names]
    results: list[Result] = []
    for trial in chosen:
        root = tempfile.mkdtemp(prefix=f"simorgh-{trial.name}-")
        try:
            results.append(await run_one(trial, root, timeout_s))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        last = results[-1]
        mark = "PASS" if last.ok else "FAIL"
        print(f"  {mark}  {trial.name:24s} {last.status:10s} {last.seconds:5.0f}s")
        for problem in last.problems:
            print(f"        - {problem}")

    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} clean")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the trial suite and score it.")
    parser.add_argument("names", nargs="*", help="only these trials (default: all)")
    parser.add_argument("--timeout", type=float, default=240.0)
    sys.exit(asyncio.run(main(parser.parse_args().names, parser.parse_args().timeout)))
