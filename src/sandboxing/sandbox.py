"""Sandboxed execution framework for skill agents.

Skill agents may need to run arbitrary or generated code on the system's
behalf. To keep that isolated from the persona's core cognitive state
(PersonaState / SharedMemoryBus), skill code never runs in-process: it is
handed to a SandboxExecutor, which runs it in a separate, resource- and
time-bounded OS process with no access to this process's objects. Only a
plain SandboxResult (text + exit code) comes back across that boundary.

SubprocessSandbox below uses process isolation, CPU/memory rlimits, and a
wall-clock timeout -- the portable primitives available in the standard
library on POSIX systems. It is NOT equivalent to true microVM-grade
isolation (no network or filesystem namespacing, no seccomp filtering).
Callers depend only on the SandboxExecutor interface, so swapping in a
Firecracker- or gVisor-backed executor later is a drop-in change.
"""

from __future__ import annotations

import abc
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import resource
except ImportError:  # resource is POSIX-only; unavailable on Windows
    resource = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SandboxResult:
    """The outcome of running skill code in a sandbox."""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.exit_code == 0


class SandboxExecutor(abc.ABC):
    """Interface for running untrusted skill code in isolation.

    Skill agents depend only on this interface, never a concrete
    implementation, so the isolation backend can change without touching
    agent code.
    """

    @abc.abstractmethod
    def run(
        self,
        code: str,
        *,
        timeout: float = 5.0,
        input_data: str | None = None,
    ) -> SandboxResult:
        """Execute `code` in isolation and return its result. Must never
        raise on the sandboxed code's own errors -- failures are reported
        via `SandboxResult.exit_code` / `.stderr` / `.timed_out`.
        """
        raise NotImplementedError


class SubprocessSandbox(SandboxExecutor):
    """Runs skill code as a fresh, throwaway Python subprocess with CPU,
    memory, and wall-clock limits and an empty environment.

    The subprocess never receives a reference to the orchestrator's
    PersonaState or SharedMemoryBus -- it only ever sees the `code` string
    and returns text -- so a misbehaving or malicious skill cannot read or
    corrupt the persona's cognitive state.
    """

    def __init__(
        self, cpu_seconds: int = 5, memory_bytes: int = 256 * 1024 * 1024
    ) -> None:
        self._cpu_seconds = cpu_seconds
        self._memory_bytes = memory_bytes

    def run(
        self,
        code: str,
        *,
        timeout: float = 5.0,
        input_data: str | None = None,
    ) -> SandboxResult:
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-sandbox-") as workdir:
            script_path = Path(workdir) / "skill.py"
            script_path.write_text(code)
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", str(script_path)],
                    input=input_data,
                    capture_output=True,
                    text=True,
                    cwd=workdir,
                    env={},
                    timeout=timeout,
                    preexec_fn=self._apply_rlimits if resource else None,
                )
            except subprocess.TimeoutExpired as exc:
                return SandboxResult(
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                    exit_code=None,
                    timed_out=True,
                    duration_seconds=time.monotonic() - start,
                )
            return SandboxResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                timed_out=False,
                duration_seconds=time.monotonic() - start,
            )

    def _apply_rlimits(self) -> None:
        # Each limit is applied best-effort: some platforms (notably macOS)
        # cap certain resources below what we ask for, or don't support
        # them at all. A limit we can't set is skipped rather than aborting
        # the whole sandboxed run.
        for res, value in (
            (getattr(resource, "RLIMIT_CPU", None), self._cpu_seconds),
            (getattr(resource, "RLIMIT_AS", None), self._memory_bytes),
            (getattr(resource, "RLIMIT_CORE", None), 0),
        ):
            if res is None:
                continue
            try:
                resource.setrlimit(res, (value, value))
            except (ValueError, OSError):
                pass
