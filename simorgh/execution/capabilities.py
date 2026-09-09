"""Which of Sim's capabilities actually work right now.

Half of the toolset added on 2026-09-09 stands on something outside
this repository: Node and a bundled Chromium for `render_page`, an
optional pip package for `search_listings`, a keyless public API for
`geocode`, a linter for Guardian's `StaticAnalysisRule`. Each one is
allowed to be absent -- every tool refuses cleanly without it -- but
"absent" was invisible until a task tried and failed. An unofficial
source that quietly starts returning nothing is worse: the tool still
answers, so nothing looks broken.

This lives in `execution/` rather than `kernel/`: every capability it
probes belongs to a tool in this package, and a subsystem may not
import another's internals (tests/simorgh/test_module_boundaries.py).

This is the probe table. Cheap, local probes (is the binary there, does
the module import) run at boot; network probes are rate-limited hard,
because a probe that runs on every restart is a probe that gets the
machine blocked from the very service it is checking.

A failed probe is information, never an error: it degrades health,
shows up in `status`, and -- the part that saves a task -- is written
into the prompt, so the model does not spend three of its steps
discovering that `search_listings` is down today.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

CAPABILITIES_STREAM = "capabilities"

Cost = Literal["free", "cheap", "network"]


@dataclass(frozen=True)
class ProbeResult:
    name: str
    ok: bool
    detail: str
    cost: Cost
    at: float = 0.0


@dataclass(frozen=True)
class Probe:
    name: str
    cost: Cost
    run: Callable[[], Awaitable[tuple[bool, str]]]
    #  What stops working when this probe fails, named the way the model
    #  sees it, so a warning can say "search_listings is failing".
    tools: tuple[str, ...] = ()


async def _module(name: str) -> tuple[bool, str]:
    found = importlib.util.find_spec(name) is not None
    return found, f"{name} importable" if found else f"{name} is not installed"


async def _binary(name: str) -> tuple[bool, str]:
    path = shutil.which(name)
    return bool(path), path or f"{name} is not on PATH"


async def _node() -> tuple[bool, str]:
    return await _binary("node")


async def _puppeteer() -> tuple[bool, str]:
    npm = shutil.which("npm")
    if not npm:
        return False, "npm is not on PATH, so the global node_modules cannot be located"

    def _look() -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                [npm, "root", "-g"], capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"could not ask npm for its global root: {exc!r}"
        root = (completed.stdout or "").strip()
        if completed.returncode != 0 or not root:
            return False, "npm root -g produced nothing"
        from pathlib import Path

        return (Path(root) / "puppeteer").exists(), f"{root}/puppeteer"

    return await asyncio.to_thread(_look)


async def _docker() -> tuple[bool, str]:
    docker = shutil.which("docker") or "/Applications/Docker.app/Contents/Resources/bin/docker"

    def _info() -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                text=True, timeout=15, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"docker is not usable: {exc!r}"
        if completed.returncode != 0:
            return False, "the Docker daemon is not running"
        return True, f"docker {completed.stdout.strip()}"

    return await asyncio.to_thread(_info)


async def _bandit() -> tuple[bool, str]:
    return await _module("bandit")


async def _homeharvest() -> tuple[bool, str]:
    return await _module("homeharvest")


PROBES: tuple[Probe, ...] = (
    Probe("node", "free", _node, tools=("run_js_sandboxed", "render_page")),
    Probe("puppeteer", "cheap", _puppeteer, tools=("render_page",)),
    Probe("bandit", "free", _bandit, tools=("guardian static analysis",)),
    Probe("homeharvest", "free", _homeharvest, tools=("search_listings",)),
    Probe("docker", "cheap", _docker, tools=("run_container",)),
)


async def run_probes(probes: tuple[Probe, ...] = PROBES, *, include: tuple[Cost, ...] = ("free", "cheap"),
                     clock=None) -> list[ProbeResult]:
    """Run every probe whose cost is in `include`. Never raises: a probe
    that throws is a failed probe, not a crashed boot."""
    now = (clock or time.time)()
    results: list[ProbeResult] = []
    for probe in probes:
        if probe.cost not in include:
            continue
        try:
            ok, detail = await probe.run()
        except Exception as exc:  # noqa: BLE001 -- a probe is diagnostics; it may not break the thing it checks
            ok, detail = False, f"probe raised: {exc!r}"
        results.append(ProbeResult(probe.name, ok, str(detail)[:300], probe.cost, now))
    return results


def degraded_detail(results: list[ProbeResult]) -> str:
    """One line naming what is unavailable, or "" when all is well.

    Only *free* probes degrade health: a missing binary is a real fact
    about this machine, while a network probe failing may just mean the
    laptop is on a plane.
    """
    broken = [r for r in results if not r.ok and r.cost == "free"]
    if not broken:
        return ""
    return "unavailable: " + "; ".join(f"{r.name} ({r.detail})" for r in broken)


def warnings_for_prompt(results: list[ProbeResult], offered: tuple[str, ...]) -> str:
    """What to tell the model about tools it is being offered that are
    known not to work right now. Empty when there is nothing to say --
    the common case, and it must cost nothing in the prompt."""
    lines = []
    for result in results:
        if result.ok:
            continue
        probe = next((p for p in PROBES if p.name == result.name), None)
        affected = [t for t in (probe.tools if probe else ()) if t in offered]
        if affected:
            lines.append(f"- {', '.join(affected)}: unavailable right now ({result.detail})")
    if not lines:
        return ""
    return "Not working in this session, do not spend steps on them:\n" + "\n".join(lines)
